from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ontology_core.cli import main
from ontology_core.inspection import inspect_package


def _copy_package(source: Path, target: Path) -> None:
    target.mkdir()
    for path in source.iterdir():
        target.joinpath(path.name).write_bytes(path.read_bytes())


def test_init_creates_package_and_refuses_to_overwrite(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    package_dir = tmp_path / "package"

    assert (
        main(
            [
                "init",
                str(package_dir),
                "--package-id",
                "example.neutral",
                "--base-uri",
                "https://example.invalid/private/",
                "--version",
                "1.0.0",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out == "initialized: example.neutral@1.0.0\n"

    assert (
        main(
            [
                "init",
                str(package_dir),
                "--package-id",
                "example.neutral",
                "--base-uri",
                "https://example.invalid/private/",
            ]
        )
        == 1
    )
    error = capsys.readouterr().err
    assert "ontology_parse_error" in error
    assert "traceback" not in error.casefold()


def test_validate_text_and_json_success(
    valid_package_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["validate", str(valid_package_dir)]) == 0
    assert capsys.readouterr().out == "valid: example.neutral@1.0.0\n"

    assert main(["validate", str(valid_package_dir), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "valid"
    assert payload["package"]["package_id"] == "example.neutral"
    assert payload["package"]["version"] == "1.0.0"
    assert re.fullmatch(r"[0-9a-f]{64}", payload["package"]["sha256"])
    assert payload["counts"] == {
        "concepts": 2,
        "properties": 1,
        "relations": 1,
        "rules": 1,
        "data_sources": 1,
        "mappings": 1,
    }
    assert "identifiers" not in payload
    assert str(valid_package_dir) not in json.dumps(payload, ensure_ascii=False)


def test_malformed_package_json_error_is_stable(
    valid_package_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    broken = tmp_path / "broken"
    _copy_package(valid_package_dir, broken)
    broken.joinpath("manifest.yaml").write_text("package_id: [\n", encoding="utf-8")

    assert main(["validate", str(broken), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["code"] == "ontology_parse_error"
    assert payload["message"]
    assert isinstance(payload["details"], dict)
    assert "traceback" not in json.dumps(payload).casefold()


def test_inspect_counts_excludes_identifiers_and_source_path(
    valid_package_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["inspect", str(valid_package_dir), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "valid"
    assert payload["counts"]["concepts"] == 2
    assert "identifiers" not in payload
    assert str(valid_package_dir) not in json.dumps(payload, ensure_ascii=False)


def test_inspect_lists_sorted_identifiers(
    valid_package_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inspection = inspect_package(valid_package_dir, list_identifiers=True)

    assert inspection.identifiers == tuple(sorted(inspection.identifiers or ()))
    assert inspection.identifiers == (
        "https://example.invalid/ontology/Metric",
        "https://example.invalid/ontology/MetricMapping",
        "https://example.invalid/ontology/NeutralSource",
        "https://example.invalid/ontology/Record",
        "https://example.invalid/ontology/RecordRule",
        "https://example.invalid/ontology/RelatedRecord",
        "https://example.invalid/ontology/relatesTo",
    )

    assert main(["inspect", str(valid_package_dir), "--json", "--list-identifiers"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["identifiers"] == list(inspection.identifiers)


def test_cli_exit_codes_for_domain_and_argument_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["validate", str(tmp_path / "missing")]) == 1
    assert "package_not_found" in capsys.readouterr().err

    with pytest.raises(SystemExit) as caught:
        main(["inspect"])

    assert caught.value.code == 2
