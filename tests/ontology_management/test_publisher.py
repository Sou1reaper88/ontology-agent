from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent.ontology_shadow import OntologyRuntime
from ontology_core.errors import OntologyValidationError, PackageNotFoundError
from ontology_core.management.models import (
    DraftDataSource,
    DraftField,
    DraftObject,
    WorkspaceDraft,
)
from ontology_core.management.publisher import (
    OntologyPublishError,
    PackagePublisher,
    VersionAlreadyExistsError,
)
from ontology_core.management.store import FileDraftStore

PACKAGE_FILES = {
    "manifest.yaml",
    "core.ttl",
    "domain.ttl",
    "mappings.ttl",
    "rules.ttl",
    "shapes.ttl",
}

def _draft(*, revision: int = 1) -> WorkspaceDraft:
    return WorkspaceDraft(
        workspace_id="evaluation",
        display_name="Synthetic evaluation",
        package_id="tests.evaluation",
        base_uri="https://example.invalid/tests/evaluation/",
        revision=revision,
        updated_at=datetime(2026, 8, 26, tzinfo=UTC),
        data_source=DraftDataSource(
            id="source/evaluation",
            label="Synthetic source",
            platform_type="generic_sql",
            dialect="generic",
            physical_namespace="synthetic",
        ),
        objects=(
            DraftObject(
                id="object/stable_customer",
                physical_name="SYNTHETIC_CUSTOMER",
                label="Synthetic customer",
                description="Synthetic object used only by tests",
                fields=(
                    DraftField(
                        id="field/stable_customer/customer_id",
                        physical_name="CUSTOMER_ID",
                        label="Synthetic customer identifier",
                        description="Synthetic key used only by tests",
                        xsd_type="string",
                        primary_key=True,
                    ),
                ),
            ),
        ),
    )


def _publisher(tmp_path: Path) -> tuple[PackagePublisher, OntologyRuntime]:
    root = tmp_path / "management"
    store = FileDraftStore(root)
    store.create_workspace(_draft())
    runtime = OntologyRuntime()
    return PackagePublisher(store, root, runtime), runtime


def _published_v1(tmp_path: Path) -> tuple[PackagePublisher, OntologyRuntime]:
    publisher, runtime = _publisher(tmp_path)
    publisher.publish("evaluation", "1.0.0", "first", 1, "tester")
    return publisher, runtime


def _version_dir(tmp_path: Path, version: str) -> Path:
    return tmp_path / "management" / "workspaces" / "evaluation" / "versions" / version


def _active_pointer_path(tmp_path: Path) -> Path:
    return tmp_path / "management" / "workspaces" / "evaluation" / "active-version.json"


def _version_metadata_path(tmp_path: Path, version: str) -> Path:
    return (
        tmp_path
        / "management"
        / "workspaces"
        / "evaluation"
        / "version-metadata"
        / f"{version}.json"
    )


def _remove_version_directory(tmp_path: Path, version: str) -> None:
    target = _version_dir(tmp_path, version)
    for item in target.iterdir():
        item.unlink()
    target.rmdir()


def _directory_bytes(path: Path) -> dict[str, bytes]:
    return {
        item.relative_to(path).as_posix(): item.read_bytes()
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }


def test_publish_commits_six_immutable_files_and_hot_installs_stable_ids(
    tmp_path: Path,
) -> None:
    publisher, runtime = _publisher(tmp_path)

    summary = publisher.publish("evaluation", "1.0.0", "first", 1, "tester")

    version_dir = _version_dir(tmp_path, "1.0.0")
    assert {item.name for item in version_dir.iterdir()} == PACKAGE_FILES
    assert summary.version == "1.0.0"
    assert summary.revision == 1
    assert summary.active is True
    pointer = json.loads(
        (tmp_path / "management/workspaces/evaluation/active-version.json").read_text(
            encoding="utf-8"
        )
    )
    assert pointer["version"] == "1.0.0"
    snapshot = runtime.snapshot()
    assert snapshot.info.version == "1.0.0"
    assert snapshot.info.source == str(version_dir.resolve())
    assert snapshot.catalog.concepts[0].uri.endswith("/concept/object%2Fstable_customer")
    assert snapshot.catalog.properties[0].uri.endswith(
        "/property/field%2Fstable_customer%2Fcustomer_id"
    )
    assert runtime.health().status == "ok"


