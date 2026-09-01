from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ontology_core.models import PackageInfo
from ontology_core.program_models import (
    DraftProgramStep,
    DraftSqlProgramPlan,
    IntentSpec,
    ProgramStepKind,
    ResultShapeSpec,
    StepSourceBinding,
    TimeIntentSpec,
)
from ontology_core.program_validation import (
    OntologyProgramBinder,
    ProgramDiagnosticCode,
)
from ontology_core.repository import OntologySnapshot
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


def _snapshot(
    *,
    include_order: bool = False,
    include_relation: bool = True,
    duplicate_entity: bool = False,
    temporal: bool = False,
) -> OntologySnapshot:
    customer = Concept(
        uri="https://example.invalid/Customer",
        short_name="Customer",
        label="客户",
        labels=_text("客户"),
    )
    concepts = [customer]
    customer_id = Property(
        uri="https://example.invalid/CustomerId",
        short_name="CustomerId",
        label="客户编号",
        labels=_text("客户编号"),
        concept_uri=customer.uri,
        datatype_uri="http://www.w3.org/2001/XMLSchema#string",
    )
    accounting_month = Property(
        uri="https://example.invalid/AccountingMonth",
        short_name="AccountingMonth",
        label="业务账期",
        labels=_text("业务账期"),
        concept_uri=customer.uri,
        datatype_uri="http://www.w3.org/2001/XMLSchema#string",
    )
    properties = [customer_id, accounting_month]
    source = DataSource(
        uri="https://example.invalid/Hive",
        short_name="Hive",
        label="Hive 数仓",
        labels=_text("Hive 数仓"),
        platform_type="hive",
        dialect="hive",
    )
    mappings = [
        PhysicalMapping(
            uri="https://example.invalid/CustomerTable",
            short_name="CustomerTable",
            label="客户表",
            labels=_text("客户表"),
            semantic_element_uri=customer.uri,
            data_source_uri=source.uri,
            physical_namespace="dm",
            object_name="customer",
        ),
        PhysicalMapping(
            uri="https://example.invalid/CustomerIdField",
            short_name="CustomerIdField",
            label="客户编号字段",
            labels=_text("客户编号字段"),
            semantic_element_uri=customer_id.uri,
            data_source_uri=source.uri,
            field_name="customer_id",
        ),
        PhysicalMapping(
            uri="https://example.invalid/AccountingMonthField",
            short_name="AccountingMonthField",
            label="账期字段",
            labels=_text("账期字段"),
            semantic_element_uri=accounting_month.uri,
            data_source_uri=source.uri,
            field_name="p_mon",
        ),
    ]
    relations: list[Relation] = []
    if include_order:
        order = Concept(
            uri="https://example.invalid/Order",
            short_name="Order",
            label="订单",
            labels=_text("订单"),
        )
        order_id = Property(
            uri="https://example.invalid/OrderId",
            short_name="OrderId",
            label="订单编号",
            labels=_text("订单编号"),
            concept_uri=order.uri,
            datatype_uri="http://www.w3.org/2001/XMLSchema#string",
        )
        order_customer_id = Property(
            uri="https://example.invalid/OrderCustomerId",
            short_name="OrderCustomerId",
            label="订单客户编号",
            labels=_text("订单客户编号"),
            concept_uri=order.uri,
            datatype_uri="http://www.w3.org/2001/XMLSchema#string",
        )
        concepts.append(order)
        properties.extend((order_id, order_customer_id))
        mappings.extend(
            (
                PhysicalMapping(
                    uri="https://example.invalid/OrderTable",
                    short_name="OrderTable",
                    label="订单表",
                    labels=_text("订单表"),
                    semantic_element_uri=order.uri,
                    data_source_uri=source.uri,
                    physical_namespace="dm",
                    object_name="orders",
                ),
                PhysicalMapping(
                    uri="https://example.invalid/OrderIdField",
                    short_name="OrderIdField",
                    label="订单编号字段",
                    labels=_text("订单编号字段"),
                    semantic_element_uri=order_id.uri,
                    data_source_uri=source.uri,
                    field_name="order_id",
                ),
                PhysicalMapping(
                    uri="https://example.invalid/OrderCustomerIdField",
                    short_name="OrderCustomerIdField",
                    label="订单客户编号字段",
                    labels=_text("订单客户编号字段"),
                    semantic_element_uri=order_customer_id.uri,
                    data_source_uri=source.uri,
                    field_name="customer_id",
                ),
            )
        )
        if include_relation:
            relations.append(
                Relation(
                    uri="https://example.invalid/CustomerOrders",
                    short_name="CustomerOrders",
                    label="客户订单关系",
                    labels=_text("客户订单关系"),
                    source_concept_uri=customer.uri,
                    target_concept_uri=order.uri,
                    source_property_uri=customer_id.uri,
                    target_property_uri=order_customer_id.uri,
                    confirmed=True,
                    priority=10,
                )
            )
    if duplicate_entity:
        concepts.extend(
            (
                Concept(
                    uri="https://example.invalid/EntityA",
                    short_name="Entity",
                    label="实体甲",
                    labels=_text("实体甲"),
                ),
                Concept(
                    uri="https://example.invalid/EntityB",
                    short_name="Entity",
                    label="实体乙",
                    labels=_text("实体乙"),
                ),
            )
        )
    policies = ()
    if temporal:
        policies = (
            TemporalPartitionPolicy(
                uri="https://example.invalid/CustomerMonthPolicy",
                short_name="CustomerMonthPolicy",
                label="客户月分区策略",
                labels=_text("客户月分区策略"),
                applies_to_uri=customer.uri,
                partition_property_uri=accounting_month.uri,
                grain=TemporalGrain.MONTH,
                default_strategy=TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH,
            ),
        )
    return OntologySnapshot(
        info=PackageInfo(
            package_id="example.program",
            version="1.0.0",
            sha256="a" * 64,
            loaded_at=datetime.now(UTC),
            source="https://example.invalid/package",
        ),
        catalog=SemanticCatalog(
            concepts=tuple(concepts),
            properties=tuple(properties),
            relations=tuple(relations),
            data_sources=(source,),
            mappings=tuple(mappings),
            temporal_policies=policies,
        ),
        _data_nt="",
        _shapes_nt="",
    )


