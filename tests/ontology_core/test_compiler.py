from __future__ import annotations

from datetime import date

import pytest

from ontology_core.compiler import CompilerRegistry, GenericSqlCompiler
from ontology_core.errors import OntologyCompileError
from ontology_core.query_plan import (
    BoundObject,
    BoundProperty,
    QueryPlan,
    ResolvedFilter,
    ResolvedJoin,
    TemporalDecision,
)
from ontology_core.semantic_models import (
    BusinessRule,
    Concept,
    DataSource,
    LocalizedText,
    PhysicalMapping,
    Property,
    RdfLiteral,
    Relation,
    RuleExpression,
    RuleOperator,
    TemporalDefaultStrategy,
    TemporalGrain,
    TemporalPartitionPolicy,
)
from ontology_core.temporal import TemporalIntentSource

XSD = "http://www.w3.org/2001/XMLSchema#"


def _text(value: str) -> tuple[LocalizedText, ...]:
    return (LocalizedText(value=value, language="en"),)


def _plan(
    condition: RuleExpression | None = None, *, object_name: str = "customer_snapshot"
) -> QueryPlan:
    concept = Concept(
        uri="https://example.invalid/ontology/Customer",
        short_name="Customer",
        label="Customer",
        labels=_text("Customer"),
    )
    customer_id = Property(
        uri="https://example.invalid/ontology/CustomerId",
        short_name="CustomerId",
        label="Customer ID",
        labels=_text("Customer ID"),
        concept_uri=concept.uri,
        datatype_uri=f"{XSD}string",
    )
    status = Property(
        uri="https://example.invalid/ontology/Status",
        short_name="Status",
        label="Status",
        labels=_text("Status"),
        concept_uri=concept.uri,
        datatype_uri=f"{XSD}string",
    )
    source = DataSource(
        uri="https://example.invalid/ontology/Warehouse",
        short_name="Warehouse",
        label="Warehouse",
        labels=_text("Warehouse"),
        platform_type="generic",
        dialect="generic",
    )
    object_mapping = PhysicalMapping(
        uri="https://example.invalid/ontology/CustomerTable",
        short_name="CustomerTable",
        label="Customer table",
        labels=_text("Customer table"),
        semantic_element_uri=concept.uri,
        data_source_uri=source.uri,
        physical_namespace="analytics",
        object_name=object_name,
    )

    def bound(property_: Property, field_name: str) -> BoundProperty:
        return BoundProperty(
            semantic=property_,
            binding=PhysicalMapping(
                uri=f"https://example.invalid/ontology/{property_.short_name}Field",
                short_name=f"{property_.short_name}Field",
                label=f"{property_.label} field",
                labels=_text(f"{property_.label} field"),
                semantic_element_uri=property_.uri,
                data_source_uri=source.uri,
                field_name=field_name,
            ),
            object_alias="t0",
        )

    id_binding = bound(customer_id, "customer_id")
    status_binding = bound(status, "status_code")
    rules = ()
    if condition is not None:
        rules = (
            BusinessRule(
                uri="https://example.invalid/ontology/ActiveCustomerRule",
                short_name="ActiveCustomerRule",
                label="Active customer",
                labels=_text("Active customer"),
                applies_to_uri=concept.uri,
                property_uris=(status.uri,),
                condition=condition,
                status="active",
            ),
        )
    return QueryPlan(
        concepts=(concept,),
        data_source=source,
        objects=(BoundObject(alias="t0", semantic=concept, binding=object_mapping),),
        selections=(id_binding,),
        property_bindings=(id_binding, status_binding),
        rules=rules,
    )


def _leaf(
    operator: RuleOperator,
    *values: str,
    datatype: str | None = f"{XSD}string",
) -> RuleExpression:
    return RuleExpression(
        operator=operator,
        property_uri="https://example.invalid/ontology/Status",
        values=tuple(RdfLiteral(lexical_form=value, datatype_uri=datatype) for value in values),
    )


