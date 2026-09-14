from __future__ import annotations

from enum import StrEnum
from typing import Literal

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


class TemporalGrain(StrEnum):
    DAY = "day"
    MONTH = "month"


def validate_predicate_shape(operator, children, has_operand, values):
    if operator in {RuleOperator.ALL_OF, RuleOperator.ANY_OF, RuleOperator.NOT}:
        expected = 1 if operator == RuleOperator.NOT else 2
        if has_operand or values or len(children) < expected or (operator == RuleOperator.NOT and len(children) != 1):
            raise ValueError("布尔条件必须只携带合法数量的子条件：NOT 一个，AND/OR 至少两个")
    elif not has_operand or children:
        raise ValueError("比较条件必须引用字段且不能携带子条件")


def predicate_leaves(predicate):
    if predicate.children:
        for child in predicate.children:
            yield from predicate_leaves(child)
    else:
        yield predicate


class TemporalDefaultStrategy(StrEnum):
    T_MINUS_2 = "t_minus_2"
    PREVIOUS_COMPLETE_MONTH = "previous_complete_month"


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
    source_property_uri: str | None = None
    target_property_uri: str | None = None
    cardinality: str | None = None
    status: str = "active"
    priority: int = 0
    confirmed: bool = False


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


class TemporalPartitionPolicy(SemanticElement):
    applies_to_uri: str
    partition_property_uri: str
    grain: TemporalGrain
    default_strategy: TemporalDefaultStrategy
    allow_query_override: bool = True
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
    temporal_policies: tuple[TemporalPartitionPolicy, ...] = ()


class SemanticCounts(FrozenModel):
    concepts: int = 0
    properties: int = 0
    relations: int = 0
    rules: int = 0
    data_sources: int = 0
    mappings: int = 0
    temporal_policies: int = 0


class InspectedPackage(FrozenModel):
    package_id: str
    version: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PackageInspection(FrozenModel):
    status: Literal["valid"] = "valid"
    package: InspectedPackage
    counts: SemanticCounts
    identifiers: tuple[str, ...] | None = None
