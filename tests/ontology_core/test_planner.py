from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ontology_core.compiler import GenericSqlCompiler
from ontology_core.errors import (
    AmbiguousQueryConceptError,
    NoMatchingConceptError,
    TemporalIntentError,
    UnsupportedQueryPlanError,
)
from ontology_core.models import PackageInfo
from ontology_core.planner import OntologyPlanner
from ontology_core.repository import OntologySnapshot
from ontology_core.resolver import OntologyResolver
from ontology_core.semantic_models import (
    Concept,
    DataSource,
    LocalizedText,
    PhysicalMapping,
    Property,
    Relation,
    SemanticCatalog,
    TemporalDefaultStrategy,
    TemporalGrain,
    TemporalPartitionPolicy,
)


def _text(value: str) -> tuple[LocalizedText, ...]:
    return (LocalizedText(value=value, language="zh-CN"),)


def _resolver(
    *,
    duplicate: bool = False,
    missing_property_mapping: bool = False,
    with_temporal_policy: bool = False,
    missing_partition_mapping: bool = False,
    missing_business_date_mapping: bool = False,
) -> OntologyResolver:
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
                uri="https://example.invalid/ontology/CustomerDuplicate",
                short_name="CustomerDuplicate",
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
        datatype_uri="http://www.w3.org/2001/XMLSchema#string",
    )
    status = Property(
        uri="https://example.invalid/ontology/Status",
        short_name="Status",
        label="客户状态",
        labels=_text("客户状态"),
        concept_uri=customer.uri,
        datatype_uri="http://www.w3.org/2001/XMLSchema#string",
    )
    accounting_month = Property(
        uri="https://example.invalid/ontology/AccountingMonth",
        short_name="AccountingMonth",
        label="业务账期",
        labels=_text("业务账期"),
        concept_uri=customer.uri,
        datatype_uri="http://www.w3.org/2001/XMLSchema#string",
    )
    registration_date = Property(
        uri="https://example.invalid/ontology/RegistrationDate",
        short_name="RegistrationDate",
        label="入网日期",
        labels=_text("入网日期"),
        concept_uri=customer.uri,
        datatype_uri="http://www.w3.org/2001/XMLSchema#date",
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
            priority=10,
        ),
        PhysicalMapping(
            uri="https://example.invalid/ontology/StatusField",
            short_name="StatusField",
            label="状态字段映射",
            labels=_text("状态字段映射"),
            semantic_element_uri=status.uri,
            data_source_uri=source.uri,
            field_name="status_code",
            priority=10,
        ),
    ]
    if not missing_property_mapping:
        mappings.append(
            PhysicalMapping(
                uri="https://example.invalid/ontology/CustomerIdField",
                short_name="CustomerIdField",
                label="客户编号字段映射",
                labels=_text("客户编号字段映射"),
                semantic_element_uri=customer_id.uri,
                data_source_uri=source.uri,
                field_name="customer_id",
                priority=20,
            )
        )
    if with_temporal_policy and not missing_partition_mapping:
        mappings.append(
            PhysicalMapping(
                uri="https://example.invalid/ontology/AccountingMonthField",
                short_name="AccountingMonthField",
                label="业务账期字段映射",
                labels=_text("业务账期字段映射"),
                semantic_element_uri=accounting_month.uri,
                data_source_uri=source.uri,
                field_name="p_mon",
                priority=20,
            )
        )
    if not missing_business_date_mapping:
        mappings.append(
            PhysicalMapping(
                uri="https://example.invalid/ontology/RegistrationDateField",
                short_name="RegistrationDateField",
                label="入网日期字段映射",
                labels=_text("入网日期字段映射"),
                semantic_element_uri=registration_date.uri,
                data_source_uri=source.uri,
                field_name="registration_date",
                priority=20,
            )
        )
    temporal_policies = ()
    if with_temporal_policy:
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
    snapshot = OntologySnapshot(
        info=PackageInfo(
            package_id="example.planner",
            version="1.0.0",
            sha256="0" * 64,
            loaded_at=datetime.now(UTC),
            source="https://example.invalid/package",
        ),
        catalog=SemanticCatalog(
            concepts=tuple(concepts),
            properties=(customer_id, status, accounting_month, registration_date),
            data_sources=(source,),
            mappings=tuple(mappings),
            temporal_policies=temporal_policies,
        ),
        _data_nt="",
        _shapes_nt="",
    )
    return OntologyResolver(snapshot)


