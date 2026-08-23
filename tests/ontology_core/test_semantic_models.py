import pytest
from pydantic import ValidationError

from ontology_core import Concept, SemanticCatalog
from ontology_core.errors import (
    AmbiguousIdentifierError,
    ConceptNotFoundError,
    InvalidOntologyReferenceError,
    InvalidRuleExpressionError,
    PropertyNotFoundError,
)
from ontology_core.semantic_models import (
    BusinessRule,
    DataSource,
    LocalizedText,
    PhysicalMapping,
    Property,
    RdfLiteral,
    Relation,
    RuleExpression,
    RuleOperator,
)
from ontology_core.vocabulary import CONCEPT, OA, SHORT_NAME


def test_concept_and_catalog_are_immutable() -> None:
    concept = Concept(
        uri="https://example.invalid/domain/Record",
        short_name="Record",
        label="Record",
        labels=(LocalizedText(value="Record", language="en"),),
        parent_uris=(),
        child_uris=(),
    )
    catalog = SemanticCatalog(concepts=(concept,))

    with pytest.raises(ValidationError):
        concept.short_name = "Changed"
    with pytest.raises(ValidationError):
        catalog.concepts = ()


def test_semantic_collections_coerce_to_tuples_and_preserve_input_order() -> None:
    first = Concept(
        uri="https://example.invalid/domain/First",
        short_name="First",
        label="First",
        labels=[{"value": "First", "language": "en"}],
        parent_uris=["urn:parent"],
        child_uris=["urn:child"],
    )
    second = Concept(
        uri="https://example.invalid/domain/Second",
        short_name="Second",
        label="Second",
        labels=[{"value": "Second", "language": "en"}],
    )
    catalog = SemanticCatalog(concepts=[first, second])

    assert first.labels == (LocalizedText(value="First", language="en"),)
    assert first.parent_uris == ("urn:parent",)
    assert first.child_uris == ("urn:child",)
    assert catalog.concepts == (first, second)


def test_rule_expression_uses_typed_recursive_children() -> None:
    expression = RuleExpression(
        operator=RuleOperator.ALL_OF,
        children=(RuleExpression(operator=RuleOperator.IS_NULL, property_uri="urn:p"),),
    )

    assert expression.children[0].operator is RuleOperator.IS_NULL


def test_semantic_dtos_accept_their_public_contract_fields() -> None:
    property_ = Property(
        uri="urn:property",
        short_name="field_name",
        label="Field name",
        labels=(),
        concept_uri="urn:concept",
        datatype_uri="urn:datatype",
    )
    relation = Relation(
        uri="urn:relation",
        short_name="related_to",
        label="Related to",
        labels=(),
        source_concept_uri="urn:concept",
        target_concept_uri="urn:target",
    )
    rule = BusinessRule(
        uri="urn:rule",
        short_name="check_record",
        label="Check record",
        labels=(),
        applies_to_uri="urn:concept",
        property_uris=[property_.uri],
        relation_uris=[relation.uri],
        condition=RuleExpression(
            operator=RuleOperator.EQ,
            property_uri=property_.uri,
            values=[RdfLiteral(lexical_form="neutral")],
        ),
    )
    data_source = DataSource(
        uri="urn:source",
        short_name="source",
        label="Source",
        labels=(),
        platform_type="neutral",
        capabilities=["read"],
    )
    mapping = PhysicalMapping(
        uri="urn:mapping",
        short_name="mapping",
        label="Mapping",
        labels=(),
        semantic_element_uri=property_.uri,
        data_source_uri=data_source.uri,
        join_path=["urn:join"],
    )

    assert rule.property_uris == (property_.uri,)
    assert rule.condition is not None
    assert rule.condition.values == (RdfLiteral(lexical_form="neutral"),)
    assert data_source.capabilities == ("read",)
    assert mapping.join_path == ("urn:join",)


def test_vocabulary_uses_the_fixed_namespace_and_terms() -> None:
    assert str(OA) == "urn:ontology-agent:core#"
    assert OA.Concept == CONCEPT
    assert OA.shortName == SHORT_NAME


def test_semantic_lookup_errors_have_stable_codes() -> None:
    assert ConceptNotFoundError.code == "concept_not_found"
    assert PropertyNotFoundError.code == "property_not_found"
    assert AmbiguousIdentifierError.code == "ambiguous_identifier"
    assert InvalidRuleExpressionError.code == "invalid_rule_expression"
    assert InvalidOntologyReferenceError.code == "invalid_ontology_reference"
