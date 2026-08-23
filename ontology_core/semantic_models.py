from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from ontology_core.models import FrozenModel


class RuleOperator(StrEnum):
    ALL_OF = "all_of"
    ANY_OF = "any_of"
    NOT = "not"
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    BETWEEN = "between"
    IS_NULL = "is_null"


class LocalizedText(FrozenModel):
    value: str = Field(min_length=1)
    language: str | None = None


class RdfLiteral(FrozenModel):
    lexical_form: str
    datatype_uri: str | None = None
    language: str | None = None


class SemanticElement(FrozenModel):
    uri: str = Field(min_length=1)
    short_name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9._-]*$")
    label: str = Field(min_length=1)
    labels: tuple[LocalizedText, ...]
    description: str | None = None


class Concept(SemanticElement):
    parent_uris: tuple[str, ...] = ()
    child_uris: tuple[str, ...] = ()


class Property(SemanticElement):
    concept_uri: str
    datatype_uri: str


class Relation(SemanticElement):
    source_concept_uri: str
    target_concept_uri: str


class RuleExpression(FrozenModel):
    operator: RuleOperator
    children: tuple[RuleExpression, ...] = ()
    property_uri: str | None = None
    values: tuple[RdfLiteral, ...] = ()
    parameter: str | None = None


class BusinessRule(SemanticElement):
    applies_to_uri: str
    property_uris: tuple[str, ...] = ()
    relation_uris: tuple[str, ...] = ()
    condition: RuleExpression | None = None
    status: str = "active"
    priority: int = 0


class DataSource(SemanticElement):
    platform_type: str
    dialect: str | None = None
    capabilities: tuple[str, ...] = ()


class PhysicalMapping(SemanticElement):
    semantic_element_uri: str
    data_source_uri: str
    physical_namespace: str | None = None
    object_name: str | None = None
    field_name: str | None = None
    join_path: tuple[str, ...] = ()
    priority: int = 0
    enabled: bool = True


class SemanticCatalog(FrozenModel):
    concepts: tuple[Concept, ...] = ()
    properties: tuple[Property, ...] = ()
    relations: tuple[Relation, ...] = ()
    rules: tuple[BusinessRule, ...] = ()
    data_sources: tuple[DataSource, ...] = ()
    mappings: tuple[PhysicalMapping, ...] = ()