def _property_inference_resolver(*, shared_label: bool = False) -> OntologyResolver:
    user = Concept(
        uri="https://example.invalid/ontology/UserEntity",
        short_name="UserEntity",
        label="用户实体",
        labels=_text("用户实体"),
    )
    order = Concept(
        uri="https://example.invalid/ontology/OrderEntity",
        short_name="OrderEntity",
        label="订单实体",
        labels=_text("订单实体"),
    )
    user_code = Property(
        uri="https://example.invalid/ontology/UserCode",
        short_name="UserCode",
        label="客户编码",
        labels=_text("客户编码"),
        concept_uri=user.uri,
        datatype_uri="http://www.w3.org/2001/XMLSchema#string",
    )
    user_status = Property(
        uri="https://example.invalid/ontology/UserStatus",
        short_name="UserStatus",
        label="状态编码" if shared_label else "用户状态",
        labels=_text("状态编码" if shared_label else "用户状态"),
        concept_uri=user.uri,
        datatype_uri="http://www.w3.org/2001/XMLSchema#string",
    )
    order_code = Property(
        uri="https://example.invalid/ontology/OrderCode",
        short_name="OrderCode",
        label="状态编码" if shared_label else "订单编码",
        labels=_text("状态编码" if shared_label else "订单编码"),
        concept_uri=order.uri,
        datatype_uri="http://www.w3.org/2001/XMLSchema#string",
    )
    source = DataSource(
        uri="https://example.invalid/ontology/Warehouse",
        short_name="Warehouse",
        label="合成仓库",
        labels=_text("合成仓库"),
        platform_type="generic",
        dialect="generic",
    )
    mappings = []
    for concept, object_name in ((user, "user_entity"), (order, "order_entity")):
        mappings.append(
            PhysicalMapping(
                uri=f"{concept.uri}Mapping",
                short_name=f"{concept.short_name}Mapping",
                label=f"{concept.label}映射",
                labels=_text(f"{concept.label}映射"),
                semantic_element_uri=concept.uri,
                data_source_uri=source.uri,
                physical_namespace="synthetic",
                object_name=object_name,
            )
        )
    for property_, field_name in (
        (user_code, "user_code"),
        (user_status, "user_status"),
        (order_code, "order_code"),
    ):
        mappings.append(
            PhysicalMapping(
                uri=f"{property_.uri}Mapping",
                short_name=f"{property_.short_name}Mapping",
                label=f"{property_.label}映射",
                labels=_text(f"{property_.label}映射"),
                semantic_element_uri=property_.uri,
                data_source_uri=source.uri,
                field_name=field_name,
            )
        )
    snapshot = OntologySnapshot(
        info=PackageInfo(
            package_id="example.property-inference",
            version="1.0.0",
            sha256="1" * 64,
            loaded_at=datetime.now(UTC),
            source="https://example.invalid/package",
        ),
        catalog=SemanticCatalog(
            concepts=(user, order),
            properties=(user_code, user_status, order_code),
            data_sources=(source,),
            mappings=tuple(mappings),
        ),
        _data_nt="",
        _shapes_nt="",
    )
    return OntologyResolver(snapshot)


