from __future__ import annotations

import json
import re
import secrets
import stat
import tempfile
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from ontology_core.errors import OntologyParseError
from ontology_core.manifest import load_manifest
from ontology_core.models import PackageFileRole, PackageManifest

_RESOURCE_PACKAGE = "ontology_core.resources"
_STAGING_SUFFIX = ".staging"
_URN_NID_AND_NSS = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{1,31}:.+")
_MODULE_PREFIXES = """@prefix oa: <urn:ontology-agent:core#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
"""
_PACKAGE_FILES = {
    PackageFileRole.CORE: "core.ttl",
    PackageFileRole.DOMAIN: "domain.ttl",
    PackageFileRole.MAPPINGS: "mappings.ttl",
    PackageFileRole.RULES: "rules.ttl",
    PackageFileRole.SHAPES: "shapes.ttl",
}


def _require_text(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OntologyParseError("本体包初始化参数无效", details={"field": field})
    return value


def _invalid_base_uri() -> OntologyParseError:
    return OntologyParseError("本体包初始化参数无效", details={"field": "base_uri"})


def _validate_base_uri(base_uri: str) -> str:
    value = _require_text(base_uri, field="base_uri")
    query_is_present = "?" in value.partition("#")[0]
    if any(
        character.isspace() or ord(character) < 0x20 or character in '<>"{}' for character in value
    ):
        raise _invalid_base_uri()
    try:
        parts = urlsplit(value)
        hostname = parts.hostname
        _ = parts.port
    except ValueError as exc:
        raise _invalid_base_uri() from exc
    if parts.scheme in {"http", "https"}:
        if (
            parts.netloc
            and hostname
            and parts.username is None
            and parts.password is None
            and not query_is_present
        ):
            return value
        raise _invalid_base_uri()
    if parts.scheme == "urn" and _URN_NID_AND_NSS.fullmatch(parts.path):
        return value
    raise _invalid_base_uri()


def _module_content(base_uri: str) -> str:
    return f"{_MODULE_PREFIXES}\n<{base_uri}> a owl:Ontology .\n"


def _manifest_content(manifest: PackageManifest) -> str:
    lines = [
        f"package_id: {json.dumps(manifest.package_id)}",
        f"version: {json.dumps(manifest.version)}",
        "files:",
    ]
    lines.extend(f"  {role.value}: {manifest.files[role]}" for role in PackageFileRole)
    return "\n".join(lines) + "\n"


def _utf8_lf_bytes(content: str) -> bytes:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"
    return normalized.encode("utf-8")


def _write_exclusive(path: Path, content: bytes, created: list[Path]) -> None:
    with path.open("xb") as output:
        created.append(path)
        output.write(content)


def _initialization_error(path: Path, error: OSError) -> OntologyParseError:
    return OntologyParseError(
        "本体包初始化失败",
        details={"path": str(path), "reason": str(error)},
    )


def _is_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise _initialization_error(path, exc) from exc
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if is_junction is not None and is_junction():
            return True
    except OSError as exc:
        raise _initialization_error(path, exc) from exc
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
    return bool(attributes & reparse_attribute)


def _require_real_directory(path: Path, *, allow_absent: bool) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if allow_absent:
            return False
        raise _integrity_error(path) from None
    except OSError as exc:
        raise _initialization_error(path, exc) from exc
    if _is_reparse_point(path) or not stat.S_ISDIR(metadata.st_mode):
        raise OntologyParseError("本体包目录不能是链接或重解析点", details={"path": str(path)})
    return True


def _staging_directory(root: Path) -> Path:
    try:
        return Path(tempfile.mkdtemp(prefix=f".{root.name}{_STAGING_SUFFIX}-", dir=root.parent))
    except OSError as exc:
        raise _initialization_error(root.parent, exc) from exc


def _target_is_empty_directory(root: Path) -> bool:
    return root.is_dir() and not any(root.iterdir())


def _empty_backup_path(root: Path) -> Path:
    return root.parent / f".{root.name}.empty-backup-{secrets.token_hex(16)}"


def _restore_captured_target(backup: Path, root: Path) -> None:
    try:
        root.lstat()
    except FileNotFoundError:
        try:
            backup.rename(root)
        except OSError:
            return
    except OSError:
        return


def _capture_empty_target(root: Path) -> Path | None:
    if not _require_real_directory(root, allow_absent=True):
        return None
    backup = _empty_backup_path(root)
    try:
        root.rename(backup)
    except OSError as exc:
        raise _initialization_error(root, exc) from exc
    try:
        _require_real_directory(backup, allow_absent=False)
        if not _target_is_empty_directory(backup):
            raise OntologyParseError("本体包目录必须不存在或为空", details={"path": str(root)})
    except OntologyParseError:
        _restore_captured_target(backup, root)
        raise
    return backup


def _commit_staging(staging: Path, root: Path, captured_target: Path | None) -> None:
    if _require_real_directory(root, allow_absent=True):
        raise OntologyParseError("本体包目录必须不存在或为空", details={"path": str(root)})
    _require_real_directory(staging, allow_absent=False)
    try:
        staging.rename(root)
    except OSError as exc:
        if captured_target is not None:
            _restore_captured_target(captured_target, root)
        raise _initialization_error(root, exc) from exc


def _integrity_error(path: Path) -> OntologyParseError:
    return OntologyParseError("本体包初始化完整性校验失败", details={"path": str(path)})


def _verify_package_contents(directory: Path, expected_files: dict[str, bytes]) -> None:
    _require_real_directory(directory, allow_absent=False)
    try:
        entries = {path.name: path for path in directory.iterdir()}
    except OSError as exc:
        raise _initialization_error(directory, exc) from exc
    if set(entries) != set(expected_files):
        raise _integrity_error(directory)
    for name, expected in expected_files.items():
        path = entries[name]
        if not path.is_file() or path.is_symlink():
            raise _integrity_error(path)
        try:
            actual = path.read_bytes()
        except OSError as exc:
            raise _initialization_error(path, exc) from exc
        if actual != expected:
            raise _integrity_error(path)


def _expected_package_files(base_uri: str, manifest: PackageManifest) -> dict[str, bytes]:
    resources = files(_RESOURCE_PACKAGE)
    return {
        _PACKAGE_FILES[PackageFileRole.CORE]: _utf8_lf_bytes(
            resources.joinpath("core.ttl").read_text(encoding="utf-8")
        ),
        _PACKAGE_FILES[PackageFileRole.DOMAIN]: _utf8_lf_bytes(_module_content(base_uri)),
        _PACKAGE_FILES[PackageFileRole.MAPPINGS]: _utf8_lf_bytes(_module_content(base_uri)),
        _PACKAGE_FILES[PackageFileRole.RULES]: _utf8_lf_bytes(_module_content(base_uri)),
        _PACKAGE_FILES[PackageFileRole.SHAPES]: _utf8_lf_bytes(
            resources.joinpath("shapes.ttl").read_text(encoding="utf-8")
        ),
        "manifest.yaml": _utf8_lf_bytes(_manifest_content(manifest)),
    }


def initialize_package(
    package_dir: str | Path,
    *,
    package_id: str,
    base_uri: str,
    version: str = "0.1.0",
) -> PackageManifest:
    """Create a blank external RDF ontology package without automatic failure cleanup."""
    package_id = _require_text(package_id, field="package_id")
    version = _require_text(version, field="version")
    base_uri = _validate_base_uri(base_uri)
    root = Path(package_dir)
    try:
        root.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise _initialization_error(root.parent, exc) from exc
    target_was_empty = _require_real_directory(root, allow_absent=True)
    if target_was_empty and not _target_is_empty_directory(root):
        raise OntologyParseError("本体包目录必须不存在或为空", details={"path": str(root)})

    staging = _staging_directory(root)
    _require_real_directory(staging, allow_absent=False)
    created: list[Path] = []
    manifest = PackageManifest(package_id=package_id, version=version, files=_PACKAGE_FILES)
    expected_files = _expected_package_files(base_uri, manifest)
    try:
        _write_exclusive(
            staging / _PACKAGE_FILES[PackageFileRole.CORE],
            expected_files[_PACKAGE_FILES[PackageFileRole.CORE]],
            created,
        )
        for role in (PackageFileRole.DOMAIN, PackageFileRole.MAPPINGS, PackageFileRole.RULES):
            _write_exclusive(
                staging / _PACKAGE_FILES[role],
                expected_files[_PACKAGE_FILES[role]],
                created,
            )
        _write_exclusive(
            staging / _PACKAGE_FILES[PackageFileRole.SHAPES],
            expected_files[_PACKAGE_FILES[PackageFileRole.SHAPES]],
            created,
        )
        _write_exclusive(staging / "manifest.yaml", expected_files["manifest.yaml"], created)
        _verify_package_contents(staging, expected_files)
        captured_target = _capture_empty_target(root) if target_was_empty else None
        _commit_staging(staging, root, captured_target)
        _verify_package_contents(root, expected_files)
        loaded_manifest = load_manifest(root)
        _verify_package_contents(root, expected_files)
        if loaded_manifest != manifest:
            raise _integrity_error(root)
    except OSError as exc:
        raise _initialization_error(root, exc) from exc
    return manifest
