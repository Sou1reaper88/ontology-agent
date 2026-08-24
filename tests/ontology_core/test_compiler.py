from __future__ import annotations

import pytest

from ontology_core.compiler import CompilerRegistry, GenericSqlCompiler
from ontology_core.errors import OntologyCompileError
from ontology_core.query_plan import BoundProperty, QueryPlan
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
)

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
        concept=concept,
        data_source=source,
        object_binding=object_mapping,
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


def test_generic_compiler_uses_only_query_plan_bindings() -> None:
    compiled = GenericSqlCompiler().compile(_plan(_leaf(RuleOperator.EQ, "ACTIVE")))

    assert compiled.sql == (
        'SELECT "customer_id" FROM "analytics"."customer_snapshot" '
        "WHERE \"status_code\" = 'ACTIVE';"
    )
    assert compiled.tables == ("analytics.customer_snapshot",)
    assert compiled.fields == ("customer_id",)


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
