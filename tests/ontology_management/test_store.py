from __future__ import annotations

import hashlib
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ontology_core.errors import OntologyError
from ontology_core.management.models import DraftDataSource, ImportSession, WorkspaceDraft
from ontology_core.management.paths import OntologyManagementConfigurationError
from ontology_core.management.store import DraftRevisionConflict, FileDraftStore


def synthetic_workspace() -> WorkspaceDraft:
    return WorkspaceDraft(
        workspace_id="evaluation",
        display_name="Evaluation",
        package_id="package/evaluation",
        base_uri="https://example.test/ontology/evaluation#",
        revision=0,
        updated_at=datetime(2026, 8, 25, tzinfo=UTC),
        data_source=DraftDataSource(
            id="source/evaluation",
            label="Evaluation source",
            platform_type="generic_sql",
            physical_namespace="evaluation",
        ),
    )


def test_store_rejects_a_root_inside_the_discovered_git_worktree() -> None:
    repository_root = Path(__file__).resolve().parents[2]

    with pytest.raises(OntologyManagementConfigurationError, match="Git 工作树之外"):
        FileDraftStore(repository_root / ".management-data")


def initialized_store(tmp_path: Path) -> FileDraftStore:
    store = FileDraftStore(tmp_path)
    store.create_workspace(synthetic_workspace())
    return store


def draft_bytes(tmp_path: Path) -> bytes:
    return (tmp_path / "workspaces" / "evaluation" / "draft.json").read_bytes()


def synthetic_import_session(token: str) -> ImportSession:
    created_at = datetime(2026, 8, 25, tzinfo=UTC)
    return ImportSession(
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        workspace_id="evaluation",
        expected_revision=0,
        content_digest="a" * 64,
        created_at=created_at,
        expires_at=created_at + timedelta(minutes=15),
    )


def test_create_workspace_persists_and_reads_canonical_draft(tmp_path: Path) -> None:
    store = FileDraftStore(tmp_path)
    draft = synthetic_workspace()

    created = store.create_workspace(draft)

    assert created == draft
    assert draft_bytes(tmp_path) == draft.canonical_json().encode("utf-8")
    assert store.read("evaluation") == draft


def test_commit_is_atomic_and_increments_revision_once(tmp_path: Path) -> None:
    store = initialized_store(tmp_path)
    before = draft_bytes(tmp_path)

    updated = store.commit(
        "evaluation",
        0,
        lambda draft: draft.model_copy(update={"display_name": "评测包"}),
    )

    assert updated.revision == 1
    assert store.read("evaluation").display_name == "评测包"
    assert before != draft_bytes(tmp_path)


def test_stale_revision_leaves_draft_bytes_unchanged(tmp_path: Path) -> None:
    store = initialized_store(tmp_path)
    before = draft_bytes(tmp_path)

    with pytest.raises(DraftRevisionConflict) as exc_info:
        store.commit("evaluation", 9, lambda draft: draft)

    assert exc_info.value.status_code == 409
    assert exc_info.value.details["current_revision"] == 0
    assert draft_bytes(tmp_path) == before


def test_callback_failure_leaves_draft_bytes_unchanged(tmp_path: Path) -> None:
    store = initialized_store(tmp_path)
    before = draft_bytes(tmp_path)

    def fail(_: WorkspaceDraft) -> WorkspaceDraft:
        raise RuntimeError("mutation failed")

    with pytest.raises(RuntimeError, match="mutation failed"):
        store.commit("evaluation", 0, fail)

    assert draft_bytes(tmp_path) == before


def test_replace_failure_keeps_original_draft_and_removes_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = initialized_store(tmp_path)
    before = draft_bytes(tmp_path)

    def fail_replace(_: Path, __: Path) -> None:
        raise OSError(f"replace failed for {tmp_path}")

    monkeypatch.setattr("ontology_core.management.store.os.replace", fail_replace)

    with pytest.raises(OntologyError) as exc_info:
        store.commit("evaluation", 0, lambda draft: draft)

    assert exc_info.value.code == "ontology_management_store_error"
    assert exc_info.value.message == "本体管理存储操作失败"
    assert exc_info.value.details == {"operation": "write"}
    assert str(tmp_path) not in str(exc_info.value)
    assert str(tmp_path) not in str(exc_info.value.details)
    assert isinstance(exc_info.value.__cause__, OSError)
    assert draft_bytes(tmp_path) == before
    assert list((tmp_path / "workspaces" / "evaluation").glob(".draft.json.*.tmp")) == []


def test_read_filesystem_failure_is_a_path_free_store_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = initialized_store(tmp_path)
    before = draft_bytes(tmp_path)
    original_read_bytes = Path.read_bytes

    def fail_read(_: Path) -> bytes:
        raise OSError(f"read failed for {tmp_path}")

    monkeypatch.setattr(Path, "read_bytes", fail_read)

    with pytest.raises(OntologyError) as exc_info:
        store.read("evaluation")

    assert exc_info.value.code == "ontology_management_store_error"
    assert exc_info.value.message == "本体管理存储操作失败"
    assert exc_info.value.details == {"operation": "read"}
    assert str(tmp_path) not in str(exc_info.value)
    assert str(tmp_path) not in str(exc_info.value.details)
    assert isinstance(exc_info.value.__cause__, OSError)
    monkeypatch.setattr(Path, "read_bytes", original_read_bytes)
    assert before == (tmp_path / "workspaces" / "evaluation" / "draft.json").read_bytes()


def test_concurrent_writers_allow_exactly_one_commit_per_revision(tmp_path: Path) -> None:
    store = initialized_store(tmp_path)
    barrier = threading.Barrier(2)
    results: list[WorkspaceDraft] = []
    conflicts: list[DraftRevisionConflict] = []

    def commit(display_name: str) -> None:
        barrier.wait()
        try:
            results.append(
                store.commit(
                    "evaluation",
                    0,
                    lambda draft: draft.model_copy(update={"display_name": display_name}),
                )
            )
        except DraftRevisionConflict as error:
            conflicts.append(error)

    first = threading.Thread(target=commit, args=("First",))
    second = threading.Thread(target=commit, args=("Second",))
    first.start()
    second.start()
    first.join()
    second.join()

    assert [result.revision for result in results] == [1]
    assert [error.details["current_revision"] for error in conflicts] == [1]
    assert store.read("evaluation").revision == 1


def test_import_session_is_addressed_by_hash_and_marked_consumed_without_token_persistence(
    tmp_path: Path,
) -> None:
    store = FileDraftStore(tmp_path)
    token = "bearer-token-that-must-not-reach-disk"
    session = synthetic_import_session(token)

    stored = store.write_import_session(token, session)
    session_path = tmp_path / "import_sessions" / f"{session.token_hash}.json"

    assert stored == session
    assert session_path.is_file()
    assert token.encode("utf-8") not in session_path.read_bytes()
    assert store.read_import_session(token) == session
    consumed = store.consume_import_session(token)

    assert consumed.consumed_at is not None
    assert session_path.is_file()
    assert token.encode("utf-8") not in session_path.read_bytes()
    assert store.read_import_session(token) == consumed
