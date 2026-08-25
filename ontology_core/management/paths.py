"""Filesystem boundary checks for external ontology-management state."""

from __future__ import annotations

import os
from pathlib import Path

from ontology_core.errors import OntologyError


class OntologyManagementConfigurationError(OntologyError):
    """Raised when the configured management root is unsafe."""

    code = "ontology_management_configuration_error"


class OntologyPathError(OntologyError):
    """Raised when a management path could escape its configured root."""

    code = "ontology_management_path_error"


def resolve_management_root(configured: str, repository_root: Path) -> Path:
    """Resolve and validate an externally configured management directory."""
    if not configured.strip():
        raise OntologyManagementConfigurationError("本体管理根目录必须配置")

    configured_path = Path(configured).expanduser()
    if _contains_reparse_point(configured_path):
        raise OntologyManagementConfigurationError("本体管理根目录不能经过符号链接或 reparse point")

    management_root = configured_path.resolve(strict=False)
    resolved_repository = repository_root.resolve(strict=False)
    if _is_within(management_root, resolved_repository):
        raise OntologyManagementConfigurationError("本体管理根目录必须位于 Git 工作树之外")
    return management_root


def safe_child(root: Path, *parts: str) -> Path:
    """Return a non-link child path while rejecting traversal and reparse points."""
    if not parts:
        raise OntologyPathError("管理路径必须包含子路径")
    if _contains_reparse_point(root):
        raise OntologyPathError("管理根目录不能经过符号链接或 reparse point")

    resolved_root = root.resolve(strict=False)
    candidate = resolved_root
    for part in parts:
        _require_plain_child_part(part)
        candidate = candidate / part
        if _contains_reparse_point(candidate):
            raise OntologyPathError("管理路径不能经过符号链接或 reparse point")

    resolved_candidate = candidate.resolve(strict=False)
    if not _is_within(resolved_candidate, resolved_root):
        raise OntologyPathError("管理路径不能越出管理根目录")
    return candidate


def _require_plain_child_part(part: str) -> None:
    segment = Path(part)
    if not part or segment.is_absolute() or segment.drive or segment.root:
        raise OntologyPathError("管理路径包含绝对或空子路径")
    if len(segment.parts) != 1 or segment.parts[0] in {".", ".."}:
        raise OntologyPathError("管理路径包含不安全的子路径")


def _contains_reparse_point(path: Path) -> bool:
    absolute_path = path.expanduser()
    if not absolute_path.is_absolute():
        absolute_path = Path.cwd() / absolute_path
    for candidate in (absolute_path, *absolute_path.parents):
        if candidate.is_symlink() or _is_junction(candidate):
            return True
    return False


def _is_junction(path: Path) -> bool:
    checker = getattr(path, "is_junction", None)
    return bool(checker()) if checker is not None else False


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        common = os.path.commonpath((os.path.normcase(str(candidate)), os.path.normcase(str(root))))
    except ValueError:
        return False
    return Path(common) == Path(os.path.normcase(str(root)))
