from __future__ import annotations

import os
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


def test_management_root_accepts_a_valid_sibling_directory(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    management_root = tmp_path / "management"
    repository.mkdir()
    management_root.mkdir()

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


def test_safe_child_rejects_symlink_traversal(tmp_path: Path) -> None:
    target = tmp_path / "target"
    link = tmp_path / "link"
    target.mkdir()
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(OntologyPathError):
        safe_child(tmp_path, "link", "draft.json")


def test_safe_child_rejects_reparse_point_traversal_when_supported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    candidate = root / "junction"
    candidate.mkdir()
    if not hasattr(Path, "is_junction"):
        pytest.skip("Path.is_junction is unavailable on this Python version")

    monkeypatch.setattr(Path, "is_junction", lambda self: self == candidate)

    with pytest.raises(OntologyPathError):
        safe_child(root, "junction", "draft.json")


def test_safe_child_rejects_windows_drive_relative_segment(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows-specific path behavior")

    with pytest.raises(OntologyPathError):
        safe_child(tmp_path, "C:relative")
