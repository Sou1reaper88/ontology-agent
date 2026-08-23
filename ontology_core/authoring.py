from __future__ import annotations

import json
import re
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from ontology_core.errors import OntologyParseError
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


def _write_exclusive(path: Path, content: str, created: list[Path]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as output:
        created.append(path)
        output.write(content.replace("\r\n", "\n"))


def _initialization_error(path: Path, error: OSError) -> OntologyParseError:
    return OntologyParseError(
        "本体包初始化失败",
        details={"path": str(path), "reason": str(error)},
    )


def _staging_path(root: Path) -> Path:
    return root.parent / f".{root.name}{_STAGING_SUFFIX}"


def _target_is_empty_directory(root: Path) -> bool:
    return root.is_dir() and not any(root.iterdir())


def _create_staging(staging: Path) -> None:
    try:
        staging.mkdir()
    except FileExistsError as exc:
        raise OntologyParseError(
            "发现未清理的本体包初始化隔离目录", details={"path": str(staging)}
        ) from exc
    except OSError as exc:
        raise _initialization_error(staging, exc) from exc


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

    staging = _staging_path(root)
    _create_staging(staging)
    created: list[Path] = []
    manifest = PackageManifest(package_id=package_id, version=version, files=_PACKAGE_FILES)
    resources = files(_RESOURCE_PACKAGE)
    try:
        _write_exclusive(
            staging / _PACKAGE_FILES[PackageFileRole.CORE],
            resources.joinpath("core.ttl").read_text(encoding="utf-8"),
            created,
        )
        for role in (PackageFileRole.DOMAIN, PackageFileRole.MAPPINGS, PackageFileRole.RULES):
            _write_exclusive(staging / _PACKAGE_FILES[role], _module_content(base_uri), created)
        _write_exclusive(
            staging / _PACKAGE_FILES[PackageFileRole.SHAPES],
            resources.joinpath("shapes.ttl").read_text(encoding="utf-8"),
            created,
        )
        _write_exclusive(staging / "manifest.yaml", _manifest_content(manifest), created)
        _prepare_empty_target_for_commit(root)
        _commit_staging(staging, root)
    except OSError as exc:
        raise _initialization_error(root, exc) from exc
    return manifest