def test_publish_records_validated_package_counts_and_content_digest(tmp_path: Path) -> None:
    publisher, _ = _publisher(tmp_path)

    summary = publisher.publish("evaluation", "1.0.0", "first", 1, "tester")

    assert summary.counts is not None
    assert summary.counts.concepts == 1
    assert summary.counts.properties == 1
    assert summary.counts.relations == 0
    assert summary.counts.temporal_policies == 0
    assert summary.content_digest is not None
    assert len(summary.content_digest) == 64
    assert set(summary.content_digest) <= set("0123456789abcdef")
    persisted = json.loads(_version_metadata_path(tmp_path, "1.0.0").read_text(encoding="utf-8"))
    assert persisted["counts"] == summary.counts.model_dump(mode="json")
    assert persisted["content_digest"] == summary.content_digest


def test_legacy_version_metadata_without_counts_or_digest_remains_readable(tmp_path: Path) -> None:
    publisher, _ = _published_v1(tmp_path)
    path = _version_metadata_path(tmp_path, "1.0.0")
    metadata = json.loads(path.read_text(encoding="utf-8"))
    metadata.pop("counts", None)
    metadata.pop("content_digest", None)
    path.write_text(json.dumps(metadata), encoding="utf-8")

    version = publisher.list_versions("evaluation")[0]

    assert version.counts is None
    assert version.content_digest is None


def test_version_reuse_is_rejected_before_build(tmp_path: Path, monkeypatch) -> None:
    publisher, runtime = _published_v1(tmp_path)
    old_sha = runtime.snapshot().info.sha256

    def unexpected_build(*args, **kwargs):
        raise AssertionError("builder must not run for a reused version")

    monkeypatch.setattr(publisher._builder, "build", unexpected_build)

    with pytest.raises(VersionAlreadyExistsError):
        publisher.publish("evaluation", "1.0.0", "reuse", 1, "tester")

    assert runtime.snapshot().info.sha256 == old_sha
    assert publisher.active_version("evaluation").version == "1.0.0"


def test_version_metadata_reserves_version_after_package_directory_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher, _ = _published_v1(tmp_path)
    _remove_version_directory(tmp_path, "1.0.0")
    _active_pointer_path(tmp_path).unlink()

    def unexpected_build(*args, **kwargs):
        raise AssertionError("builder must not run for a metadata-reserved version")

    monkeypatch.setattr(publisher._builder, "build", unexpected_build)

    with pytest.raises(VersionAlreadyExistsError):
        publisher.publish("evaluation", "1.0.0", "different bytes", 1, "tester")

    assert not _version_dir(tmp_path, "1.0.0").exists()
    assert _version_metadata_path(tmp_path, "1.0.0").is_file()
    assert list(_version_dir(tmp_path, "1.0.0").parent.iterdir()) == []


def test_active_pointer_reserves_version_when_package_and_metadata_are_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher, _ = _published_v1(tmp_path)
    _remove_version_directory(tmp_path, "1.0.0")
    _version_metadata_path(tmp_path, "1.0.0").unlink()

    def unexpected_build(*args, **kwargs):
        raise AssertionError("builder must not run for an active-pointer-reserved version")

    monkeypatch.setattr(publisher._builder, "build", unexpected_build)

    with pytest.raises(VersionAlreadyExistsError):
        publisher.publish("evaluation", "1.0.0", "different bytes", 1, "tester")

    assert not _version_dir(tmp_path, "1.0.0").exists()
    assert publisher.active_version("evaluation").version == "1.0.0"
    assert list(_version_dir(tmp_path, "1.0.0").parent.iterdir()) == []


@pytest.mark.parametrize(
    ("boundary", "error"),
    [
        ("build", RuntimeError("synthetic build failure")),
        ("validation", OntologyValidationError("synthetic validation failure")),
        ("rename", OSError("synthetic rename failure")),
    ],
)
def test_pre_activation_failures_keep_old_runtime_and_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    error: Exception,
) -> None:
    publisher, runtime = _published_v1(tmp_path)
    old_sha = runtime.snapshot().info.sha256
    old_pointer = publisher.active_version("evaluation")

    def fail(*args, **kwargs):
        raise error

    target = {
        "build": publisher._builder,
        "validation": publisher,
        "rename": publisher,
    }[boundary]
    attribute = {
        "build": "build",
        "validation": "_load_candidate",
        "rename": "_commit_version",
    }[boundary]
    monkeypatch.setattr(target, attribute, fail)

    with pytest.raises(OntologyPublishError):
        publisher.publish("evaluation", "1.1.0", "second", 1, "tester")

    assert runtime.snapshot().info.sha256 == old_sha
    assert publisher.active_version("evaluation") == old_pointer
    assert not _version_dir(tmp_path, "1.1.0").exists()


