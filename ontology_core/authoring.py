from __future__ import annotations

import json
import os
import re
from contextlib import suppress
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from ontology_core.errors import OntologyParseError
from ontology_core.models import PackageFileRole, PackageManifest

_RESOURCE_PACKAGE = "ontology_core.resources"
_LOCK_NAME = ".ontology-agent-init.lock"
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


@dataclass(frozen=True)
class _CreatedPath:
    path: Path
    device: int
    inode: int


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
        f"package_id: {json.dumps(manifest.package_id, ensure_ascii=False)}",
        f"version: {json.dumps(manifest.version, ensure_ascii=False)}",
        "files:",
    ]
    lines.extend(f"  {role.value}: {manifest.files[role]}" for role in PackageFileRole)
    return "\n".join(lines) + "\n"


def _created_path(path: Path, file_descriptor: int) -> _CreatedPath:
    status = os.fstat(file_descriptor)
    return _CreatedPath(path=path, device=status.st_dev, inode=status.st_ino)


def _write_exclusive(path: Path, content: str, created: list[_CreatedPath]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as output:
        created.append(_created_path(path, output.fileno()))
        output.write(content.replace("\r\n", "\n"))


def _remove_if_owned(created: _CreatedPath) -> None:
    try:
        status = created.path.stat()
    except FileNotFoundError:
        return
    if (status.st_dev, status.st_ino) == (created.device, created.inode):
        try:
            created.path.unlink()
        except FileNotFoundError:
            return


def _directory_is_empty(root: Path, *, lock_path: Path | None = None) -> bool:
    return not any(path != lock_path for path in root.iterdir())


def _create_target_directory(root: Path) -> bool:
    try:
        root.mkdir(parents=True, exist_ok=False)
        return True
    except FileExistsError as exc:
        if not root.is_dir() or not _directory_is_empty(root):
            raise OntologyParseError(
                "本体包目录必须不存在或为空", details={"path": str(root)}
            ) from exc
        return False


def _initialization_error(path: Path, error: OSError) -> OntologyParseError:
    return OntologyParseError(
        "本体包初始化失败",
        details={"path": str(path), "reason": str(error)},
    )


def initialize_package(
    package_dir: str | Path,
    *,
    package_id: str,
    base_uri: str,
    version: str = "0.1.0",
) -> PackageManifest:
    """Create a blank external RDF ontology package without domain instances."""
    package_id = _require_text(package_id, field="package_id")
    version = _require_text(version, field="version")
    base_uri = _validate_base_uri(base_uri)
    root = Path(package_dir)
    created_root = _create_target_directory(root)
    lock_path = root / _LOCK_NAME
    created_files: list[_CreatedPath] = []
    lock: _CreatedPath | None = None
    completed = False
    try:
        _write_exclusive(lock_path, "initializing\n", created_files)
        lock = created_files.pop()
        if not _directory_is_empty(root, lock_path=lock_path):
            raise OntologyParseError("本体包目录必须不存在或为空", details={"path": str(root)})

        manifest = PackageManifest(package_id=package_id, version=version, files=_PACKAGE_FILES)
        resources = files(_RESOURCE_PACKAGE)
        _write_exclusive(
            root / _PACKAGE_FILES[PackageFileRole.CORE],
            resources.joinpath("core.ttl").read_text(encoding="utf-8"),
            created_files,
        )
        for role in (PackageFileRole.DOMAIN, PackageFileRole.MAPPINGS, PackageFileRole.RULES):
            _write_exclusive(root / _PACKAGE_FILES[role], _module_content(base_uri), created_files)
        _write_exclusive(
            root / _PACKAGE_FILES[PackageFileRole.SHAPES],
            resources.joinpath("shapes.ttl").read_text(encoding="utf-8"),
            created_files,
        )
        _write_exclusive(root / "manifest.yaml", _manifest_content(manifest), created_files)
        completed = True
        return manifest
    except OSError as exc:
        raise _initialization_error(root, exc) from exc
    finally:
        if not completed:
            for created in reversed(created_files):
                _remove_if_owned(created)
        if lock is not None:
            _remove_if_owned(lock)
        if not completed and created_root:
            with suppress(OSError):
                root.rmdir()
