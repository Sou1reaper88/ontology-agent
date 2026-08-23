from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from ontology_core.errors import OntologyParseError
from ontology_core.models import PackageFileRole, PackageManifest

_RESOURCE_PACKAGE = "ontology_core.resources"
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


def _validate_base_uri(base_uri: str) -> str:
    value = _require_text(base_uri, field="base_uri")
    parts = urlsplit(value)
    valid = (parts.scheme in {"http", "https"} and bool(parts.netloc)) or (
        parts.scheme == "urn" and bool(parts.path)
    )
    if not valid or any(character.isspace() or character in '<>"' for character in value):
        raise OntologyParseError("本体包初始化参数无效", details={"field": "base_uri"})
    return value


def _module_content(base_uri: str) -> str:
    return f"{_MODULE_PREFIXES}\n<{base_uri}> a owl:Ontology .\n"


def _manifest_content(manifest: PackageManifest) -> str:
    lines = [f"package_id: {manifest.package_id}", f"version: {manifest.version}", "files:"]
    lines.extend(f"  {role.value}: {manifest.files[role]}" for role in PackageFileRole)
    return "\n".join(lines) + "\n"


def _write(path: Path, content: str) -> None:
    path.write_text(content.replace("\r\n", "\n"), encoding="utf-8", newline="\n")


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
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise OntologyParseError("本体包目录必须不存在或为空", details={"path": str(root)})
    root.mkdir(parents=True, exist_ok=True)

    manifest = PackageManifest(package_id=package_id, version=version, files=_PACKAGE_FILES)
    resources = files(_RESOURCE_PACKAGE)
    _write(root / _PACKAGE_FILES[PackageFileRole.CORE], resources.joinpath("core.ttl").read_text())
    for role in (PackageFileRole.DOMAIN, PackageFileRole.MAPPINGS, PackageFileRole.RULES):
        _write(root / _PACKAGE_FILES[role], _module_content(base_uri))
    _write(
        root / _PACKAGE_FILES[PackageFileRole.SHAPES], resources.joinpath("shapes.ttl").read_text()
    )
    _write(root / "manifest.yaml", _manifest_content(manifest))
    return manifest