def _temporal_plan(
    start: str = "202607",
    end: str = "202607",
    *,
    include_policy: bool = True,
    include_decision: bool = True,
    property_uri: str = "https://example.invalid/ontology/AccountingMonth",
) -> QueryPlan:
    plan = _plan()
    month = Property(
        uri=property_uri,
        short_name="AccountingMonth",
        label="Accounting month",
        labels=_text("Accounting month"),
        concept_uri=plan.concept.uri,
        datatype_uri=f"{XSD}string",
    )
    month_binding = BoundProperty(
        semantic=month,
        binding=PhysicalMapping(
            uri="https://example.invalid/ontology/AccountingMonthField",
            short_name="AccountingMonthField",
            label="Accounting month field",
            labels=_text("Accounting month field"),
            semantic_element_uri=month.uri,
            data_source_uri=plan.data_source.uri,
            field_name="accounting_month",
        ),
        object_alias="t0",
    )
    operator = RuleOperator.EQ if start == end else RuleOperator.BETWEEN
    values = (start,) if start == end else (start, end)
    policy = TemporalPartitionPolicy(
        uri="https://example.invalid/ontology/MonthlyPolicy",
        short_name="MonthlyPolicy",
        label="Monthly policy",
        labels=_text("Monthly policy"),
        applies_to_uri=plan.concept.uri,
        partition_property_uri="https://example.invalid/ontology/AccountingMonth",
        grain=TemporalGrain.MONTH,
        default_strategy=TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH,
    )
    decision = TemporalDecision(
        partition_property_uri=policy.partition_property_uri,
        grain=TemporalGrain.MONTH,
        source=TemporalIntentSource.ONTOLOGY_DEFAULT,
        system_date=date(2026, 8, 24),
        resolved_start=start,
        resolved_end=end,
        default_strategy=TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH,
        explanation="默认取上一个完整自然月",
    )
    return plan.model_copy(
        update={
            "property_bindings": (*plan.property_bindings, month_binding),
            "filters": (
                ResolvedFilter(
                    property=month_binding,
                    operator=operator,
                    values=tuple(
                        RdfLiteral(lexical_form=value, datatype_uri=f"{XSD}string")
                        for value in values
                    ),
                    source="ontology_default",
                    explanation="默认取上一个完整自然月",
                ),
            ),
            "temporal_policies": (policy,) if include_policy else (),
            "temporal_decisions": (decision,) if include_decision else (),
        }
    )


def test_generic_compiler_compiles_resolved_temporal_filters() -> None:
    single = GenericSqlCompiler().compile(_temporal_plan())
    ranged = GenericSqlCompiler().compile(_temporal_plan("202604", "202606"))

    assert "\"accounting_month\" = '202607'" in single.sql
    assert "\"accounting_month\" BETWEEN '202604' AND '202606'" in ranged.sql
    assert single.fields == ("customer_id",)


def test_generic_compiler_joins_rules_and_resolved_filters() -> None:
    plan = _temporal_plan().model_copy(
        update={"rules": _plan(_leaf(RuleOperator.EQ, "ACTIVE")).rules}
    )

    compiled = GenericSqlCompiler().compile(plan)

    assert "\"status_code\" = 'ACTIVE' AND \"accounting_month\" = '202607'" in compiled.sql


def test_compiler_rejects_incomplete_temporal_guard() -> None:
    with pytest.raises(OntologyCompileError, match="缺少时间决策"):
        GenericSqlCompiler().compile(_temporal_plan(include_decision=False))

    wrong_filter = _temporal_plan(property_uri="https://example.invalid/ontology/OtherMonth")
    with pytest.raises(OntologyCompileError, match="缺少有界分区过滤"):
        GenericSqlCompiler().compile(wrong_filter)


def test_generic_compiler_uses_only_query_plan_bindings() -> None:
    compiled = GenericSqlCompiler().compile(_plan(_leaf(RuleOperator.EQ, "ACTIVE")))

    assert compiled.sql == (
        'SELECT "customer_id" FROM "analytics"."customer_snapshot" '
        "WHERE \"status_code\" = 'ACTIVE';"
    )
    assert compiled.tables == ("analytics.customer_snapshot",)
    assert compiled.fields == ("customer_id",)


def test_generic_compiler_compiles_structured_two_object_inner_join() -> None:
    single = _plan()
    customer = single.concepts[0]
    customer_id = single.selections[0].model_copy(update={"object_alias": "t0"})
    order = Concept(
        uri="https://example.invalid/ontology/Order",
        short_name="Order",
        label="Order",
        labels=_text("Order"),
    )
    amount = Property(
        uri=f"{order.uri}/Amount",
        short_name="Amount",
        label="Amount",
        labels=_text("Amount"),
        concept_uri=order.uri,
        datatype_uri=f"{XSD}decimal",
    )
    order_customer_id = Property(
        uri=f"{order.uri}/CustomerId",
        short_name="OrderCustomerId",
        label="Order customer ID",
        labels=_text("Order customer ID"),
        concept_uri=order.uri,
        datatype_uri=f"{XSD}string",
    )

    def order_bound(property_: Property, field: str) -> BoundProperty:
        return BoundProperty(
            semantic=property_,
            binding=PhysicalMapping(
                uri=f"{property_.uri}/Mapping",
                short_name=f"{property_.short_name}Mapping",
                label="Order field mapping",
                labels=_text("Order field mapping"),
                semantic_element_uri=property_.uri,
                data_source_uri=single.data_source.uri,
                field_name=field,
            ),
            object_alias="t1",
        )

    amount_binding = order_bound(amount, "order_amount")
    order_key = order_bound(order_customer_id, "customer_id")
    relation = Relation(
        uri="https://example.invalid/ontology/CustomerOrder",
        short_name="CustomerOrder",
        label="Customer orders",
        labels=_text("Customer orders"),
        source_concept_uri=customer.uri,
        target_concept_uri=order.uri,
        source_property_uri=customer_id.semantic.uri,
        target_property_uri=order_customer_id.uri,
        confirmed=True,
    )
    order_object = PhysicalMapping(
        uri=f"{order.uri}/Mapping",
        short_name="OrderTable",
        label="Order table",
        labels=_text("Order table"),
        semantic_element_uri=order.uri,
        data_source_uri=single.data_source.uri,
        physical_namespace="analytics",
        object_name="order_detail",
    )
    plan = QueryPlan(
        concepts=(customer, order),
        data_source=single.data_source,
        objects=(
            BoundObject(alias="t0", semantic=customer, binding=single.objects[0].binding),
            BoundObject(alias="t1", semantic=order, binding=order_object),
        ),
        selections=(customer_id, amount_binding),
        property_bindings=(customer_id, amount_binding, order_key),
        joins=(ResolvedJoin(relation=relation, left=customer_id, right=order_key),),
    )

    compiled = GenericSqlCompiler().compile(plan)

    assert compiled.sql == (
        'SELECT "t0"."customer_id", "t1"."order_amount" '
        'FROM "analytics"."customer_snapshot" AS "t0" '
        'INNER JOIN "analytics"."order_detail" AS "t1" '
        'ON "t0"."customer_id" = "t1"."customer_id";'
    )
    assert compiled.tables == ("analytics.customer_snapshot", "analytics.order_detail")


