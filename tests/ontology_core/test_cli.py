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


def _append_secret_shape(package_dir: Path) -> None:
    shapes = package_dir / "shapes.ttl"
    shapes.write_text(
        shapes.read_text(encoding="utf-8") + """

<https://example.invalid/fictional-secret-source-shape> a sh:NodeShape ;
    sh:targetNode <https://example.invalid/ontology/Record> ;
    sh:severity <https://example.invalid/fictional-secret-severity> ;
    sh:property [
        sh:path <https://example.invalid/fictional-secret-path> ;
        sh:minCount 1 ;
        sh:message "fictional-secret-shacl-message"
    ] .
""",
        encoding="utf-8",
    )


def _append_credential_predicate(package_dir: Path) -> None:
    mappings = package_dir / "mappings.ttl"
    mappings.write_text(
        mappings.read_text(encoding="utf-8")
        + "\nex:MetricMapping <https://example.invalid/fictional-secret/password> "
        '"fictional-secret-value" .\n',
        encoding="utf-8",
    )


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
        "temporal_policies": 0,
    }
    assert {"identifiers", "source_path", "source", "loaded_at", "timestamp"}.isdisjoint(
        _all_keys(payload)
    )
    assert str(package_path.resolve()) not in json.dumps(payload, ensure_ascii=False)


def _all_keys(value: object) -> set[str]:
    if not isinstance(value, dict):
        return set()
    return set(value) | {key for item in value.values() for key in _all_keys(item)}


def _write_tabular_fixture(path: Path) -> None:
    path.write_text(
        "对象英文名称\t对象中文名称\t对象描述\t属性英文名\t属性中文名\t属性类型\t属性描述\n"
        "DEMO_ENTITY\t演示实体\t合成测试对象\tENTITY_ID\t实体编码\tstring\t实体编码的稳定说明\n"
        "DEMO_ENTITY\t\t\tTOTAL_VALUE\t累计值\tdecimal\t合成累计值\n",
        encoding="utf-8",
    )


def _import_tabular_args(input_path: Path, target: Path) -> list[str]:
    return [
        "import-tabular",
        str(input_path),
        str(target),
        "--package-id",
        "tests.cli-import",
        "--base-uri",
        "https://example.invalid/tests/cli-import/",
        "--version",
        "1.0.0",
        "--physical-namespace",
        "demo_warehouse",
        "--platform-type",
        "synthetic",
        "--dialect",
        "generic",
        "--json",
    ]