def _join_resolver(*, include_relation: bool = True) -> OntologyResolver:
    customer = Concept(
        uri="https://example.invalid/ontology/CustomerJoin",
        short_name="CustomerJoin",
        label="客户",
        labels=_text("客户"),
    )
    order = Concept(
        uri="https://example.invalid/ontology/OrderJoin",
        short_name="OrderJoin",
        label="订单",
        labels=_text("订单"),
    )
    customer_id = Property(
        uri=f"{customer.uri}/CustomerId",
        short_name="CustomerId",
        label="客户编号",
        labels=_text("客户编号"),
        concept_uri=customer.uri,
        datatype_uri="http://www.w3.org/2001/XMLSchema#string",
    )
    order_customer_id = Property(
        uri=f"{order.uri}/CustomerId",
        short_name="OrderCustomerId",
        label="订单客户编号",
        labels=_text("订单客户编号"),
        concept_uri=order.uri,
        datatype_uri="http://www.w3.org/2001/XMLSchema#string",
    )
    amount = Property(
        uri=f"{order.uri}/Amount",
        short_name="OrderAmount",
        label="订单金额",
        labels=_text("订单金额"),
        concept_uri=order.uri,
        datatype_uri="http://www.w3.org/2001/XMLSchema#decimal",
    )
    p_mon = Property(
        uri=f"{customer.uri}/Month",
        short_name="CustomerMonth",
        label="客户月分区",
        labels=_text("客户月分区"),
        concept_uri=customer.uri,
        datatype_uri="http://www.w3.org/2001/XMLSchema#string",
    )
    p_day = Property(
        uri=f"{order.uri}/Day",
        short_name="OrderDay",
        label="订单日分区",
        labels=_text("订单日分区"),
        concept_uri=order.uri,
        datatype_uri="http://www.w3.org/2001/XMLSchema#string",
    )
    source = DataSource(
        uri="https://example.invalid/ontology/JoinWarehouse",
        short_name="JoinWarehouse",
        label="关联仓库",
        labels=_text("关联仓库"),
        platform_type="generic",
        dialect="generic",
    )
    properties = (customer_id, order_customer_id, amount, p_mon, p_day)
    mappings = [
        PhysicalMapping(
            uri=f"{concept.uri}/Mapping",
            short_name=f"{concept.short_name}Table",
            label="对象映射",
            labels=_text("对象映射"),
            semantic_element_uri=concept.uri,
            data_source_uri=source.uri,
            physical_namespace="analytics",
            object_name=table,
        )
        for concept, table in ((customer, "customer_m"), (order, "order_d"))
    ]
    for property_, field in zip(
        properties,
        ("customer_id", "customer_id", "order_amount", "p_mon", "p_day"),
        strict=True,
    ):
        mappings.append(
            PhysicalMapping(
                uri=f"{property_.uri}/Mapping",
                short_name=f"{property_.short_name}Field",
                label="字段映射",
                labels=_text("字段映射"),
                semantic_element_uri=property_.uri,
                data_source_uri=source.uri,
                field_name=field,
            )
        )
    relations = (
        Relation(
            uri="https://example.invalid/ontology/CustomerOrderJoin",
            short_name="CustomerOrderJoin",
            label="客户订单关系",
            labels=_text("客户订单关系"),
            source_concept_uri=customer.uri,
            target_concept_uri=order.uri,
            source_property_uri=customer_id.uri,
            target_property_uri=order_customer_id.uri,
            confirmed=True,
            priority=100,
        ),
    ) if include_relation else ()
    policies = (
        TemporalPartitionPolicy(
            uri=f"{customer.uri}/Policy",
            short_name="CustomerMonthPolicy",
            label="客户月策略",
            labels=_text("客户月策略"),
            applies_to_uri=customer.uri,
            partition_property_uri=p_mon.uri,
            grain=TemporalGrain.MONTH,
            default_strategy=TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH,
        ),
        TemporalPartitionPolicy(
            uri=f"{order.uri}/Policy",
            short_name="OrderDayPolicy",
            label="订单日策略",
            labels=_text("订单日策略"),
            applies_to_uri=order.uri,
            partition_property_uri=p_day.uri,
            grain=TemporalGrain.DAY,
            default_strategy=TemporalDefaultStrategy.T_MINUS_2,
        ),
    )
    snapshot = OntologySnapshot(
        info=PackageInfo(
            package_id="example.join-planner",
            version="1.0.0",
            sha256="2" * 64,
            loaded_at=datetime.now(UTC),
            source="https://example.invalid/package",
        ),
        catalog=SemanticCatalog(
            concepts=(customer, order),
            properties=properties,
            relations=relations,
            data_sources=(source,),
            mappings=tuple(mappings),
            temporal_policies=policies,
        ),
        _data_nt="",
        _shapes_nt="",
    )
    return OntologyResolver(snapshot)


def test_planner_builds_single_concept_plan_from_labels_and_mappings() -> None:
    plan = OntologyPlanner(_resolver()).plan("查询客户编号")

    assert plan.concept.short_name == "Customer"
    assert plan.data_source.short_name == "Warehouse"
    assert plan.object_binding.object_name == "customer_snapshot"
    assert tuple(item.semantic.short_name for item in plan.selections) == ("CustomerId",)
    assert plan.selections[0].binding.field_name == "customer_id"


def test_planner_builds_bounded_direct_two_concept_plan() -> None:
    plan = OntologyPlanner(_join_resolver()).plan(
        "查询客户编号和订单金额",
        system_time="2026-08-24",
    )
    compiled = GenericSqlCompiler().compile(plan)

    assert tuple(item.short_name for item in plan.concepts) == ("CustomerJoin", "OrderJoin")
    assert tuple(item.semantic.short_name for item in plan.selections) == (
        "CustomerId",
        "OrderAmount",
    )
    assert tuple(item.resolved_start for item in plan.temporal_decisions) == (
        "202607",
        "20260822",
    )
    assert len(plan.joins) == 1
    assert 'INNER JOIN "analytics"."order_d" AS "t1"' in compiled.sql
    assert '"t0"."p_mon" = \'202607\'' in compiled.sql
    assert '"t1"."p_day" = \'20260822\'' in compiled.sql


def test_planner_rejects_two_concepts_without_confirmed_relation() -> None:
    with pytest.raises(UnsupportedQueryPlanError, match="直接关系"):
        OntologyPlanner(_join_resolver(include_relation=False)).plan(
            "查询客户编号和订单金额",
            system_time="2026-08-24",
        )


