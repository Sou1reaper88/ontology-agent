from __future__ import annotations

import threading
from pathlib import Path

import pytest

from ontology_core.authoring import initialize_package
from ontology_core.errors import OntologyParseError
from ontology_core.manifest import load_manifest
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
        'package_id: "neutral.package"\n'
        'version: "0.1.0"\n'
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
    ("package_id", "version"),
    [
        ("name: colon", "0.1.0"),
        ('name "quoted"', 'version "quoted"'),
        ("name\nnext", "0.1.0"),
        ("neutral.package", "version\nnext"),
        ("name\rafter", "0.1.0"),
        ("neutral.package", "version\rafter"),
    ],
)
def test_initialize_package_serializes_manifest_identifiers_without_yaml_injection(
    tmp_path: Path,
    package_id: str,
    version: str,
) -> None:
    package_dir = tmp_path / "package"

    manifest = initialize_package(
        package_dir,
        package_id=package_id,
        base_uri="https://example.invalid/private/",
        version=version,
    )
    manifest_bytes = package_dir.joinpath("manifest.yaml").read_bytes()

    assert manifest.package_id == package_id
    assert manifest.version == version
    assert load_manifest(package_dir) == manifest
    assert b"\r" not in manifest_bytes
    assert manifest_bytes.endswith(b"\n")


@pytest.mark.parametrize(
    ("package_id", "base_uri", "version"),
    [
        ("", "https://example.invalid/private/", "0.1.0"),
        ("neutral.package", "not-a-uri", "0.1.0"),
        ("neutral.package", "file:///private", "0.1.0"),
        ("neutral.package", "https:///private", "0.1.0"),
        ("neutral.package", "https://[broken", "0.1.0"),
        ("neutral.package", "https://", "0.1.0"),
        ("neutral.package", "urn:missing-nss-separator", "0.1.0"),
        ("neutral.package", "https://example.invalid/private/\n<injected>", "0.1.0"),
        ("neutral.package", "urn:example:unsafe{value}", "0.1.0"),
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


def test_initialize_package_accepts_a_valid_urn_base_uri(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"

    initialize_package(
        package_dir,
        package_id="neutral.package",
        base_uri="urn:example:private",
    )

    assert "<urn:example:private> a owl:Ontology ." in package_dir.joinpath("domain.ttl").read_text(
        encoding="utf-8"
    )


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


def test_initialize_package_preserves_a_file_inserted_after_empty_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "package"
    core_path = package_dir / "core.ttl"
    user_bytes = b"user-owned\n"
    original_open = Path.open
    inserted = False

    def interleaving_open(path: Path, mode: str = "r", *args, **kwargs):
        nonlocal inserted
        if path == core_path and mode == "x" and not inserted:
            inserted = True
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(user_bytes)
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", interleaving_open)

    with pytest.raises(OntologyParseError):
        initialize_package(
            package_dir,
            package_id="neutral.package",
            base_uri="https://example.invalid/private/",
        )

    assert core_path.read_bytes() == user_bytes
    assert not package_dir.joinpath("manifest.yaml").exists()
    assert not package_dir.joinpath("domain.ttl").exists()
    assert not package_dir.joinpath("mappings.ttl").exists()
    assert not package_dir.joinpath("rules.ttl").exists()
    assert not package_dir.joinpath("shapes.ttl").exists()
    assert not package_dir.joinpath(".ontology-agent-init.lock").exists()


def test_concurrent_initializers_allow_only_one_success_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "package"
    core_path = package_dir / "core.ttl"
    write_barrier = threading.Barrier(2)
    start_barrier = threading.Barrier(2)
    original_write_text = Path.write_text

    def synchronized_write_text(path: Path, data: str, *args, **kwargs) -> int:
        if path == core_path:
            write_barrier.wait(timeout=5)
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", synchronized_write_text)
    outcomes: list[Exception | None] = []

    def initialize() -> None:
        start_barrier.wait(timeout=5)
        try:
            initialize_package(
                package_dir,
                package_id="neutral.package",
                base_uri="https://example.invalid/private/",
            )
        except Exception as exc:  # The contract is one successful exclusive initializer.
            outcomes.append(exc)
        else:
            outcomes.append(None)

    first = threading.Thread(target=initialize)
    second = threading.Thread(target=initialize)
    first.start()
    second.start()
    first.join(timeout=10)
    second.join(timeout=10)

    assert not first.is_alive()
    assert not second.is_alive()
    assert outcomes.count(None) == 1
    assert len(outcomes) == 2
    assert all(error is None or isinstance(error, OntologyParseError) for error in outcomes)
    assert not package_dir.joinpath(".ontology-agent-init.lock").exists()
    assert load_manifest(package_dir).package_id == "neutral.package"


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
