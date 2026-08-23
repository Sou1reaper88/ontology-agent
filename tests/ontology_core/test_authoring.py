from __future__ import annotations

import threading
from pathlib import Path

import pytest

import ontology_core.authoring as authoring
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
        ("name\u0085next", "0.1.0"),
        ("neutral.package", "version\u0085next"),
        ("name\u2028next", "0.1.0"),
        ("neutral.package", "version\u2029next"),
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
    info = OntologyRepository().publish(package_dir)
    assert (info.package_id, info.version) == (package_id, version)
    assert b"\r" not in manifest_bytes
    assert manifest_bytes.endswith(b"\n")
    assert b"\xc2\x85" not in manifest_bytes
    assert b"\xe2\x80\xa8" not in manifest_bytes
    assert b"\xe2\x80\xa9" not in manifest_bytes


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
    assert not tmp_path.joinpath(".package.staging").exists()


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
    assert not tmp_path.joinpath(".package.staging").exists()


def test_failed_initialization_never_deletes_a_rebound_staging_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "package"
    staging_dir = tmp_path / ".package.staging"
    user_file = staging_dir / "user.txt"
    original_write = authoring._write_exclusive
    original_rename = Path.rename

    def fail_after_core(path: Path, content: str, created) -> None:
        if path.name == "domain.ttl":
            moved_staging = tmp_path / "moved-staging"
            original_rename(path.parent, moved_staging)
            staging_dir.mkdir()
            user_file.write_text("user-owned\n", encoding="utf-8", newline="\n")
            raise OSError("simulated staged write failure")
        original_write(path, content, created)

    monkeypatch.setattr(authoring, "_write_exclusive", fail_after_core)

    with pytest.raises(OntologyParseError):
        initialize_package(
            package_dir,
            package_id="neutral.package",
            base_uri="https://example.invalid/private/",
        )

    assert user_file.read_text(encoding="utf-8") == "user-owned\n"
    assert not package_dir.joinpath("manifest.yaml").exists()


def test_commit_preserves_user_file_inserted_before_directory_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "package"
    user_file = package_dir / "user.txt"
    staging_dir = tmp_path / ".package.staging"
    original_rename = Path.rename
    inserted = False

    def competing_rename(path: Path, target: Path):
        nonlocal inserted
        if target == package_dir and not inserted:
            inserted = True
            package_dir.mkdir()
            user_file.write_text("user-owned\n", encoding="utf-8", newline="\n")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", competing_rename)

    with pytest.raises(OntologyParseError):
        initialize_package(
            package_dir,
            package_id="neutral.package",
            base_uri="https://example.invalid/private/",
        )

    assert user_file.read_text(encoding="utf-8") == "user-owned\n"
    assert not package_dir.joinpath("manifest.yaml").exists()
    assert staging_dir.joinpath("manifest.yaml").is_file()


@pytest.mark.parametrize("create_target", [False, True])
def test_initialize_package_commits_from_staging_for_absent_or_empty_targets(
    tmp_path: Path,
    create_target: bool,
) -> None:
    package_dir = tmp_path / "package"
    if create_target:
        package_dir.mkdir()

    initialize_package(
        package_dir,
        package_id="neutral.package",
        base_uri="https://example.invalid/private/",
    )

    assert load_manifest(package_dir).package_id == "neutral.package"
    assert not tmp_path.joinpath(".package.staging").exists()


def test_stale_staging_blocks_automatic_retry_after_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "package"
    staging_dir = tmp_path / ".package.staging"
    original_write = authoring._write_exclusive
    failed = False

    def fail_once(path: Path, content: str, created) -> None:
        nonlocal failed
        if path.name == "domain.ttl" and not failed:
            failed = True
            raise OSError("simulated staged write failure")
        original_write(path, content, created)

    monkeypatch.setattr(authoring, "_write_exclusive", fail_once)

    with pytest.raises(OntologyParseError):
        initialize_package(
            package_dir,
            package_id="neutral.package",
            base_uri="https://example.invalid/private/",
        )
    before = tuple(path.name for path in staging_dir.iterdir())

    with pytest.raises(OntologyParseError):
        initialize_package(
            package_dir,
            package_id="neutral.package",
            base_uri="https://example.invalid/private/",
        )

    assert tuple(path.name for path in staging_dir.iterdir()) == before
    assert not package_dir.joinpath("manifest.yaml").exists()


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
