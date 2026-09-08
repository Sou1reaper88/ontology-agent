from __future__ import annotations

import json
from pathlib import Path

import pytest

from ontology_core.errors import OntologyImportError
from ontology_core.tabular_metadata import (
    DiagnosticSeverity,
    MetadataOverrides,
    analyze_metadata,
    apply_metadata_overrides,
    load_metadata_overrides,
    parse_tabular_metadata,
    raise_for_blocking_diagnostics,
)

SYNTHETIC_TSV = (
    "属性英文名\t对象中文名称\t对象英文名称\t额外列\t属性中文名\t属性类型\t"
    "属性描述\t对象描述\t状态\t是否主键\t是否标题\n"
    "ENTITY_ID\t演示实体月表\tDEMO_ENTITY_M\tignored\t实体编码\tstring\t"
    "实体的稳定编码\t用于测试的合成对象\t启用\t是\t是\n"
    "P_MON\t\tDEMO_ENTITY_M\tignored\t时间分区\tstring\t\t\t\t\t\n"
)


def test_parse_tabular_metadata_groups_one_object_and_preserves_identifiers() -> None:
    draft = parse_tabular_metadata(SYNTHETIC_TSV)

    assert draft.table.physical_name == "DEMO_ENTITY_M"
    assert draft.table.label == "演示实体月表"
    assert draft.table.description == "用于测试的合成对象"
    assert draft.table.enabled is True
    assert [field.physical_name for field in draft.fields] == ["ENTITY_ID", "P_MON"]
    assert draft.fields[0].primary_key is True
    assert draft.fields[0].title is True
    assert draft.fields[0].location.line == 2
    assert draft.fields[1].description is None


def test_parse_tabular_metadata_matches_headers_in_any_order_and_ignores_extra_columns() -> None:
    text = """无关列\t属性描述\t属性英文名\t对象英文名称\t属性中文名
unused\t字段说明\tVALUE_CODE\tDEMO_OBJECT\t值编码
"""

    draft = parse_tabular_metadata(text)

    assert draft.table.physical_name == "DEMO_OBJECT"
    assert draft.fields[0].physical_name == "VALUE_CODE"
    assert draft.fields[0].description == "字段说明"


def test_parse_tabular_metadata_strips_optional_cells_without_changing_identifier_case() -> None:
    text = (
        "对象英文名称\t属性英文名\t属性中文名\t属性类型\n"
        "  MixedCaseTable  \t  MixedCaseField  \t  混合字段  \t  STRING  \n"
    )

    draft = parse_tabular_metadata(text)

    assert draft.table.physical_name == "MixedCaseTable"
    assert draft.fields[0].physical_name == "MixedCaseField"
    assert draft.fields[0].label == "混合字段"
    assert draft.fields[0].source_type == "STRING"


def test_parse_tabular_metadata_rejects_missing_required_headers() -> None:
    text = """对象中文名称\t属性中文名
演示对象\t实体编码
"""

    with pytest.raises(OntologyImportError, match="缺少必需列") as exc_info:
        parse_tabular_metadata(text)

    assert exc_info.value.details == {"columns": ["对象英文名称", "属性英文名"]}


def test_parse_tabular_metadata_records_missing_required_cells_as_diagnostics() -> None:
    text = """对象英文名称\t属性英文名\t属性中文名
DEMO_A\t\t缺少英文名
DEMO_A\tENTITY_ID\t实体编码
"""

    diagnostics = analyze_metadata(parse_tabular_metadata(text))

    issue = next(item for item in diagnostics if item.code == "missing_field_name")
    assert issue.severity is DiagnosticSeverity.ERROR
    assert issue.location is not None
    assert issue.location.line == 2
    assert issue.location.column == "属性英文名"


def test_analyze_metadata_reports_blocking_and_non_blocking_quality_issues() -> None:
    text = """对象英文名称\t对象中文名称\t对象描述\t属性英文名\t属性中文名\t属性类型\t属性描述
DEMO_A\t演示对象\t\tENTITY_ID\t实体编码\tstring\t实体的编码
DEMO_A\t\t\tentity_id\t实体编码\tmystery\t完全不同含义
DEMO_A\t\t\tBAD-NAME\t状态\tstring\t竞争对手状态
DEMO_B\t另一对象\t\tOTHER_ID\t其他编码\tstring\t
"""

    diagnostics = analyze_metadata(parse_tabular_metadata(text))
    by_code = {item.code: item for item in diagnostics}

    assert by_code["multiple_objects"].severity is DiagnosticSeverity.ERROR
    assert by_code["duplicate_field"].severity is DiagnosticSeverity.ERROR
    assert by_code["invalid_field_identifier"].severity is DiagnosticSeverity.ERROR
    assert by_code["blank_table_description"].severity is DiagnosticSeverity.WARNING
    assert by_code["blank_field_description"].severity is DiagnosticSeverity.WARNING
    assert by_code["unknown_field_type"].severity is DiagnosticSeverity.WARNING
    assert by_code["metadata_text_conflict"].severity is DiagnosticSeverity.CONFIRMATION_REQUIRED
    assert all("DEMO_A\t" not in item.message for item in diagnostics)


