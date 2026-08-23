from __future__ import annotations

import os
import stat
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import ontology_core.authoring as authoring
from ontology_core.authoring import initialize_package
from ontology_core.errors import OntologyParseError
from ontology_core.manifest import load_manifest
from ontology_core.models import PackageFileRole
from ontology_core.repository import OntologyRepository
from ontology_core.semantic_models import SemanticCatalog


def _staging_directories(parent: Path) -> tuple[Path, ...]:
    return tuple(path for path in parent.iterdir() if path.name.startswith(".package.staging"))


def _empty_backups(parent: Path) -> tuple[Path, ...]:
    return tuple(
        path for path in parent.iterdir() if path.name.startswith(".package.empty-backup-")
    )


def _make_directory_symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")


def _make_directory_junction_or_skip(link: Path, target: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows junctions are unavailable on this platform")
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0 or not link.is_junction():
        pytest.skip(f"directory junctions are unavailable: {result.stderr.strip()}")


def test_reparse_helper_recognizes_windows_file_attribute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "package"
    directory.mkdir()
    attributes = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
    monkeypatch.setattr(
        Path,
        "lstat",
        lambda _path: SimpleNamespace(st_file_attributes=attributes),
    )
    monkeypatch.setattr(Path, "is_symlink", lambda _path: False)
    monkeypatch.setattr(Path, "is_junction", lambda _path: False)

    detected = getattr(authoring, "_is_reparse_point", lambda _path: False)(directory)

    assert detected


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
    assert not _staging_directories(tmp_path)


@pytest.mark.parametrize(
    "base_uri",
    (
        "https://alice:fictional-secret@example.invalid/private/",
        "https://alice@example.invalid/private/",
        "https://:fictional-secret@example.invalid/private/",
        "https://example.invalid/private/?token=fictional-secret",
        "https://example.invalid/private/?",
    ),
)
def test_initialize_package_rejects_http_base_uri_credentials_and_query_without_writes(
    tmp_path: Path,
    base_uri: str,
) -> None:
    package_dir = tmp_path / "package"

    with pytest.raises(OntologyParseError) as caught:
        initialize_package(
            package_dir,
            package_id="neutral.package",
            base_uri=base_uri,
        )

    assert caught.value.details == {"field": "base_uri"}
    assert "fictional-secret" not in str(caught.value.details)
    assert not package_dir.exists()
    assert not _staging_directories(tmp_path)
    assert not _empty_backups(tmp_path)


def test_initialize_package_accepts_a_valid_http_base_uri(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"

    initialize_package(
        package_dir,
        package_id="neutral.package",
        base_uri="http://example.invalid/private/",
    )

    assert "<http://example.invalid/private/> a owl:Ontology ." in package_dir.joinpath(
        "domain.ttl"
    ).read_text(encoding="utf-8")


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
    assert not _staging_directories(tmp_path)


def test_initialize_package_rejects_existing_empty_symlink_without_staging(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    package_dir = tmp_path / "package"
    _make_directory_symlink_or_skip(package_dir, target)

    with pytest.raises(OntologyParseError):
        initialize_package(
            package_dir,
            package_id="neutral.package",
            base_uri="https://example.invalid/private/",
        )

    assert package_dir.is_symlink()
    assert tuple(target.iterdir()) == ()
    assert not _staging_directories(tmp_path)


def test_initialize_package_rejects_existing_empty_junction_without_staging(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    package_dir = tmp_path / "package"
    _make_directory_junction_or_skip(package_dir, target)

    with pytest.raises(OntologyParseError):
        initialize_package(
            package_dir,
            package_id="neutral.package",
            base_uri="https://example.invalid/private/",
        )

    assert package_dir.is_junction()
    assert tuple(target.iterdir()) == ()
    assert not _staging_directories(tmp_path)


def test_initialize_package_uses_unique_random_staging_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "package"
    observed: list[Path] = []
    original_write = authoring._write_exclusive

    def record_staging(path: Path, content: str, created) -> None:
        observed.append(path.parent)
        original_write(path, content, created)

    monkeypatch.setattr(authoring, "_write_exclusive", record_staging)

    initialize_package(
        package_dir,
        package_id="neutral.package",
        base_uri="https://example.invalid/private/",
    )

    assert len(set(observed)) == 1
    assert observed[0].parent == tmp_path
    assert observed[0].name.startswith(".package.staging-")
    assert observed[0].name != ".package.staging"
    assert not _staging_directories(tmp_path)


def test_failed_initialization_never_deletes_a_rebound_staging_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "package"
    rebound_staging: Path | None = None
    user_file: Path | None = None
    original_write = authoring._write_exclusive
    original_rename = Path.rename

    def fail_after_core(path: Path, content: str, created) -> None:
        nonlocal rebound_staging, user_file
        if path.name == "domain.ttl":
            moved_staging = tmp_path / "moved-staging"
            original_rename(path.parent, moved_staging)
            rebound_staging = path.parent
            rebound_staging.mkdir()
            user_file = rebound_staging / "user.txt"
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

    assert rebound_staging is not None
    assert user_file is not None
    assert user_file.read_text(encoding="utf-8") == "user-owned\n"
    assert not package_dir.joinpath("manifest.yaml").exists()


def test_commit_preserves_user_file_inserted_before_directory_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "package"
    user_file = package_dir / "user.txt"
    staging_paths: list[Path] = []
    original_rename = Path.rename
    inserted = False

    def competing_rename(path: Path, target: Path):
        nonlocal inserted
        if target == package_dir and not inserted:
            inserted = True
            staging_paths.append(path)
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
    assert staging_paths[0].joinpath("manifest.yaml").is_file()


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
    assert not _staging_directories(tmp_path)
    assert len(_empty_backups(tmp_path)) == int(create_target)


def test_existing_empty_target_is_captured_without_rmdir_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    original_rmdir = Path.rmdir
    called_rmdir = False

    def observe_rmdir(path: Path) -> None:
        nonlocal called_rmdir
        if path == package_dir:
            called_rmdir = True
        original_rmdir(path)

    monkeypatch.setattr(Path, "rmdir", observe_rmdir)

    manifest = initialize_package(
        package_dir,
        package_id="neutral.package",
        base_uri="https://example.invalid/private/",
    )

    assert not called_rmdir
    assert load_manifest(package_dir) == manifest


def test_capture_rejects_and_restores_junction_swapped_before_backup_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    junction_target = tmp_path / "junction-target"
    junction_target.mkdir()
    original_rename = Path.rename
    swapped = False

    def swap_before_capture(path: Path, target: Path):
        nonlocal swapped
        if path == package_dir and target.name.startswith(".package.empty-backup-") and not swapped:
            swapped = True
            original_rename(path, tmp_path / "moved-empty-target")
            _make_directory_junction_or_skip(path, junction_target)
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", swap_before_capture)

    with pytest.raises(OntologyParseError):
        initialize_package(
            package_dir,
            package_id="neutral.package",
            base_uri="https://example.invalid/private/",
        )

    assert swapped
    assert package_dir.is_junction()
    assert tuple(junction_target.iterdir()) == ()


def test_capture_rejects_and_restores_non_empty_target_inserted_before_backup_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    user_file = package_dir / "user.txt"
    original_rename = Path.rename
    inserted = False

    def insert_before_capture(path: Path, target: Path):
        nonlocal inserted
        if (
            path == package_dir
            and target.name.startswith(".package.empty-backup-")
            and not inserted
        ):
            inserted = True
            user_file.write_text("user-owned\n", encoding="utf-8", newline="\n")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", insert_before_capture)

    with pytest.raises(OntologyParseError):
        initialize_package(
            package_dir,
            package_id="neutral.package",
            base_uri="https://example.invalid/private/",
        )

    assert inserted
    assert user_file.read_text(encoding="utf-8") == "user-owned\n"
    assert not package_dir.joinpath("manifest.yaml").exists()
    assert not _empty_backups(tmp_path)


def test_existing_empty_target_keeps_empty_backup_outside_publishable_package(
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()

    manifest = initialize_package(
        package_dir,
        package_id="neutral.package",
        base_uri="https://example.invalid/private/",
    )

    backups = _empty_backups(tmp_path)
    assert len(backups) == 1
    assert backups[0].is_dir()
    assert not backups[0].is_junction()
    assert tuple(backups[0].iterdir()) == ()
    assert tuple(path.name for path in sorted(package_dir.iterdir())) == (
        "core.ttl",
        "domain.ttl",
        "manifest.yaml",
        "mappings.ttl",
        "rules.ttl",
        "shapes.ttl",
    )
    assert load_manifest(package_dir) == manifest
    OntologyRepository().publish(package_dir)


def test_quarantined_random_staging_does_not_block_retry_after_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "package"
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
    quarantined = _staging_directories(tmp_path)
    assert len(quarantined) == 1
    before = tuple(path.name for path in quarantined[0].iterdir())

    manifest = initialize_package(
        package_dir,
        package_id="neutral.package",
        base_uri="https://example.invalid/private/",
    )

    assert tuple(path.name for path in quarantined[0].iterdir()) == before
    assert load_manifest(package_dir) == manifest


def test_initialize_package_rejects_a_valid_staging_replacement_before_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "package"
    replacement_dir = tmp_path / "replacement"
    initialize_package(
        replacement_dir,
        package_id="replacement.package",
        base_uri="https://example.invalid/replacement/",
    )
    original_write = authoring._write_exclusive
    original_rename = Path.rename
    replaced = False

    def replace_staging_after_manifest(path: Path, content: str, created) -> None:
        nonlocal replaced
        original_write(path, content, created)
        if path.name == "manifest.yaml" and not replaced:
            replaced = True
            staging = path.parent
            original_rename(staging, tmp_path / "quarantined-original")
            original_rename(replacement_dir, staging)

    monkeypatch.setattr(authoring, "_write_exclusive", replace_staging_after_manifest)

    with pytest.raises(OntologyParseError):
        initialize_package(
            package_dir,
            package_id="neutral.package",
            base_uri="https://example.invalid/private/",
        )

    if package_dir.exists():
        assert load_manifest(package_dir).package_id == "replacement.package"
    assert replaced
    assert not replacement_dir.exists()


def test_initialize_package_rejects_same_content_junction_staging_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "package"
    replacement_dir = tmp_path / "replacement"
    initialize_package(
        replacement_dir,
        package_id="neutral.package",
        base_uri="https://example.invalid/private/",
    )
    original_write = authoring._write_exclusive
    original_rename = Path.rename
    replaced = False

    def replace_staging_after_manifest(path: Path, content: bytes, created) -> None:
        nonlocal replaced
        original_write(path, content, created)
        if path.name == "manifest.yaml" and not replaced:
            replaced = True
            original_rename(path.parent, tmp_path / "quarantined-original")
            _make_directory_junction_or_skip(path.parent, replacement_dir)

    monkeypatch.setattr(authoring, "_write_exclusive", replace_staging_after_manifest)

    with pytest.raises(OntologyParseError):
        initialize_package(
            package_dir,
            package_id="neutral.package",
            base_uri="https://example.invalid/private/",
        )

    assert replaced
    assert not package_dir.exists()


def test_initialize_package_rejects_a_valid_replacement_committed_after_precheck(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "package"
    replacement_dir = tmp_path / "replacement"
    initialize_package(
        replacement_dir,
        package_id="replacement.package",
        base_uri="https://example.invalid/replacement/",
    )
    original_rename = Path.rename
    replaced = False

    def replace_during_commit(path: Path, target: Path):
        nonlocal replaced
        if target == package_dir and not replaced:
            replaced = True
            original_rename(path, tmp_path / "quarantined-original")
            return original_rename(replacement_dir, target)
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", replace_during_commit)

    with pytest.raises(OntologyParseError):
        initialize_package(
            package_dir,
            package_id="neutral.package",
            base_uri="https://example.invalid/private/",
        )

    assert replaced
    assert load_manifest(package_dir).package_id == "replacement.package"
    assert not replacement_dir.exists()


def test_initialize_package_rejects_same_content_junction_final_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "package"
    replacement_dir = tmp_path / "replacement"
    initialize_package(
        replacement_dir,
        package_id="neutral.package",
        base_uri="https://example.invalid/private/",
    )
    original_rename = Path.rename
    replaced = False

    def replace_during_commit(path: Path, target: Path):
        nonlocal replaced
        if target == package_dir and not replaced:
            replaced = True
            original_rename(path, tmp_path / "quarantined-original")
            _make_directory_junction_or_skip(target, replacement_dir)
            return target
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", replace_during_commit)

    with pytest.raises(OntologyParseError):
        initialize_package(
            package_dir,
            package_id="neutral.package",
            base_uri="https://example.invalid/private/",
        )

    assert replaced
    assert package_dir.is_junction()
    assert load_manifest(package_dir).package_id == "neutral.package"


def test_initialize_package_rejects_post_rename_byte_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "package"
    original_rename = Path.rename
    tampered = False

    def tamper_after_rename(path: Path, target: Path):
        nonlocal tampered
        result = original_rename(path, target)
        if target == package_dir and not tampered:
            tampered = True
            target.joinpath("domain.ttl").write_bytes(b"tampered\n")
        return result

    monkeypatch.setattr(Path, "rename", tamper_after_rename)

    with pytest.raises(OntologyParseError):
        initialize_package(
            package_dir,
            package_id="neutral.package",
            base_uri="https://example.invalid/private/",
        )

    assert package_dir.joinpath("domain.ttl").read_bytes() == b"tampered\n"


def test_initialize_package_rechecks_final_root_after_loading_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "package"
    replacement_dir = tmp_path / "replacement"
    initialize_package(
        replacement_dir,
        package_id="neutral.package",
        base_uri="https://example.invalid/private/",
    )
    original_load_manifest = authoring.load_manifest
    original_rename = Path.rename
    replaced = False

    def replace_after_loading_manifest(path: Path):
        nonlocal replaced
        manifest = original_load_manifest(path)
        if path == package_dir and not replaced:
            replaced = True
            original_rename(package_dir, tmp_path / "quarantined-final")
            _make_directory_junction_or_skip(package_dir, replacement_dir)
        return manifest

    monkeypatch.setattr(authoring, "load_manifest", replace_after_loading_manifest)

    with pytest.raises(OntologyParseError):
        initialize_package(
            package_dir,
            package_id="neutral.package",
            base_uri="https://example.invalid/private/",
        )

    assert replaced
    assert package_dir.is_junction()


def test_concurrent_initializers_allow_only_one_success_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "package"
    commit_barrier = threading.Barrier(2)
    start_barrier = threading.Barrier(2)
    result_lock = threading.Lock()
    original_commit = authoring._commit_staging
    commit_stagings: list[Path] = []

    def synchronized_commit(staging: Path, root: Path, captured_target: Path | None) -> None:
        with result_lock:
            commit_stagings.append(staging)
        commit_barrier.wait(timeout=5)
        original_commit(staging, root, captured_target)

    monkeypatch.setattr(authoring, "_commit_staging", synchronized_commit)
    outcomes: list[Exception | None] = []

    def initialize() -> None:
        try:
            start_barrier.wait(timeout=5)
            initialize_package(
                package_dir,
                package_id="neutral.package",
                base_uri="https://example.invalid/private/",
            )
        except Exception as exc:  # The contract is one successful exclusive initializer.
            outcome: Exception | None = exc
        else:
            outcome = None
        with result_lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=initialize) for _ in range(2)]
    for thread in threads:
        thread.start()
    try:
        for thread in threads:
            thread.join(timeout=10)
    finally:
        start_barrier.abort()
        commit_barrier.abort()
        for thread in threads:
            thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert len(commit_stagings) == 2
    assert len(set(commit_stagings)) == 2
    assert all(staging.parent == tmp_path for staging in commit_stagings)
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