def _intent(
    *,
    concepts: tuple[str, ...] = ("Customer",),
    properties: tuple[str, ...] = ("CustomerId",),
    time_expression: str | None = None,
) -> IntentSpec:
    return IntentSpec(
        normalized_request="生成结果",
        business_concepts=concepts,
        requested_properties=properties,
        time_intent=TimeIntentSpec(
            source="user" if time_expression else "default",
            expression=time_expression,
            grain="month" if time_expression else None,
            requires_default=time_expression is None,
        ),
        result_shape=ResultShapeSpec(),
    )


def _step(
    step_id: str,
    kind: ProgramStepKind,
    *,
    objects: tuple[str, ...] = ("Customer",),
    properties: tuple[str, ...] = ("CustomerId",),
    dependencies: tuple[str | None, ...] | None = None,
) -> DraftProgramStep:
    dependencies = dependencies or (None,) * len(objects)
    return DraftProgramStep(
        step_id=step_id,
        kind=kind,
        purpose=f"生成 {step_id}",
        source_objects=objects,
        source_bindings=tuple(
            StepSourceBinding(object_ref=object_ref, source_step_id=dependency)
            for object_ref, dependency in zip(objects, dependencies, strict=True)
        ),
        requested_properties=properties,
    )


def _bind(draft: DraftSqlProgramPlan, snapshot: OntologySnapshot):
    return OntologyProgramBinder().bind(
        draft,
        program_id="a1b2c3d4e5f6",
        system_time=datetime(2026, 8, 24, tzinfo=UTC),
        snapshot=snapshot,
    )


def test_binder_orders_linear_dependencies() -> None:
    draft = DraftSqlProgramPlan(
        intent=_intent(),
        steps=(
            _step("base", ProgramStepKind.INTERMEDIATE),
            _step("result", ProgramStepKind.RESULT, dependencies=("base",)),
        ),
    )

    outcome = _bind(draft, _snapshot())

    assert outcome.plan is not None
    assert tuple(item.step_id for item in outcome.plan.steps) == ("base", "result")
    assert outcome.plan.result_step_id == "result"
    assert outcome.plan.package_sha256 == "a" * 64


def test_binder_preserves_original_order_for_fan_in_dependencies() -> None:
    draft = DraftSqlProgramPlan(
        intent=_intent(
            concepts=("Customer", "Order"),
            properties=("CustomerId", "OrderId"),
        ),
        steps=(
            _step(
                "orders",
                ProgramStepKind.INTERMEDIATE,
                objects=("Order",),
                properties=("OrderId",),
            ),
            _step("customers", ProgramStepKind.INTERMEDIATE),
            _step(
                "result",
                ProgramStepKind.RESULT,
                objects=("Customer", "Order"),
                properties=("CustomerId", "OrderId"),
                dependencies=("customers", "orders"),
            ),
        ),
    )

    outcome = _bind(draft, _snapshot(include_order=True))

    assert outcome.plan is not None
    assert tuple(item.step_id for item in outcome.plan.steps) == (
        "orders",
        "customers",
        "result",
    )
    assert len(outcome.plan.steps[-1].query_plan.joins) == 1


