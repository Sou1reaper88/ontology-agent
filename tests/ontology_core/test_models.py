from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ontology_core.errors import PackageNotFoundError
from ontology_core.models import (
    OntologyViolation,
    PackageFileRole,
    PackageInfo,
    PackageManifest,
    ValidationReport,
)


def test_manifest_requires_all_package_roles() -> None:
    with pytest.raises(ValidationError):
        PackageManifest(
            package_id="example.neutral",
            version="1.0.0",
            files={PackageFileRole.CORE: "core.ttl"},
        )


def test_manifest_files_cannot_be_mutated_in_place() -> None:
    manifest = PackageManifest(
        package_id="example.neutral",
        version="1.0.0",
        files={role: f"{role.value}.ttl" for role in PackageFileRole},
    )

    with pytest.raises(TypeError):
        manifest.files[PackageFileRole.CORE] = "changed.ttl"

    assert manifest.files[PackageFileRole.CORE] == "core.ttl"


def test_manifest_json_round_trip_preserves_read_only_files() -> None:
    manifest = PackageManifest(
        package_id="example.neutral",
        version="1.0.0",
        files={role: f"{role.value}.ttl" for role in PackageFileRole},
    )

    restored = PackageManifest.model_validate(manifest.model_dump(mode="json"))

    assert restored == manifest
    with pytest.raises(TypeError):
        restored.files[PackageFileRole.CORE] = "changed.ttl"


def test_package_info_is_immutable() -> None:
    info = PackageInfo(
        package_id="example.neutral",
        version="1.0.0",
        sha256="a" * 64,
        loaded_at=datetime.now(UTC),
        source="C:/tmp/package",
    )
    with pytest.raises(ValidationError):
        info.version = "2.0.0"


def test_validation_report_uses_tuple_violations() -> None:
    violation = OntologyViolation(
        focus_node="https://example.invalid/Record",
        path="http://www.w3.org/2000/01/rdf-schema#label",
        message="Label is required",
        severity="http://www.w3.org/ns/shacl#Violation",
        source_shape="https://example.invalid/ClassShape",
    )
    report = ValidationReport(conforms=False, violations=(violation,))
    assert report.violations == (violation,)


def test_error_exposes_stable_code_and_details() -> None:
    exc = PackageNotFoundError("包不存在", details={"path": "missing"})
    assert exc.code == "package_not_found"
    assert exc.details == {"path": "missing"}
