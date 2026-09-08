import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_settings_accepts_ontology_management_environment() -> None:
    environment = os.environ.copy()
    environment["ONTOLOGY__MANAGEMENT_ROOT"] = "C:/ontology-management"
    environment["ONTOLOGY__MANAGEMENT_WORKSPACE"] = "evaluation"

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from config.settings import settings; "
            "print(settings.ontology.management_root, settings.ontology.management_workspace)",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "C:/ontology-management evaluation"
