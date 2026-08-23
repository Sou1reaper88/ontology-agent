from __future__ import annotations

import json
import re
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
        if parts.netloc and hostname:
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


def _staging_directory(root: Path) -> Path:
    try:
        return Path(tempfile.mkdtemp(prefix=f".{root.name}{_STAGING_SUFFIX}-", dir=root.parent))
    except OSError as exc:
        raise _initialization_error(root.parent, exc) from exc


def _target_is_empty_directory(root: Path) -> bool:
    return root.is_dir() and not any(root.iterdir())


def _prepare_empty_target_for_commit(root: Path) -> None:
    if not root.exists():
        return
    if not _target_is_empty_directory(root):
        raise OntologyParseError("本体包目录必须不存在或为空", details={"path": str(root)})
    try:
        root.rmdir()
    except OSError as exc:
        raise _initialization_error(root, exc) from exc


def _restore_empty_target(root: Path) -> None:
    if root.exists():
        return
    try:
        root.mkdir()
    except OSError:
        return


def _commit_staging(staging: Path, root: Path) -> None:
    if root.exists():
        raise OntologyParseError("本体包目录必须不存在或为空", details={"path": str(root)})
    try:
        staging.rename(root)
    except OSError as exc:
        _restore_empty_target(root)
        raise _initialization_error(root, exc) from exc


def _integrity_error(path: Path) -> OntologyParseError:
    return OntologyParseError("本体包初始化完整性校验失败", details={"path": str(path)})


def _verify_package_contents(directory: Path, expected_files: dict[str, bytes]) -> None:
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
    if root.exists() and not _target_is_empty_directory(root):
        raise OntologyParseError("本体包目录必须不存在或为空", details={"path": str(root)})

    staging = _staging_directory(root)
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
        _prepare_empty_target_for_commit(root)
        _commit_staging(staging, root)
        _verify_package_contents(root, expected_files)
        if load_manifest(root) != manifest:
            raise _integrity_error(root)
    except OSError as exc:
        raise _initialization_error(root, exc) from exc
    return manifest