@pytest.mark.parametrize("shape", ("unknown", "cycle", "multiple_results", "nonterminal"))
def test_binder_classifies_invalid_dependency_shapes_as_repairable(shape: str) -> None:
    if shape == "unknown":
        steps = (_step("result", ProgramStepKind.RESULT, dependencies=("missing",)),)
    elif shape == "cycle":
        steps = (
            _step("base", ProgramStepKind.INTERMEDIATE, dependencies=("result",)),
            _step("result", ProgramStepKind.RESULT, dependencies=("base",)),
        )
    elif shape == "multiple_results":
        steps = (
            _step("first", ProgramStepKind.RESULT),
            _step("second", ProgramStepKind.RESULT),
        )
    else:
        steps = (
            _step("result", ProgramStepKind.RESULT),
            _step("later", ProgramStepKind.INTERMEDIATE, dependencies=("result",)),
        )
    draft = DraftSqlProgramPlan.model_construct(intent=_intent(), steps=steps)

    outcome = _bind(draft, _snapshot())

    assert outcome.plan is None
    assert outcome.should_repair is True
    assert outcome.should_clarify is False
    assert outcome.diagnostics[0].code == ProgramDiagnosticCode.REPAIRABLE_REFERENCE


def test_binder_classifies_ambiguous_concept_as_clarification() -> None:
    draft = DraftSqlProgramPlan(
        intent=_intent(concepts=("Entity",), properties=("CustomerId",)),
        steps=(
            _step(
                "result",
                ProgramStepKind.RESULT,
                objects=("Entity",),
                properties=("CustomerId",),
            ),
        ),
    )

    outcome = _bind(draft, _snapshot(duplicate_entity=True))

    assert outcome.plan is None
    assert outcome.should_clarify is True
    assert outcome.should_repair is False
    assert outcome.diagnostics[0].code == ProgramDiagnosticCode.AMBIGUOUS_BUSINESS_TERM


def test_binder_classifies_missing_join_as_unsupported() -> None:
    draft = DraftSqlProgramPlan(
        intent=_intent(
            concepts=("Customer", "Order"),
            properties=("CustomerId", "OrderId"),
        ),
        steps=(
            _step(
                "result",
                ProgramStepKind.RESULT,
                objects=("Customer", "Order"),
                properties=("CustomerId", "OrderId"),
            ),
        ),
    )

    outcome = _bind(draft, _snapshot(include_order=True, include_relation=False))

    assert outcome.plan is None
    assert outcome.should_clarify is False
    assert outcome.should_repair is False
    assert outcome.diagnostics[0].code == ProgramDiagnosticCode.UNSUPPORTED_PLAN


def test_binder_preserves_explicit_time_over_default_policy() -> None:
    draft = DraftSqlProgramPlan(
        intent=_intent(time_expression="2026年5月"),
        steps=(_step("result", ProgramStepKind.RESULT),),
    )

    outcome = _bind(draft, _snapshot(temporal=True))

    assert outcome.plan is not None
    decision = outcome.plan.steps[0].query_plan.temporal_decisions[0]
    assert decision.resolved_start == "202605"
    assert decision.resolved_end == "202605"
    assert decision.matched_text == "2026年5月"


def test_binder_requires_clarification_for_declared_intent_ambiguity() -> None:
    draft = DraftSqlProgramPlan(
        intent=_intent().model_copy(update={"ambiguities": ("用户口径存在冲突",)}),
        steps=(_step("result", ProgramStepKind.RESULT),),
    )

    outcome = _bind(draft, _snapshot())

    assert outcome.plan is None
    assert outcome.should_clarify is True
    assert outcome.diagnostics[0].code == ProgramDiagnosticCode.AMBIGUOUS_BUSINESS_TERM


def test_binder_rejects_result_shape_that_query_plan_cannot_represent() -> None:
    draft = DraftSqlProgramPlan(
        intent=_intent().model_copy(
            update={"result_shape": ResultShapeSpec(distinct=True)}
        ),
        steps=(_step("result", ProgramStepKind.RESULT),),
    )

    outcome = _bind(draft, _snapshot())

    assert outcome.plan is None
    assert outcome.should_repair is False
    assert outcome.should_clarify is False
    assert outcome.diagnostics[0].code == ProgramDiagnosticCode.UNSUPPORTED_PLAN
