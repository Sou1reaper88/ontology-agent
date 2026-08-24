from __future__ import annotations

from ontology_core.models import FrozenModel
from ontology_core.semantic_models import (
    BusinessRule,
    Concept,
    DataSource,
    PhysicalMapping,
    Property,
)


class BoundProperty(FrozenModel):
    semantic: Property
    binding: PhysicalMapping


class QueryPlan(FrozenModel):
    concept: Concept
    data_source: DataSource
    object_binding: PhysicalMapping
    selections: tuple[BoundProperty, ...]
    property_bindings: tuple[BoundProperty, ...]
    rules: tuple[BusinessRule, ...] = ()
