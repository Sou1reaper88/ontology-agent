"""Filesystem boundary checks for external ontology-management state."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from ontology_core.errors import OntologyError

_RESERVED_MANAGEMENT_ROOT_SEGMENTS = frozenset({".local", ".worktrees"})


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
    management_root = configured_path.resolve(strict=False)
    resolved_repository = repository_root.resolve(strict=False)
    if _is_within(management_root, resolved_repository):
        raise OntologyManagementConfigurationError("本体管理根目录必须位于 Git 工作树之外")
    if _is_within(management_root, Path(tempfile.gettempdir()).resolve(strict=False)):
        raise OntologyManagementConfigurationError("本体管理根目录不能位于系统临时目录")
    if _contains_reserved_management_segment(management_root):
        raise OntologyManagementConfigurationError(
            "本体管理根目录不能位于 .local 或 .worktrees 保留目录"
        )
    if _contains_reparse_point(configured_path):
        raise OntologyManagementConfigurationError("本体管理根目录不能经过符号链接或 reparse point")
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


def _contains_reserved_management_segment(path: Path) -> bool:
    reserved = {os.path.normcase(segment) for segment in _RESERVED_MANAGEMENT_ROOT_SEGMENTS}
    return any(os.path.normcase(part) in reserved for part in path.parts)


def _contains_reparse_point(path: Path) -> bool:
    absolute_path = path.expanduser()
    if not absolute_path.is_absolute():
        absolute_path = Path.cwd() / absolute_path
    for candidate in (absolute_path, *absolute_path.parents):
        if _is_reparse_point(candidate):
            return True
    return False


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        file_attributes = path.lstat().st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(file_attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        common = os.path.commonpath((os.path.normcase(str(candidate)), os.path.normcase(str(root))))
    except ValueError:
        return False
    return Path(common) == Path(os.path.normcase(str(root)))
