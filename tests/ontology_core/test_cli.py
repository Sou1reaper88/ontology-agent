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


def _assert_valid_payload(payload: dict[str, object], *, package_path: Path) -> None:
    assert set(payload) == {"status", "package", "counts"}
    assert payload["status"] == "valid"
    package = payload["package"]
    assert isinstance(package, dict)
    assert set(package) == {"package_id", "version", "sha256"}
    assert package["package_id"] == "example.neutral"
    assert package["version"] == "1.0.0"
    assert isinstance(package["sha256"], str)
    assert re.fullmatch(r"[0-9a-f]{64}", package["sha256"])
    assert payload["counts"] == {
        "concepts": 2,
        "properties": 1,
        "relations": 1,
        "rules": 1,
        "data_sources": 1,
        "mappings": 1,
    }
    assert {"identifiers", "source_path", "source", "loaded_at", "timestamp"}.isdisjoint(
        _all_keys(payload)
    )
    assert str(package_path.resolve()) not in json.dumps(payload, ensure_ascii=False)


def _all_keys(value: object) -> set[str]:
    if not isinstance(value, dict):
        return set()
    return set(value) | {key for item in value.values() for key in _all_keys(item)}


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
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["validate", str(valid_package_dir)]) == 0
    assert capsys.readouterr().out == "valid: example.neutral@1.0.0\n"

    package_dir = tmp_path / "valid-package"
    _copy_package(valid_package_dir, package_dir)

    assert main(["validate", str(package_dir), "--json"]) == 0
    _assert_valid_payload(json.loads(capsys.readouterr().out), package_path=package_dir)


def test_malformed_package_json_error_is_stable(
    valid_package_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    broken = tmp_path / "broken"
    _copy_package(valid_package_dir, broken)
    broken.joinpath("manifest.yaml").write_text("package_id: [\n", encoding="utf-8")

    assert main(["validate", str(broken), "--json"]) == 1
    output = capsys.readouterr()

    assert output.out == ""
    payload = json.loads(output.err)
    assert output.err == json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    assert payload == {
        "code": "ontology_parse_error",
        "message": "本体包清单解析失败",
        "details": {
            "path": str((broken / "manifest.yaml").resolve()),
            "reason": (
                "while parsing a flow node\n"
                "expected the node content, but found '<stream end>'\n"
                '  in "<unicode string>", line 2, column 1:\n'
                "    \n"
                "    ^"
            ),
        },
    }
    assert "traceback" not in output.err.casefold()


def test_inspect_counts_excludes_identifiers_and_source_path(
    valid_package_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    package_dir = tmp_path / "valid-package"
    _copy_package(valid_package_dir, package_dir)

    assert main(["inspect", str(package_dir), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    _assert_valid_payload(payload, package_path=package_dir)


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
    assert set(payload) == {"status", "package", "counts", "identifiers"}
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
