from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from ontology_core.errors import OntologyParseError, PackageNotFoundError
from ontology_core.models import PackageFileRole, PackageManifest


def load_manifest(package_dir: str | Path) -> PackageManifest:
    root = Path(package_dir).resolve()
    path = root / "manifest.yaml"
    if not path.is_file():
        raise PackageNotFoundError("本体包清单不存在", details={"path": str(path)})
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return PackageManifest.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise OntologyParseError(
            "本体包清单解析失败",
            details={"path": str(path), "reason": str(exc)},
        ) from exc


def resolve_package_files(
    package_dir: str | Path,
    manifest: PackageManifest,
) -> dict[PackageFileRole, Path]:
    root = Path(package_dir).resolve()
    resolved: dict[PackageFileRole, Path] = {}
    for role in PackageFileRole:
        candidate = (root / manifest.files[role]).resolve()
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