def test_pointer_failure_keeps_old_runtime_and_active_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher, runtime = _published_v1(tmp_path)
    old_sha = runtime.snapshot().info.sha256

    def raising_os_error(*args, **kwargs) -> None:
        raise OSError("synthetic pointer failure")

    monkeypatch.setattr(publisher, "_write_active_pointer", raising_os_error)

    with pytest.raises(OntologyPublishError):
        publisher.publish("evaluation", "1.1.0", "second", 1, "tester")

    assert runtime.snapshot().info.sha256 == old_sha
    assert publisher.active_version("evaluation").version == "1.0.0"
    assert _version_dir(tmp_path, "1.1.0").is_dir()
    versions = publisher.list_versions("evaluation")
    assert [(item.version, item.active) for item in versions] == [
        ("1.0.0", True),
        ("1.1.0", False),
    ]


def test_rollback_only_switches_pointer_and_runtime(tmp_path: Path) -> None:
    publisher, runtime = _published_v1(tmp_path)
    publisher.publish("evaluation", "1.1.0", "second", 1, "tester")
    original = next(
        item for item in publisher.list_versions("evaluation") if item.version == "1.0.0"
    )
    first_dir = _version_dir(tmp_path, "1.0.0")
    second_dir = _version_dir(tmp_path, "1.1.0")
    before = {
        "1.0.0": _directory_bytes(first_dir),
        "1.1.0": _directory_bytes(second_dir),
    }

    summary = publisher.rollback("evaluation", "1.0.0", "synthetic rollback", "admin")

    assert summary.version == "1.0.0"
    assert summary.actor == "admin"
    assert summary.release_notes == "synthetic rollback"
    assert summary.active is True
    assert summary.counts == original.counts
    assert summary.content_digest == original.content_digest
    assert runtime.snapshot().info.version == "1.0.0"
    active = publisher.active_version("evaluation")
    assert active.version == "1.0.0"
    assert active.counts == original.counts
    assert active.content_digest == original.content_digest
    assert _directory_bytes(first_dir) == before["1.0.0"]
    assert _directory_bytes(second_dir) == before["1.1.0"]


def test_recover_loads_only_the_exact_active_pointer_target(tmp_path: Path) -> None:
    publisher, _ = _published_v1(tmp_path)
    recovered_runtime = OntologyRuntime()
    recovered = PackagePublisher(
        publisher._store,
        tmp_path / "management",
        recovered_runtime,
    )

    health = recovered.recover("evaluation")

    assert health.status == "ok"
    assert health.version == "1.0.0"
    assert recovered_runtime.snapshot().info.version == "1.0.0"


def test_recover_degrades_for_missing_exact_target_without_fallback(tmp_path: Path) -> None:
    publisher, _ = _published_v1(tmp_path)
    pointer_path = _active_pointer_path(tmp_path)
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["version"] = "9.9.9"
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    recovered_runtime = OntologyRuntime()
    recovered = PackagePublisher(
        publisher._store,
        tmp_path / "management",
        recovered_runtime,
    )

    health = recovered.recover("evaluation")

    assert health.status == "degraded"
    assert health.version == "9.9.9"
    with pytest.raises(PackageNotFoundError):
        recovered_runtime.snapshot()


@pytest.mark.parametrize("unsafe_version", ("../synthetic-version", "C:\\synthetic\\unsafe"))
def test_recover_does_not_expose_unsafe_pointer_version(
    tmp_path: Path, unsafe_version: str
) -> None:
    publisher, _ = _published_v1(tmp_path)
    pointer_path = _active_pointer_path(tmp_path)
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["version"] = unsafe_version
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    recovered_runtime = OntologyRuntime()
    recovered = PackagePublisher(
        publisher._store,
        tmp_path / "management",
        recovered_runtime,
    )

    health = recovered.recover("evaluation")

    assert health.status == "degraded"
    assert health.version is None
    with pytest.raises(PackageNotFoundError):
        recovered_runtime.snapshot()
    assert _version_dir(tmp_path, "1.0.0").is_dir()


def test_recover_degrades_for_malformed_pointer_without_exposing_version(tmp_path: Path) -> None:
    publisher, _ = _published_v1(tmp_path)
    _active_pointer_path(tmp_path).write_text('{"version":', encoding="utf-8")
    recovered_runtime = OntologyRuntime()
    recovered = PackagePublisher(
        publisher._store,
        tmp_path / "management",
        recovered_runtime,
    )

    health = recovered.recover("evaluation")

    assert health.status == "degraded"
    assert health.version is None
    with pytest.raises(PackageNotFoundError):
        recovered_runtime.snapshot()
