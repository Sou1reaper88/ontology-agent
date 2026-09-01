from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from config.settings import OntologySettings
from ontology_core.management.paths import (
    OntologyManagementConfigurationError,
    OntologyPathError,
    resolve_management_root,
    safe_child,
)


def test_ontology_settings_expose_management_defaults() -> None:
    settings = OntologySettings()

    assert settings.management_root == ""
    assert settings.management_workspace == "evaluation"
    assert settings.import_token_ttl_seconds == 900
    assert settings.max_upload_bytes == 20 * 1024 * 1024
    assert settings.max_xlsx_uncompressed_bytes == 100 * 1024 * 1024


def test_management_root_must_be_configured(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()

    with pytest.raises(OntologyManagementConfigurationError, match="必须配置"):
        resolve_management_root("   ", repository)


def test_management_root_must_be_outside_repository(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()

    with pytest.raises(OntologyManagementConfigurationError, match="Git 工作树之外"):
        resolve_management_root(str(repository / ".local"), repository)


@pytest.mark.parametrize("reserved_segment", (".local", ".worktrees"))
def test_management_root_rejects_reserved_path_segments(reserved_segment: str) -> None:
    base = Path(Path.cwd().anchor) / "ontology-management-boundary-tests"
    repository = base / "repo"
    management_root = base / reserved_segment / "management"

    with pytest.raises(OntologyManagementConfigurationError, match="保留目录"):
        resolve_management_root(str(management_root), repository)


@pytest.mark.parametrize("suffix", ((), ("ontology-management",)))
def test_management_root_rejects_system_temp_root_and_descendants(
    suffix: tuple[str, ...],
) -> None:
    system_temp = Path(tempfile.gettempdir()).resolve()
    repository = Path(Path.cwd().anchor) / "ontology-management-boundary-tests" / "repo"
    management_root = system_temp.joinpath(*suffix)

    with pytest.raises(OntologyManagementConfigurationError, match="系统临时目录"):
        resolve_management_root(str(management_root), repository)


def test_management_root_accepts_a_valid_sibling_directory() -> None:
    base = Path(Path.cwd().anchor) / "ontology-management-boundary-tests"
    repository = base / "repo"
    management_root = base / "management"

    assert resolve_management_root(str(management_root), repository) == management_root.resolve()


@pytest.mark.parametrize("parts", (("..", "outside"), ("nested/../outside",), ("",)))
def test_safe_child_rejects_path_escape_or_ambiguous_segments(
    tmp_path: Path, parts: tuple[str, ...]
) -> None:
    with pytest.raises(OntologyPathError):
        safe_child(tmp_path, *parts)


def test_safe_child_rejects_absolute_child_segment(tmp_path: Path) -> None:
    absolute_child = (tmp_path / "outside").resolve()

    with pytest.raises(OntologyPathError):
        safe_child(tmp_path, str(absolute_child))


def test_safe_child_returns_a_regular_child(tmp_path: Path) -> None:
    assert (
        safe_child(tmp_path, "workspaces", "evaluation") == tmp_path / "workspaces" / "evaluation"
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_windows_reparse_point_rejects_child_traversal_and_management_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    repository = tmp_path / "repository"
    child_target = tmp_path / "child-target"
    root_target = tmp_path / "root-target"
    child_junction = root / "junction"
    management_root_junction = tmp_path / "management-junction"
    root.mkdir()
    repository.mkdir()
    child_target.mkdir()
    root_target.mkdir()

    for junction, target in (
        (child_junction, child_target),
        (management_root_junction, root_target),
    ):
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    with pytest.raises(OntologyPathError):
        safe_child(root, "junction", "draft.json")
    with pytest.raises(OntologyManagementConfigurationError):
        resolve_management_root(str(management_root_junction), repository)


def test_safe_child_rejects_windows_drive_relative_segment(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows-specific path behavior")

    with pytest.raises(OntologyPathError):
        safe_child(tmp_path, "C:relative")
