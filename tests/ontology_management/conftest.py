"""Ontology-management test isolation for production temp-root guards."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _separate_pytest_tmp_from_system_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep tmp_path usable while production code rejects the system temp root."""
    synthetic_system_temp = tmp_path / "synthetic-system-temp"
    synthetic_system_temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(synthetic_system_temp))
