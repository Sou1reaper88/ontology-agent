from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from ontology_core.errors import OntologyParseError, PackageNotFoundError
from ontology_core.models import PackageFileRole, PackageManifest
from ontology_core.parse_diagnostics import safe_parse_details


def _load_manifest_with_bytes(package_dir: str | Path) -> tuple[PackageManifest, bytes]:
    root = Path(package_dir).resolve()
    path = root / "manifest.yaml"
    if not path.is_file():
        raise PackageNotFoundError("本体包清单不存在", details={"path": str(path)})
    try:
        content = path.read_bytes()
    except FileNotFoundError as exc:
        raise PackageNotFoundError("本体包清单不存在", details={"path": str(path)}) from exc
    except OSError as exc:
        raise OntologyParseError(
            "本体包清单读取失败",
            details=safe_parse_details("io_error", "manifest"),
        ) from exc
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OntologyParseError(
            "本体包清单解析失败",
            details=safe_parse_details("invalid_utf8", "manifest"),
        ) from exc
    try:
        raw = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise OntologyParseError(
            "本体包清单解析失败",
            details=safe_parse_details("yaml_syntax_error", "manifest", exc),
        ) from exc
    try:
        return PackageManifest.model_validate(raw), content
    except ValidationError as exc:
        raise OntologyParseError(
            "本体包清单解析失败",
            details=safe_parse_details("manifest_schema_error", "manifest"),
        ) from exc


def load_manifest(package_dir: str | Path) -> PackageManifest:
    manifest, _ = _load_manifest_with_bytes(package_dir)
    return manifest


def resolve_package_files(
    package_dir: str | Path,
    manifest: PackageManifest,
) -> dict[PackageFileRole, Path]:
    root = Path(package_dir).resolve()
    resolved: dict[PackageFileRole, Path] = {}
    for role in PackageFileRole:
        relative = Path(manifest.files[role])
        if relative.is_absolute() or ".." in relative.parts:
            raise OntologyParseError(
                "本体包文件路径不安全",
                details={"role": role.value, "path": str(relative)},
            )
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root):
            raise OntologyParseError(
                "本体包文件路径越界",
                details={"role": role.value, "path": str(candidate)},
            )
        if not candidate.is_file():
            raise PackageNotFoundError(
                "本体包文件不存在",
                details={"role": role.value, "path": str(candidate)},
            )
        resolved[role] = candidate
    return resolved
