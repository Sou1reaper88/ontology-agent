from __future__ import annotations

from datetime import date

from ontology_core.models import FrozenModel
from ontology_core.semantic_models import (
    BusinessRule,
    Concept,
    DataSource,
    PhysicalMapping,
    Property,
    RdfLiteral,
    RuleOperator,
    TemporalDefaultStrategy,
    TemporalGrain,
    TemporalPartitionPolicy,
)
from ontology_core.temporal import TemporalIntentSource


class BoundProperty(FrozenModel):
    semantic: Property
    binding: PhysicalMapping


class ResolvedFilter(FrozenModel):
    property: BoundProperty
    operator: RuleOperator
    values: tuple[RdfLiteral, ...]
    source: str
    explanation: str


class TemporalDecision(FrozenModel):
    partition_property_uri: str
    grain: TemporalGrain
    source: TemporalIntentSource
    system_date: date
    resolved_start: str
    resolved_end: str
    default_strategy: TemporalDefaultStrategy
    explanation: str
    matched_text: str | None = None


class QueryPlan(FrozenModel):
    concept: Concept
    data_source: DataSource
    object_binding: PhysicalMapping
    selections: tuple[BoundProperty, ...]
    property_bindings: tuple[BoundProperty, ...]
    rules: tuple[BusinessRule, ...] = ()
    filters: tuple[ResolvedFilter, ...] = ()
    temporal_policy: TemporalPartitionPolicy | None = None
    temporal_decision: TemporalDecision | None = None


class CompiledQuery(FrozenModel):
    sql: str
    tables: tuple[str, ...]
    fields: tuple[str, ...]
    predicates: tuple[str, ...] = ()