def test_planner_rejects_no_match_ambiguity_and_missing_mapping() -> None:
    with pytest.raises(NoMatchingConceptError):
        OntologyPlanner(_resolver()).plan("查询完全无关对象")
    with pytest.raises(AmbiguousQueryConceptError):
        OntologyPlanner(_resolver(duplicate=True)).plan("查询客户")
    with pytest.raises(UnsupportedQueryPlanError):
        OntologyPlanner(_resolver(missing_property_mapping=True)).plan("查询客户编号")


def test_planner_infers_unique_concept_from_multiple_property_labels() -> None:
    plan = OntologyPlanner(_property_inference_resolver()).plan("查询客户编码和用户状态")

    assert plan.concept.short_name == "UserEntity"
    assert tuple(item.semantic.short_name for item in plan.selections) == (
        "UserCode",
        "UserStatus",
    )


def test_planner_rejects_property_inference_tie_between_concepts() -> None:
    with pytest.raises(AmbiguousQueryConceptError) as exc_info:
        OntologyPlanner(_property_inference_resolver(shared_label=True)).plan("查询状态编码")

    assert exc_info.value.details == {"candidates": ("OrderEntity", "UserEntity")}


def test_planner_rejects_direct_concept_match_without_known_property() -> None:
    with pytest.raises(UnsupportedQueryPlanError, match="未匹配到查询属性"):
        OntologyPlanner(_resolver()).plan("查询客户的火星指标")


@pytest.mark.parametrize(
    ("query", "expected_predicate", "expected_source"),
    (
        ("查询客户编号", "\"p_mon\" = '202607'", "ontology_default"),
        ("查询2026年6月客户编号", "\"p_mon\" = '202606'", "explicit_absolute"),
        (
            "查询2026年4月至2026年6月客户编号",
            "\"p_mon\" BETWEEN '202604' AND '202606'",
            "explicit_absolute",
        ),
        ("查询最近3个月客户编号", "\"p_mon\" BETWEEN '202605' AND '202607'", "explicit_relative"),
    ),
)
def test_planner_applies_ontology_temporal_policy(
    query: str,
    expected_predicate: str,
    expected_source: str,
) -> None:
    plan = OntologyPlanner(_resolver(with_temporal_policy=True)).plan(
        query,
        system_time="2026-08-24",
    )
    compiled = GenericSqlCompiler().compile(plan)

    assert expected_predicate in compiled.sql
    assert tuple(item.binding.field_name for item in plan.selections) == ("customer_id",)
    assert plan.temporal_decision is not None
    assert plan.temporal_decision.source == expected_source


def test_planner_temporal_policy_fails_closed() -> None:
    planner = OntologyPlanner(_resolver(with_temporal_policy=True))

    with pytest.raises(TemporalIntentError, match="多个冲突账期"):
        planner.plan("查询2026年5月和2026年6月客户编号", system_time="2026-08-24")
    with pytest.raises(TemporalIntentError, match="明确账期"):
        planner.plan("查询全部历史客户编号", system_time="2026-08-24")
    with pytest.raises(TemporalIntentError, match="系统时间格式无效"):
        planner.plan("查询客户编号", system_time="20260824")
    with pytest.raises(UnsupportedQueryPlanError, match="分区属性缺少可用的字段映射"):
        OntologyPlanner(_resolver(with_temporal_policy=True, missing_partition_mapping=True)).plan(
            "查询客户编号", system_time="2026-08-24"
        )

    with pytest.raises(UnsupportedQueryPlanError, match="查询属性缺少可用的字段映射"):
        OntologyPlanner(
            _resolver(with_temporal_policy=True, missing_business_date_mapping=True)
        ).plan("查询2026年6月入网日期的客户编号", system_time="2026-08-24")


def test_planner_keeps_default_partition_with_business_date_filter() -> None:
    plan = OntologyPlanner(_resolver(with_temporal_policy=True)).plan(
        "查询2026年6月入网日期的客户编号",
        system_time="2026-08-24",
    )
    compiled = GenericSqlCompiler().compile(plan)

    assert "\"p_mon\" = '202607'" in compiled.sql
    assert "\"registration_date\" BETWEEN '2026-06-01' AND '2026-06-30'" in compiled.sql


def test_planner_without_temporal_policy_preserves_legacy_plan() -> None:
    plan = OntologyPlanner(_resolver()).plan("查询客户编号", system_time="2026-08-24")

    assert plan.filters == ()
    assert plan.temporal_policy is None
    assert plan.temporal_decision is None
