from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import ontology_core.management.imports as imports_module
from ontology_core.errors import OntologyError
from ontology_core.management.imports import BatchImportService, UploadPayload
from ontology_core.management.models import DraftDataSource, UploadLimits, WorkspaceDraft
from ontology_core.management.parsers import ParsedUpload, parse_metadata_upload
from ontology_core.management.store import FileDraftStore, OntologyManagementStoreError

LIMITS = UploadLimits(max_upload_bytes=1_000_000, max_xlsx_uncompressed_bytes=100_000)
HEADER = "对象英文名称\t对象中文名称\t对象描述\t属性英文名\t属性中文名\t属性类型\t属性描述\n"
TABLE_A = HEADER + "DEMO_ACCOUNT\t账户\t账户表\tACCOUNT_ID\t账户编号\tbigint\t稳定主键\n"
TABLE_B = HEADER + "DEMO_CUSTOMER\t客户\t客户表\tCUSTOMER_ID\t客户编号\tbigint\t稳定主键\n"
TABLE_C = HEADER + "DEMO_ORDER\t订单\t订单表\tORDER_ID\t订单编号\tbigint\t稳定主键\n"


def upload(file_name: str, table: str) -> UploadPayload:
    return UploadPayload(file_name=file_name, content=table.encode("utf-8"))


def workspace(*, objects: tuple = ()) -> WorkspaceDraft:
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
        objects=objects,
    )


def import_service(
    tmp_path: Path,
    *,
    objects: tuple = (),
    now: datetime | None = None,
) -> tuple[BatchImportService, FileDraftStore, list[datetime]]:
    store = FileDraftStore(tmp_path)
    store.create_workspace(workspace(objects=objects))
    clock = [now or datetime(2026, 8, 25, tzinfo=UTC)]
    return (
        BatchImportService(
            store,
            limits=LIMITS,
            token_ttl=timedelta(minutes=5),
            now=lambda: clock[0],
        ),
        store,
        clock,
    )


def draft_bytes(tmp_path: Path) -> bytes:
    return (tmp_path / "workspaces" / "evaluation" / "draft.json").read_bytes()


def assert_failure_preserves_draft(
    tmp_path: Path,
    store: FileDraftStore,
    action: object,
    *,
    code: str,
) -> None:
    before = draft_bytes(tmp_path)
    revision = store.read("evaluation").revision

    with pytest.raises(OntologyError) as exc_info:
        action()

    assert exc_info.value.code == code
    assert draft_bytes(tmp_path) == before
    assert store.read("evaluation").revision == revision


def test_preview_of_three_unique_objects_issues_one_token_without_mutating_draft(
    tmp_path: Path,
) -> None:
    service, store, _ = import_service(tmp_path)
    before = draft_bytes(tmp_path)

    preview = service.preview(
        "evaluation",
        expected_revision=0,
        uploads=(
            upload("accounts.tsv", TABLE_A),
            upload("customers.tsv", TABLE_B),
            upload("orders.tsv", TABLE_C),
        ),
    )

    assert preview.status == "ready"
    assert preview.token is not None
    assert preview.object_count == 3
    assert preview.field_count == 3
    assert not [item for item in preview.diagnostics if item.severity == "error"]
    assert draft_bytes(tmp_path) == before
    session_path = next((tmp_path / "import_sessions").glob("*.json"))
    assert preview.token.encode("utf-8") not in session_path.read_bytes()
    assert store.read("evaluation").revision == 0


def test_duplicate_inside_one_file_blocks_whole_preview_without_draft_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, store, _ = import_service(tmp_path)
    before = draft_bytes(tmp_path)
    candidate = parse_metadata_upload("source.tsv", TABLE_A.encode("utf-8"), LIMITS).objects[0]
    duplicate = candidate.model_copy(update={"physical_name": "demo_account"})

    def parse_duplicate(*_: object) -> ParsedUpload:
        return ParsedUpload(
            file_name="duplicates.tsv",
            sha256="a" * 64,
            objects=(candidate, duplicate),
            diagnostics=(),
        )

    monkeypatch.setattr(imports_module, "parse_metadata_upload", parse_duplicate)

    preview = service.preview(
        "evaluation", expected_revision=0, uploads=(upload("duplicates.tsv", TABLE_A),)
    )

    assert preview.status == "blocked"
    assert preview.token is None
    assert {item.code for item in preview.diagnostics if item.severity == "error"} == {
        "duplicate_object_in_batch"
    }
    diagnostic = next(
        item for item in preview.diagnostics if item.code == "duplicate_object_in_batch"
    )
    assert diagnostic.related_ids == ("object/demo_account",)
    assert draft_bytes(tmp_path) == before
    assert store.read("evaluation").revision == 0
    assert not (tmp_path / "import_sessions").exists()


