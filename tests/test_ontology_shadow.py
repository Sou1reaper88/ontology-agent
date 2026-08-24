from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agent.ontology_shadow import OntologyRuntime, OntologyShadowService
from ontology_core.models import PackageInfo
from ontology_core.repository import OntologySnapshot
from ontology_core.semantic_models import (
    BusinessRule,
    Concept,
    DataSource,
    LocalizedText,
    PhysicalMapping,
    Property,
    RdfLiteral,
    RuleExpression,
    RuleOperator,
    SemanticCatalog,
)

XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"


def _text(value: str) -> tuple[LocalizedText, ...]:
    return (LocalizedText(value=value, language="zh-CN"),)


def _snapshot(*, duplicate: bool = False, missing_field_mapping: bool = False) -> OntologySnapshot:
    customer = Concept(
        uri="https://example.invalid/ontology/Customer",
        short_name="Customer",
        label="客户",
        labels=_text("客户"),
    )
    concepts = [customer]
    if duplicate:
        concepts.append(
            Concept(
                uri="https://example.invalid/ontology/OtherCustomer",
                short_name="OtherCustomer",
                label="客户",
                labels=_text("客户"),
            )
        )
    customer_id = Property(
        uri="https://example.invalid/ontology/CustomerId",
        short_name="CustomerId",
        label="客户编号",
        labels=_text("客户编号"),
        concept_uri=customer.uri,
        datatype_uri=XSD_STRING,
    )
    status = Property(
        uri="https://example.invalid/ontology/Status",
        short_name="Status",
        label="客户状态",
        labels=_text("客户状态"),
        concept_uri=customer.uri,
        datatype_uri=XSD_STRING,
    )
    source = DataSource(
        uri="https://example.invalid/ontology/Warehouse",
        short_name="Warehouse",
        label="分析仓库",
        labels=_text("分析仓库"),
        platform_type="generic",
        dialect="generic",
    )
    mappings = [
        PhysicalMapping(
            uri="https://example.invalid/ontology/CustomerTable",
            short_name="CustomerTable",
            label="客户对象映射",
            labels=_text("客户对象映射"),
            semantic_element_uri=customer.uri,
            data_source_uri=source.uri,
            physical_namespace="analytics",
            object_name="customer_snapshot",
        ),
        PhysicalMapping(
            uri="https://example.invalid/ontology/StatusField",
            short_name="StatusField",
            label="状态字段映射",
            labels=_text("状态字段映射"),
            semantic_element_uri=status.uri,
            data_source_uri=source.uri,
            field_name="status_code",
        ),
    ]
    if not missing_field_mapping:
        mappings.append(
            PhysicalMapping(
                uri="https://example.invalid/ontology/CustomerIdField",
                short_name="CustomerIdField",
                label="编号字段映射",
                labels=_text("编号字段映射"),
                semantic_element_uri=customer_id.uri,
                data_source_uri=source.uri,
                field_name="customer_id",
            )
        )
    rule = BusinessRule(
        uri="https://example.invalid/ontology/ActiveCustomer",
        short_name="ActiveCustomer",
        label="只统计有效客户",
        labels=_text("只统计有效客户"),
        applies_to_uri=customer.uri,
        property_uris=(status.uri,),
        condition=RuleExpression(
            operator=RuleOperator.EQ,
            property_uri=status.uri,
            values=(RdfLiteral(lexical_form="ACTIVE", datatype_uri=XSD_STRING),),
        ),
        status="active",
        priority=10,
    )
    return OntologySnapshot(
        info=PackageInfo(
            package_id="example.shadow",
            version="1.0.0",
            sha256="a" * 64,
            loaded_at=datetime.now(UTC),
            source="C:\\private\\fictional-package-secret",
        ),
        catalog=SemanticCatalog(
            concepts=tuple(concepts),
            properties=(customer_id, status),
            rules=(rule,),
            data_sources=(source,),
            mappings=tuple(mappings),
        ),
        _data_nt="",
        _shapes_nt="",
    )


class _StaticRuntime:
    def __init__(self, snapshot: OntologySnapshot) -> None:
        self._snapshot = snapshot

    def snapshot(self) -> OntologySnapshot:
        return self._snapshot


class _BrokenRuntime:
    def snapshot(self) -> OntologySnapshot:
        raise RuntimeError("C:\\private\\fictional-package-secret")


def test_shadow_generates_sql_and_evidence_without_reading_legacy_sql() -> None:
    service = OntologyShadowService(runtime=_StaticRuntime(_snapshot()))

    first = service.preview("查询客户编号", "SELECT legacy_one FROM old_table;")
    second = service.preview("查询客户编号", "SELECT different FROM other_table;")

    assert first.status == "generated"
    assert first.ontology_sql == second.ontology_sql
    assert first.ontology_sql == (
        'SELECT "customer_id" FROM "analytics"."customer_snapshot" '
        "WHERE \"status_code\" = 'ACTIVE';"
    )
    assert first.diff.changed is True
    assert first.diff.legacy_tables == ("old_table",)
    assert first.diff.ontology_tables == ("analytics.customer_snapshot",)
    assert first.evidence.concepts == ("Customer",)
    assert first.evidence.properties == ("CustomerId",)
    assert first.evidence.rules == ("ActiveCustomer",)
    assert first.package is not None and first.package.sha256 == "a" * 12


def test_shadow_maps_planning_outcomes_without_guessing_sql() -> None:
    no_match = OntologyShadowService(runtime=_StaticRuntime(_snapshot())).preview(
        "查询无关对象", "SELECT 1;"
    )
    ambiguous = OntologyShadowService(runtime=_StaticRuntime(_snapshot(duplicate=True))).preview(
        "查询客户", "SELECT 1;"
    )
    unsupported = OntologyShadowService(
        runtime=_StaticRuntime(_snapshot(missing_field_mapping=True))
    ).preview("查询客户编号", "SELECT 1;")

    assert no_match.status == "no_match" and no_match.ontology_sql is None
    assert ambiguous.status == "ambiguous" and ambiguous.ontology_sql is None
    assert unsupported.status == "unsupported" and unsupported.ontology_sql is None


def test_shadow_failure_and_disabled_mode_return_safe_unavailable_result() -> None:
    broken = OntologyShadowService(runtime=_BrokenRuntime()).preview("查询客户编号", "SELECT 1;")
    disabled = OntologyShadowService(runtime=None, enabled=False).preview(
        "查询客户编号", "SELECT 1;"
    )

    assert broken.status == "unavailable"
    assert broken.ontology_sql is None
    assert "fictional-package-secret" not in broken.model_dump_json()
    assert disabled.status == "unavailable"


def test_runtime_publishes_an_external_package() -> None:
    valid_package_dir = Path(__file__).parent / "fixtures" / "ontology_core" / "valid"
    snapshot = OntologyRuntime(valid_package_dir).snapshot()

    assert snapshot.info.package_id == "example.neutral"
    assert OntologyRuntime(valid_package_dir).snapshot().info.sha256 == snapshot.info.sha256
