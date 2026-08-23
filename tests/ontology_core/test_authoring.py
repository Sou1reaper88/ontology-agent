from __future__ import annotations

from pathlib import Path

import pytest

from ontology_core.authoring import initialize_package
from ontology_core.errors import OntologyParseError
from ontology_core.models import PackageFileRole
from ontology_core.repository import OntologyRepository
from ontology_core.semantic_models import SemanticCatalog


def test_initialize_package_creates_stable_blank_publishable_package(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"

    manifest = initialize_package(
        package_dir,
        package_id="neutral.package",
        base_uri="https://example.invalid/private/",
    )

    assert tuple(path.name for path in sorted(package_dir.iterdir())) == (
        "core.ttl",
        "domain.ttl",
        "manifest.yaml",
        "mappings.ttl",
        "rules.ttl",
        "shapes.ttl",
    )
    assert manifest.package_id == "neutral.package"
    assert manifest.version == "0.1.0"
    assert tuple(manifest.files) == tuple(PackageFileRole)
    assert manifest.model_dump(mode="json") == {
        "package_id": "neutral.package",
        "version": "0.1.0",
        "files": {
            "core": "core.ttl",
            "domain": "domain.ttl",
            "mappings": "mappings.ttl",
            "rules": "rules.ttl",
            "shapes": "shapes.ttl",
        },
    }
    assert package_dir.joinpath("manifest.yaml").read_text(encoding="utf-8") == (
        "package_id: neutral.package\n"
        "version: 0.1.0\n"
        "files:\n"
        "  core: core.ttl\n"
        "  domain: domain.ttl\n"
        "  mappings: mappings.ttl\n"
        "  rules: rules.ttl\n"
        "  shapes: shapes.ttl\n"
    )

    repository = OntologyRepository()
    repository.publish(package_dir)
    assert repository.current().catalog == SemanticCatalog()


@pytest.mark.parametrize(
    ("package_id", "base_uri", "version"),
    [
        ("", "https://example.invalid/private/", "0.1.0"),
        ("neutral.package", "not-a-uri", "0.1.0"),
        ("neutral.package", "file:///private", "0.1.0"),
        ("neutral.package", "https:///private", "0.1.0"),
        ("neutral.package", "https://example.invalid/private/", ""),
    ],
)
def test_initialize_package_rejects_invalid_identifiers(
    tmp_path: Path,
    package_id: str,
    base_uri: str,
    version: str,
) -> None:
    package_dir = tmp_path / "package"

    with pytest.raises(OntologyParseError) as caught:
        initialize_package(
            package_dir,
            package_id=package_id,
            base_uri=base_uri,
            version=version,
        )

    assert caught.value.code == "ontology_parse_error"
    assert not package_dir.exists()


def test_initialize_package_refuses_non_empty_directory_without_modification(
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    sentinel = package_dir / "keep.txt"
    sentinel.write_text("keep\n", encoding="utf-8", newline="\n")
    before = sentinel.read_bytes()

    with pytest.raises(OntologyParseError) as caught:
        initialize_package(
            package_dir,
            package_id="neutral.package",
            base_uri="urn:example:private",
        )

    assert caught.value.code == "ontology_parse_error"
    assert tuple(path.name for path in package_dir.iterdir()) == ("keep.txt",)
    assert sentinel.read_bytes() == before


def test_generated_package_contains_only_generic_vocabulary_and_blank_modules(
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "package"
    initialize_package(
        package_dir,
        package_id="neutral.package",
        base_uri="https://example.invalid/private/",
    )

    generated = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(package_dir.iterdir())
    )

    assert "Record" not in generated
    assert "Example" not in generated
    assert "ConcreteTable" not in generated
    assert "password" not in generated.casefold()
    assert "token" not in generated.casefold()
    assert "ex:Instance" not in generated
    for path in package_dir.iterdir():
        content = path.read_bytes()
        assert b"\r\n" not in content
        assert content.endswith(b"\n")