def test_duplicate_across_files_blocks_whole_preview_without_draft_mutation(tmp_path: Path) -> None:
    service, store, _ = import_service(tmp_path)
    before = draft_bytes(tmp_path)

    preview = service.preview(
        "evaluation",
        expected_revision=0,
        uploads=(upload("one.tsv", TABLE_A), upload("two.tsv", TABLE_A)),
    )

    assert preview.status == "blocked"
    assert preview.token is None
    assert {item.code for item in preview.diagnostics if item.severity == "error"} == {
        "duplicate_object_in_batch"
    }
    diagnostic = next(
        item for item in preview.diagnostics if item.code == "duplicate_object_in_batch"
    )
    assert diagnostic.related_ids == ("object/demo_account",)
    assert draft_bytes(tmp_path) == before
    assert store.read("evaluation").revision == 0
    assert not (tmp_path / "import_sessions").exists()


def test_draft_duplicate_blocks_whole_preview_without_draft_mutation(tmp_path: Path) -> None:
    existing = parse_metadata_upload("existing.tsv", TABLE_A.encode("utf-8"), LIMITS).objects
    service, store, _ = import_service(tmp_path, objects=existing)
    before = draft_bytes(tmp_path)

    preview = service.preview(
        "evaluation", expected_revision=0, uploads=(upload("new.tsv", TABLE_A),)
    )

    assert preview.status == "blocked"
    assert preview.token is None
    diagnostic = next(
        item for item in preview.diagnostics if item.code == "duplicate_object_in_draft"
    )
    assert diagnostic.related_ids == ("object/demo_account",)
    assert draft_bytes(tmp_path) == before
    assert store.read("evaluation").revision == 0


def test_parser_error_blocks_whole_preview_without_a_token(tmp_path: Path) -> None:
    service, store, _ = import_service(tmp_path)
    before = draft_bytes(tmp_path)

    preview = service.preview(
        "evaluation",
        expected_revision=0,
        uploads=(UploadPayload(file_name="invalid.tsv", content=b"wrong\theader\nvalue\tvalue\n"),),
    )

    assert preview.status == "blocked"
    assert preview.token is None
    assert "ontology_import_error" in {item.code for item in preview.diagnostics}
    assert draft_bytes(tmp_path) == before
    assert store.read("evaluation").revision == 0


@pytest.mark.parametrize("file_name", (r"C:\private\file.tsv", "../../file.tsv", "C:file.tsv"))
def test_preview_diagnostics_keep_only_a_safe_upload_basename(
    tmp_path: Path, file_name: str
) -> None:
    service, _, _ = import_service(tmp_path)
    content = (
        HEADER + "DEMO_ACCOUNT\t账户\t账户表\tBAD-NAME\t字段\tbigint\tRAW_ROW_SECRET\n"
    ).encode("utf-8")

    preview = service.preview(
        "evaluation",
        expected_revision=0,
        uploads=(UploadPayload(file_name=file_name, content=content),),
    )

    diagnostic = next(
        item for item in preview.diagnostics if item.code == "invalid_field_identifier"
    )
    assert "file.tsv" in diagnostic.message
    assert "C:" not in diagnostic.message
    assert "private" not in diagnostic.message
    assert ".." not in diagnostic.message
    assert "RAW_ROW_SECRET" not in diagnostic.message
    assert diagnostic.related_ids == ("object/demo_account", "field/demo_account/bad-name")


def test_empty_upload_blocks_whole_preview_without_a_token(tmp_path: Path) -> None:
    service, store, _ = import_service(tmp_path)
    before = draft_bytes(tmp_path)

    preview = service.preview(
        "evaluation",
        expected_revision=0,
        uploads=(UploadPayload(file_name="empty.tsv", content=b""),),
    )

    assert preview.status == "blocked"
    assert preview.token is None
    assert "ontology_import_error" in {item.code for item in preview.diagnostics}
    assert draft_bytes(tmp_path) == before
    assert store.read("evaluation").revision == 0