def test_query_plan_rejects_two_objects_without_one_join() -> None:
    plan = _plan()
    second_concept = plan.concepts[0].model_copy(
        update={
            "uri": "https://example.invalid/ontology/Second",
            "short_name": "Second",
        }
    )
    second = BoundObject(
        alias="t1",
        semantic=second_concept,
        binding=plan.objects[0].binding.model_copy(
            update={
                "semantic_element_uri": second_concept.uri,
                "object_name": "second_table",
            }
        ),
    )

    with pytest.raises(ValueError, match="双对象查询必须包含一条关系"):
        QueryPlan(
            concepts=(plan.concepts[0], second_concept),
            data_source=plan.data_source,
            objects=(plan.objects[0], second),
            selections=plan.selections,
            property_bindings=plan.property_bindings,
        )
@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        (_leaf(RuleOperator.NE, "A"), "\"status_code\" <> 'A'"),
        (_leaf(RuleOperator.GT, "1", datatype=f"{XSD}integer"), '"status_code" > 1'),
        (_leaf(RuleOperator.GTE, "1", datatype=f"{XSD}integer"), '"status_code" >= 1'),
        (_leaf(RuleOperator.LT, "2", datatype=f"{XSD}integer"), '"status_code" < 2'),
        (_leaf(RuleOperator.LTE, "2", datatype=f"{XSD}integer"), '"status_code" <= 2'),
        (_leaf(RuleOperator.IN, "A", "B"), "\"status_code\" IN ('A', 'B')"),
        (_leaf(RuleOperator.BETWEEN, "A", "Z"), "\"status_code\" BETWEEN 'A' AND 'Z'"),
        (_leaf(RuleOperator.IS_NULL), '"status_code" IS NULL'),
    ],
)
def test_generic_compiler_supports_leaf_operators(
    condition: RuleExpression,
    expected: str,
) -> None:
    assert expected in GenericSqlCompiler().compile(_plan(condition)).sql


def test_generic_compiler_supports_logical_operators_and_escapes_literals() -> None:
    equals = _leaf(RuleOperator.EQ, "O'Reilly")
    missing = _leaf(RuleOperator.IS_NULL)
    condition = RuleExpression(
        operator=RuleOperator.ALL_OF,
        children=(
            RuleExpression(operator=RuleOperator.ANY_OF, children=(equals, missing)),
            RuleExpression(operator=RuleOperator.NOT, children=(missing,)),
        ),
    )

    sql = GenericSqlCompiler().compile(_plan(condition)).sql

    assert "'O''Reilly'" in sql
    assert " OR " in sql
    assert " AND " in sql
    assert "NOT (" in sql


def test_compiler_fails_closed_for_unknown_dialect_identifier_and_binding() -> None:
    with pytest.raises(OntologyCompileError):
        CompilerRegistry.default().get("unknown")
    with pytest.raises(OntologyCompileError):
        GenericSqlCompiler().compile(_plan(object_name="unsafe-name"))

    condition = RuleExpression(
        operator=RuleOperator.EQ,
        property_uri="https://example.invalid/ontology/Unbound",
        values=(RdfLiteral(lexical_form="A", datatype_uri=f"{XSD}string"),),
    )
    with pytest.raises(OntologyCompileError):
        GenericSqlCompiler().compile(_plan(condition))


def test_compiler_fails_closed_for_unsupported_literal_datatype() -> None:
    condition = _leaf(
        RuleOperator.EQ,
        "value",
        datatype="https://example.invalid/datatype/Custom",
    )
    with pytest.raises(OntologyCompileError):
        GenericSqlCompiler().compile(_plan(condition))
