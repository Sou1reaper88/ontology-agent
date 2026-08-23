import json
from pathlib import Path

import pytest

from ontology_core.errors import OntologyParseError, PackageNotFoundError
from ontology_core.manifest import load_manifest, resolve_package_files
from ontology_core.models import PackageFileRole


def _write_manifest(package: Path, file_path: str) -> None:
    package.joinpath("manifest.yaml").write_text(
        'package_id: example.neutral\nversion: "1"\nfiles:\n'
        f"  core: {file_path}\n  domain: {file_path}\n"
        f"  mappings: {file_path}\n  rules: {file_path}\n"
        f"  shapes: {file_path}\n",
        encoding="utf-8",
    )


def test_load_manifest_and_resolve_all_roles(valid_package_dir: Path) -> None:
    manifest = load_manifest(valid_package_dir)
    files = resolve_package_files(valid_package_dir, manifest)
    assert manifest.package_id == "example.neutral"
    assert tuple(files) == tuple(PackageFileRole)
    assert all(path.is_file() for path in files.values())


def test_missing_manifest_raises_stable_error(tmp_path: Path) -> None:
    with pytest.raises(PackageNotFoundError) as caught:
        load_manifest(tmp_path)
    assert caught.value.code == "package_not_found"


def test_malformed_manifest_error_does_not_expose_source_or_path(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    secret = "fictional-secret-manifest"
    package.joinpath("manifest.yaml").write_text(
        f"package_id: [{secret}\n",
        encoding="utf-8",
    )

    with pytest.raises(OntologyParseError) as caught:
        load_manifest(package)

    serialized = json.dumps(caught.value.details, ensure_ascii=False)
    assert caught.value.details == {
        "error_type": "yaml_syntax_error",
        "role": "manifest",
        "line": 2,
        "column": 1,
    }
    assert secret not in serialized
    assert str(package.resolve()) not in serialized


def test_manifest_rejects_parent_path(tmp_path: Path) -> None:
    outside = tmp_path / "outside.ttl"
    outside.write_text("", encoding="utf-8")
    package = tmp_path / "package"
    package.mkdir()
    _write_manifest(package, "../outside.ttl")

    manifest = load_manifest(package)
    with pytest.raises(OntologyParseError) as caught:
        resolve_package_files(package, manifest)
    assert caught.value.details["role"] == "core"


def test_manifest_rejects_parent_segment_even_when_target_stays_inside(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    package.joinpath("core.ttl").write_text("", encoding="utf-8")
    _write_manifest(package, "nested/../core.ttl")

    manifest = load_manifest(package)
    with pytest.raises(OntologyParseError) as caught:
        resolve_package_files(package, manifest)
    assert caught.value.details["role"] == "core"


def test_manifest_rejects_absolute_path(tmp_path: Path) -> None:
    outside = tmp_path / "outside.ttl"
    outside.write_text("", encoding="utf-8")
    package = tmp_path / "package"
    package.mkdir()
    _write_manifest(package, outside.as_posix())

    manifest = load_manifest(package)
    with pytest.raises(OntologyParseError) as caught:
        resolve_package_files(package, manifest)
    assert caught.value.details["role"] == "core"


def test_manifest_rejects_absolute_path_even_when_target_is_inside(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    inside = package / "core.ttl"
    inside.write_text("", encoding="utf-8")
    _write_manifest(package, inside.as_posix())

    manifest = load_manifest(package)
    with pytest.raises(OntologyParseError) as caught:
        resolve_package_files(package, manifest)
    assert caught.value.details["role"] == "core"


def test_missing_package_file_raises_stable_error(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    _write_manifest(package, "missing.ttl")

    manifest = load_manifest(package)
    with pytest.raises(PackageNotFoundError) as caught:
        resolve_package_files(package, manifest)
    assert caught.value.details["role"] == "core"
