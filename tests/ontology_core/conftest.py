from pathlib import Path

import pytest


@pytest.fixture()
def valid_package_dir() -> Path:
    return Path(__file__).parent.parent / "fixtures" / "ontology_core" / "valid"