def test_analyze_metadata_does_not_flag_related_chinese_synonyms_as_conflicts() -> None:
    text = """对象英文名称\t对象描述\t属性英文名\t属性中文名\t属性类型\t属性描述
DEMO_A\t合成对象\tBANK_CODE\t银行代码\tstring\t银行编号
"""

    diagnostics = analyze_metadata(parse_tabular_metadata(text))

    assert "metadata_text_conflict" not in {item.code for item in diagnostics}


def test_raise_for_blocking_diagnostics_returns_only_safe_structured_details() -> None:
    text = """对象英文名称\t属性英文名\t属性中文名
DEMO_A\tBAD-NAME\t错误字段
"""
    diagnostics = analyze_metadata(parse_tabular_metadata(text))

    with pytest.raises(OntologyImportError) as exc_info:
        raise_for_blocking_diagnostics(diagnostics)

    assert exc_info.value.code == "ontology_import_error"
    assert exc_info.value.message == "元数据包含阻断问题"
    assert exc_info.value.details["diagnostics"][0]["code"] == "invalid_field_identifier"
    assert "DEMO_A\t" not in str(exc_info.value.details)


def test_apply_metadata_overrides_updates_description_and_aliases(tmp_path: Path) -> None:
    draft = parse_tabular_metadata(SYNTHETIC_TSV)
    override_path = tmp_path / "overrides.json"
    override_path.write_text(
        json.dumps(
            {
                "fields": {
                    "entity_id": {
                        "description": "已确认的实体状态编码",
                        "aliases": ["实体编号"],
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    overrides = load_metadata_overrides(override_path)
    updated = apply_metadata_overrides(draft, overrides)

    assert updated.fields[0].physical_name == "ENTITY_ID"
    assert updated.fields[0].description == "已确认的实体状态编码"
    assert updated.fields[0].aliases == ("实体编号",)
    assert draft.fields[0].description == "实体的稳定编码"


def test_apply_metadata_overrides_rejects_unknown_fields(tmp_path: Path) -> None:
    draft = parse_tabular_metadata(SYNTHETIC_TSV)
    override_path = tmp_path / "overrides.yaml"
    override_path.write_text(
        "fields:\n  UNKNOWN_FIELD:\n    description: 无法匹配\n",
        encoding="utf-8",
    )

    with pytest.raises(OntologyImportError, match="覆盖配置引用了未知字段"):
        apply_metadata_overrides(draft, load_metadata_overrides(override_path))


def test_load_metadata_overrides_forbids_physical_identifier_changes(tmp_path: Path) -> None:
    override_path = tmp_path / "overrides.json"
    override_path.write_text(
        json.dumps(
            {"fields": {"ENTITY_ID": {"physical_name": "CHANGED_ID"}}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(OntologyImportError, match="本地覆盖配置无效"):
        load_metadata_overrides(override_path)


def test_apply_overrides_attaches_confirmed_temporal_policy(tmp_path: Path) -> None:
    draft = parse_tabular_metadata(SYNTHETIC_TSV)
    override_path = tmp_path / "overrides.json"
    override_path.write_text(
        json.dumps(
            {
                "temporal_policy": {
                    "field": "p_mon",
                    "grain": "month",
                    "default_strategy": "previous_complete_month",
                    "allow_query_override": True,
                }
            }
        ),
        encoding="utf-8",
    )

    updated = apply_metadata_overrides(draft, load_metadata_overrides(override_path))

    assert updated.temporal_policy is not None
    assert updated.temporal_policy.field == "P_MON"
    assert draft.temporal_policy is None


def test_apply_overrides_does_not_infer_temporal_policy_from_labels() -> None:
    draft = parse_tabular_metadata(SYNTHETIC_TSV)

    updated = apply_metadata_overrides(draft, MetadataOverrides())

    assert updated.temporal_policy is None


def test_temporal_policy_override_rejects_unknown_field_and_strategy_pair(
    tmp_path: Path,
) -> None:
    draft = parse_tabular_metadata(SYNTHETIC_TSV)
    unknown_path = tmp_path / "unknown.json"
    unknown_path.write_text(
        json.dumps(
            {
                "temporal_policy": {
                    "field": "UNKNOWN_FIELD",
                    "grain": "month",
                    "default_strategy": "previous_complete_month",
                }
            }
        ),
        encoding="utf-8",
    )
    mismatch_path = tmp_path / "mismatch.json"
    mismatch_path.write_text(
        json.dumps(
            {
                "temporal_policy": {
                    "field": "P_MON",
                    "grain": "month",
                    "default_strategy": "t_minus_2",
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(OntologyImportError, match="时间分区策略引用了未知字段"):
        apply_metadata_overrides(draft, load_metadata_overrides(unknown_path))
    with pytest.raises(OntologyImportError, match="本地覆盖配置无效"):
        load_metadata_overrides(mismatch_path)