def test_confirm_appends_the_entire_ready_batch_in_one_revision(tmp_path: Path) -> None:
    service, store, _ = import_service(tmp_path)
    preview = service.preview(
        "evaluation",
        expected_revision=0,
        uploads=(
            upload("accounts.tsv", TABLE_A),
            upload("customers.tsv", TABLE_B),
            upload("orders.tsv", TABLE_C),
        ),
    )
    assert preview.token is not None

    updated = service.confirm("evaluation", preview.token, expected_revision=0)

    assert updated.revision == 1
    assert [item.physical_name for item in updated.objects] == [
        "DEMO_ACCOUNT",
        "DEMO_CUSTOMER",
        "DEMO_ORDER",
    ]
    assert store.read("evaluation") == updated


def test_confirm_stale_revision_preserves_draft_bytes_and_revision(tmp_path: Path) -> None:
    service, store, _ = import_service(tmp_path)
    preview = service.preview(
        "evaluation", expected_revision=0, uploads=(upload("accounts.tsv", TABLE_A),)
    )
    assert preview.token is not None
    store.commit(
        "evaluation", 0, lambda draft: draft.model_copy(update={"display_name": "Updated"})
    )

    assert_failure_preserves_draft(
        tmp_path,
        store,
        lambda: service.confirm("evaluation", preview.token or "", expected_revision=0),
        code="draft_revision_conflict",
    )


def test_confirm_for_the_wrong_workspace_preserves_draft_bytes_and_revision(
    tmp_path: Path,
) -> None:
    service, store, _ = import_service(tmp_path)
    preview = service.preview(
        "evaluation", expected_revision=0, uploads=(upload("accounts.tsv", TABLE_A),)
    )
    assert preview.token is not None

    assert_failure_preserves_draft(
        tmp_path,
        store,
        lambda: service.confirm("other", preview.token or "", expected_revision=0),
        code="import_token_workspace_mismatch",
    )


def test_expired_token_preserves_draft_bytes_and_revision(tmp_path: Path) -> None:
    service, store, clock = import_service(tmp_path)
    preview = service.preview(
        "evaluation", expected_revision=0, uploads=(upload("accounts.tsv", TABLE_A),)
    )
    assert preview.token is not None
    clock[0] += timedelta(minutes=6)

    assert_failure_preserves_draft(
        tmp_path,
        store,
        lambda: service.confirm("evaluation", preview.token or "", expected_revision=0),
        code="import_token_expired",
    )


def test_changed_canonical_candidate_digest_preserves_draft_bytes_and_revision(
    tmp_path: Path,
) -> None:
    service, store, _ = import_service(tmp_path)
    preview = service.preview(
        "evaluation", expected_revision=0, uploads=(upload("accounts.tsv", TABLE_A),)
    )
    assert preview.token is not None
    session = store.read_import_session(preview.token)
    changed = session.objects[0].model_copy(update={"label": "Changed"})
    store.write_import_session(preview.token, session.model_copy(update={"objects": (changed,)}))

    assert_failure_preserves_draft(
        tmp_path,
        store,
        lambda: service.confirm("evaluation", preview.token or "", expected_revision=0),
        code="import_digest_mismatch",
    )


def test_confirm_rechecks_session_under_the_workspace_commit_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, store, _ = import_service(tmp_path)
    preview = service.preview(
        "evaluation", expected_revision=0, uploads=(upload("accounts.tsv", TABLE_A),)
    )
    assert preview.token is not None
    original_read = store.read_import_session
    calls = 0

    def read_session(token: str):
        nonlocal calls
        calls += 1
        session = original_read(token)
        if calls == 2:
            return session.model_copy(update={"committed_revision": 1})
        return session

    monkeypatch.setattr(store, "read_import_session", read_session)

    assert_failure_preserves_draft(
        tmp_path,
        store,
        lambda: service.confirm("evaluation", preview.token or "", expected_revision=0),
        code="import_token_used",
    )
    assert calls == 2