def test_import_tabular_json_generates_package_and_report(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "metadata.tsv"
    target = tmp_path / "package"
    report = tmp_path / "report.json"
    _write_tabular_fixture(input_path)

    args = _import_tabular_args(input_path, target)
    args[2:2] = ["--report", str(report)]
    assert main(args) == 0

    output = capsys.readouterr()
    assert output.err == ""
    payload = json.loads(output.out)
    assert payload["status"] == "imported"
    assert payload["target"] == str(target)
    assert payload["package"]["package_id"] == "tests.cli-import"
    assert payload["counts"] == {
        "concepts": 1,
        "properties": 2,
        "relations": 0,
        "rules": 0,
        "data_sources": 1,
        "mappings": 3,
        "temporal_policies": 0,
    }
    assert payload["diagnostic_counts"] == {
        "error": 0,
        "warning": 0,
        "confirmation_required": 0,
    }
    assert json.loads(report.read_text(encoding="utf-8")) == payload
    assert inspect_package(target).counts.properties == 2


def test_import_tabular_json_returns_safe_blocking_diagnostics(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "metadata.tsv"
    target = tmp_path / "package"
    secret_row = "SAFE_TABLE\tBAD-NAME\tfictional-sensitive-description"
    input_path.write_text(
        "对象英文名称\t属性英文名\t属性描述\n" + secret_row + "\n",
        encoding="utf-8",
    )

    assert main(_import_tabular_args(input_path, target)) == 1

    output = capsys.readouterr()
    payload = json.loads(output.err)
    assert payload["code"] == "ontology_import_error"
    assert payload["details"]["diagnostics"][0]["code"] == "invalid_field_identifier"
    assert secret_row not in output.err
    assert "traceback" not in output.err.casefold()
    assert not target.exists()


def test_import_tabular_rejects_unknown_override_field(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "metadata.tsv"
    target = tmp_path / "package"
    overrides = tmp_path / "overrides.json"
    _write_tabular_fixture(input_path)
    overrides.write_text(
        json.dumps({"fields": {"UNKNOWN_FIELD": {"description": "合成修正"}}}),
        encoding="utf-8",
    )
    args = _import_tabular_args(input_path, target)
    args[2:2] = ["--overrides", str(overrides)]

    assert main(args) == 1

    output = capsys.readouterr()
    payload = json.loads(output.err)
    assert payload["code"] == "ontology_import_error"
    assert payload["message"] == "覆盖配置引用了未知字段"
    assert not target.exists()


def test_import_tabular_requires_replace_for_existing_target(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "metadata.tsv"
    target = tmp_path / "package"
    _write_tabular_fixture(input_path)
    args = _import_tabular_args(input_path, target)
    assert main(args) == 0
    capsys.readouterr()

    assert main(args) == 1

    payload = json.loads(capsys.readouterr().err)
    assert payload["code"] == "ontology_import_error"
    assert payload["message"] == "目标本体包已存在"


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
    secret = "fictional-secret-cli"
    broken.joinpath("manifest.yaml").write_text(
        f"package_id: [{secret}\n",
        encoding="utf-8",
    )

    assert main(["validate", str(broken), "--json"]) == 1
    output = capsys.readouterr()

    assert output.out == ""
    payload = json.loads(output.err)
    assert output.err == json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    assert payload == {
        "code": "ontology_parse_error",
        "message": "本体包清单解析失败",
        "details": {
            "error_type": "yaml_syntax_error",
            "role": "manifest",
            "line": 2,
            "column": 1,
        },
    }
    assert "traceback" not in output.err.casefold()
    assert secret not in output.err
    assert str(broken.resolve()) not in output.err


def test_malformed_turtle_cli_error_does_not_expose_source_or_path(
    valid_package_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    broken = tmp_path / "broken-turtle"
    _copy_package(valid_package_dir, broken)
    secret = "fictional-secret-cli-turtle"
    broken.joinpath("domain.ttl").write_text(
        "@prefix ex: <https://example.invalid/ontology/> .\n" f"ex:{secret} ex:predicate [\n",
        encoding="utf-8",
    )

    assert main(["validate", str(broken), "--json"]) == 1
    output = capsys.readouterr()

    assert output.out == ""
    payload = json.loads(output.err)
    assert payload["details"]["error_type"] == "turtle_syntax_error"
    assert payload["details"]["role"] == "domain"
    assert secret not in output.err
    assert str(broken.resolve()) not in output.err
    assert "traceback" not in output.err.casefold()


def test_deep_rule_cli_error_is_stable_without_traceback(
    valid_package_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    broken = tmp_path / "deep-rule"
    _copy_package(valid_package_dir, broken)
    wrappers = 1200
    lines = [
        "@prefix ex: <https://example.invalid/ontology/> .",
        "@prefix oa: <urn:ontology-agent:core#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        'ex:Rule a oa:BusinessRule ; oa:shortName "Rule" ; rdfs:label "Rule" ;',
        "    oa:appliesTo ex:Record ; oa:condition ex:condition0 .",
    ]
    lines.extend(
        f"ex:condition{index} a oa:Not ; oa:argument ex:condition{index + 1} ."
        for index in range(wrappers)
    )
    lines.append(f"ex:condition{wrappers} a oa:IsNull ; oa:leftProperty ex:Metric .")
    broken.joinpath("rules.ttl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert main(["validate", str(broken), "--json"]) == 1
    output = capsys.readouterr()

    assert output.out == ""
    payload = json.loads(output.err)
    assert payload["code"] == "ontology_validation_error"
    assert "maximum depth of 64" in output.err
    assert "traceback" not in output.err.casefold()
    assert "RecursionError" not in output.err
    assert str(broken.resolve()) not in output.err
    assert "_:" not in output.err


def test_validate_json_does_not_expose_authored_shacl_result_message(
    valid_package_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    broken = tmp_path / "secret-shape"
    _copy_package(valid_package_dir, broken)
    _append_secret_shape(broken)

    assert main(["validate", str(broken), "--json"]) == 1
    output = capsys.readouterr()

    assert output.out == ""
    payload = json.loads(output.err)
    assert payload["code"] == "ontology_validation_error"
    assert payload["details"]["violations"]
    assert "fictional-secret" not in output.err
    for violation in payload["details"]["violations"]:
        for field in ("focus_node", "path", "severity", "source_shape"):
            assert violation[field].startswith(f"urn:ontology-agent:diagnostic:{field}:")
    assert "traceback" not in output.err.casefold()


def test_validate_json_credential_violation_uses_safe_diagnostics(
    valid_package_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    broken = tmp_path / "credential-predicate"
    _copy_package(valid_package_dir, broken)
    _append_credential_predicate(broken)

    assert main(["validate", str(broken), "--json"]) == 1
    output = capsys.readouterr()

    assert output.out == ""
    assert "fictional-secret" not in output.err
    payload = json.loads(output.err)
    violation = next(
        item
        for item in payload["details"]["violations"]
        if item["code"] == "forbidden_credential_predicate"
    )
    assert violation["uri"] == "urn:ontology-agent:diagnostic:credential-configuration"
    assert violation["path"] == "urn:ontology-agent:core#configuration"


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


def test_inspect_text_prints_digest_and_counts_without_sensitive_details(
    valid_package_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    package_dir = tmp_path / "text-package"
    _copy_package(valid_package_dir, package_dir)
    mappings_path = package_dir / "mappings.ttl"
    mappings_path.write_text(
        mappings_path.read_text(encoding="utf-8").replace(
            "    oa:enabled true .",
            '    oa:objectName "fictional_physical_table" ;\n'
            '    oa:fieldName "fictional_physical_field" ;\n'
            "    oa:enabled true .",
        ),
        encoding="utf-8",
    )
    inspection = inspect_package(package_dir)

    assert main(["inspect", str(package_dir)]) == 0
    output = capsys.readouterr().out

    assert output == (
        "valid: example.neutral@1.0.0\n"
        f"sha256: {inspection.package.sha256}\n"
        "counts:\n"
        "  concepts: 2\n"
        "  properties: 1\n"
        "  relations: 1\n"
        "  rules: 1\n"
        "  data_sources: 1\n"
        "  mappings: 1\n"
        "  temporal_policies: 0\n"
    )
    assert str(package_dir.resolve()) not in output
    assert "https://example.invalid/ontology/Record" not in output
    assert "Neutral record used only by tests." not in output
    non_digest_output = "\n".join(
        line for line in output.splitlines() if not line.startswith("sha256: ")
    )
    assert "42" not in non_digest_output
    assert "fictional_physical_table" not in output
    assert "fictional_physical_field" not in output


def test_inspect_text_lists_sorted_identifiers_only_when_requested(
    valid_package_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inspection = inspect_package(valid_package_dir, list_identifiers=True)

    assert main(["inspect", str(valid_package_dir), "--list-identifiers"]) == 0
    output = capsys.readouterr().out

    assert output == (
        "valid: example.neutral@1.0.0\n"
        f"sha256: {inspection.package.sha256}\n"
        "counts:\n"
        "  concepts: 2\n"
        "  properties: 1\n"
        "  relations: 1\n"
        "  rules: 1\n"
        "  data_sources: 1\n"
        "  mappings: 1\n"
        "  temporal_policies: 0\n"
        "identifiers:\n"
        "  https://example.invalid/ontology/Metric\n"
        "  https://example.invalid/ontology/MetricMapping\n"
        "  https://example.invalid/ontology/NeutralSource\n"
        "  https://example.invalid/ontology/Record\n"
        "  https://example.invalid/ontology/RecordRule\n"
        "  https://example.invalid/ontology/RelatedRecord\n"
        "  https://example.invalid/ontology/relatesTo\n"
    )


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
