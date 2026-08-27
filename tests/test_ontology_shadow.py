from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent.ontology_shadow import (
    OntologyRuntime,
    OntologyShadowService,
    _configured_service,
    get_ontology_runtime,
    get_ontology_shadow_service,
)
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
    TemporalDefaultStrategy,
    TemporalGrain,
    TemporalPartitionPolicy,
)

XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"


def _text(value: str) -> tuple[LocalizedText, ...]:
    return (LocalizedText(value=value, language="zh-CN"),)


def _snapshot(
    *,
    duplicate: bool = False,
    missing_field_mapping: bool = False,
    with_temporal_policy: bool = False,
) -> OntologySnapshot:
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
    segment = Property(
        uri="https://example.invalid/ontology/Segment",
        short_name="Segment",
        label="客户分群",
        labels=_text("客户分群"),
        concept_uri=customer.uri,
        datatype_uri=XSD_STRING,
    )
    accounting_month = Property(
        uri="https://example.invalid/ontology/AccountingMonth",
        short_name="AccountingMonth",
        label="业务账期",
        labels=_text("业务账期"),
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
        PhysicalMapping(
            uri="https://example.invalid/ontology/SegmentField",
            short_name="SegmentField",
            label="分群字段映射",
            labels=_text("分群字段映射"),
            semantic_element_uri=segment.uri,
            data_source_uri=source.uri,
            field_name="segment_code",
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
    temporal_policies = ()
    if with_temporal_policy:
        mappings.append(
            PhysicalMapping(
                uri="https://example.invalid/ontology/AccountingMonthField",
                short_name="AccountingMonthField",
                label="业务账期字段映射",
                labels=_text("业务账期字段映射"),
                semantic_element_uri=accounting_month.uri,
                data_source_uri=source.uri,
                field_name="accounting_month",
            )
        )
        temporal_policies = (
            TemporalPartitionPolicy(
                uri="https://example.invalid/ontology/CustomerMonthPolicy",
                short_name="CustomerMonthPolicy",
                label="客户月分区策略",
                labels=_text("客户月分区策略"),
                applies_to_uri=customer.uri,
                partition_property_uri=accounting_month.uri,
                grain=TemporalGrain.MONTH,
                default_strategy=TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH,
            ),
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
            properties=(customer_id, segment, status, accounting_month),
            rules=(rule,),
            data_sources=(source,),
            mappings=tuple(mappings),
            temporal_policies=temporal_policies,
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
    assert first.evidence.mappings == (
        "CustomerTable",
        "CustomerIdField",
        "StatusField",
    )
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


def test_shadow_outputs_bounded_temporal_evidence() -> None:
    service = OntologyShadowService(runtime=_StaticRuntime(_snapshot(with_temporal_policy=True)))

    result = service.preview(
        "查询客户编号",
        "SELECT legacy_one FROM old_table;",
        system_time="2026-08-24",
    )

    assert result.status == "generated"
    assert "\"accounting_month\" = '202607'" in (result.ontology_sql or "")
    assert len(result.temporal_decisions) == 1
    decision = result.temporal_decisions[0]
    assert decision.partition_field == "accounting_month"
    assert decision.source == "ontology_default"
    assert decision.resolved_start == "202607"
    assert decision.safety_status == "bounded"


def test_shadow_requests_clarification_for_unsafe_time_scope() -> None:
    service = OntologyShadowService(runtime=_StaticRuntime(_snapshot(with_temporal_policy=True)))

    conflict = service.preview(
        "查询2026年5月和2026年6月客户编号",
        "SELECT 1;",
        system_time="2026-08-24",
    )
    unbounded = service.preview(
        "查询全部历史客户编号",
        "SELECT 1;",
        system_time="2026-08-24",
    )

    assert conflict.status == "clarification_required"
    assert unbounded.status == "clarification_required"
    assert conflict.ontology_sql is None and unbounded.ontology_sql is None
    assert "确认" in conflict.summary
    assert "明确" in unbounded.summary


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


def test_runtime_install_is_prevalidated_assignment_and_reports_health() -> None:
    runtime = OntologyRuntime()

    assert runtime.health().status == "degraded"
    with pytest.raises(TypeError, match="snapshot must be OntologySnapshot"):
        runtime.install(object())  # type: ignore[arg-type]

    snapshot = _snapshot()
    runtime.install(snapshot)

    assert runtime.snapshot() is snapshot
    assert runtime.health().status == "ok"
    assert runtime.health().sha256 == snapshot.info.sha256


def test_shadow_service_uses_the_process_wide_runtime(monkeypatch) -> None:
    get_ontology_runtime.cache_clear()
    _configured_service.cache_clear()
    monkeypatch.setattr("agent.ontology_shadow.settings.ontology.package_path", "")

    runtime = get_ontology_runtime()
    service = get_ontology_shadow_service()

    assert service._runtime is runtime
    _configured_service.cache_clear()
    get_ontology_runtime.cache_clear()