def test_used_token_preserves_draft_bytes_and_revision(tmp_path: Path) -> None:
    service, store, _ = import_service(tmp_path)
    preview = service.preview(
        "evaluation", expected_revision=0, uploads=(upload("accounts.tsv", TABLE_A),)
    )
    assert preview.token is not None
    service.confirm("evaluation", preview.token, expected_revision=0)

    assert_failure_preserves_draft(
        tmp_path,
        store,
        lambda: service.confirm("evaluation", preview.token or "", expected_revision=1),
        code="import_token_used",
    )
    final_draft = store.read("evaluation")
    assert final_draft.revision == 1
    assert len(final_draft.objects) == 1


def test_commit_failure_preserves_draft_bytes_and_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, store, _ = import_service(tmp_path)
    preview = service.preview(
        "evaluation", expected_revision=0, uploads=(upload("accounts.tsv", TABLE_A),)
    )
    assert preview.token is not None

    def fail_commit(*_: object) -> WorkspaceDraft:
        raise OntologyManagementStoreError(operation="write")

    monkeypatch.setattr(store, "commit", fail_commit)

    assert_failure_preserves_draft(
        tmp_path,
        store,
        lambda: service.confirm("evaluation", preview.token or "", expected_revision=0),
        code="ontology_management_store_error",
    )


def test_marker_write_failure_preserves_draft_bytes_and_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, store, _ = import_service(tmp_path)
    preview = service.preview(
        "evaluation", expected_revision=0, uploads=(upload("accounts.tsv", TABLE_A),)
    )
    assert preview.token is not None
    original_write = store.write_import_session

    def fail_marker_write(_: str, __: object) -> object:
        raise OntologyManagementStoreError(operation="write")

    monkeypatch.setattr(store, "write_import_session", fail_marker_write)

    assert_failure_preserves_draft(
        tmp_path,
        store,
        lambda: service.confirm("evaluation", preview.token or "", expected_revision=0),
        code="ontology_management_store_error",
    )
    monkeypatch.setattr(store, "write_import_session", original_write)
    updated = service.confirm("evaluation", preview.token, expected_revision=0)

    assert updated.revision == 1
    assert len(updated.objects) == 1
    assert_failure_preserves_draft(
        tmp_path,
        store,
        lambda: service.confirm("evaluation", preview.token or "", expected_revision=1),
        code="import_token_used",
    )
    final_draft = store.read("evaluation")
    assert final_draft.revision == 1
    assert len(final_draft.objects) == 1


def test_draft_replace_failure_after_marker_burns_the_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, store, _ = import_service(tmp_path)
    preview = service.preview(
        "evaluation", expected_revision=0, uploads=(upload("accounts.tsv", TABLE_A),)
    )
    assert preview.token is not None
    original_atomic_write = store._atomic_write

    def fail_draft_replace(path: Path, content: bytes) -> None:
        if path.name == "draft.json":
            raise OSError("draft replacement failed")
        original_atomic_write(path, content)

    monkeypatch.setattr(store, "_atomic_write", fail_draft_replace)

    assert_failure_preserves_draft(
        tmp_path,
        store,
        lambda: service.confirm("evaluation", preview.token or "", expected_revision=0),
        code="ontology_management_store_error",
    )
    assert store.read_import_session(preview.token).committed_revision == 1
    assert_failure_preserves_draft(
        tmp_path,
        store,
        lambda: service.confirm("evaluation", preview.token or "", expected_revision=0),
        code="import_token_used",
    )


def test_cleanup_failure_marks_token_used_before_returning_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, store, _ = import_service(tmp_path)
    preview = service.preview(
        "evaluation", expected_revision=0, uploads=(upload("accounts.tsv", TABLE_A),)
    )
    assert preview.token is not None

    def fail_cleanup(_: str) -> object:
        raise OntologyManagementStoreError(operation="delete")

    monkeypatch.setattr(store, "consume_import_session", fail_cleanup)
    before = draft_bytes(tmp_path)

    with pytest.raises(OntologyError) as exc_info:
        service.confirm("evaluation", preview.token, expected_revision=0)

    assert exc_info.value.code == "ontology_management_store_error"
    assert store.read("evaluation").revision == 1
    assert draft_bytes(tmp_path) != before
    assert store.read_import_session(preview.token).committed_revision == 1
    assert_failure_preserves_draft(
        tmp_path,
        store,
        lambda: service.confirm("evaluation", preview.token or "", expected_revision=1),
        code="import_token_used",
    )
