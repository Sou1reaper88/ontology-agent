"""Application-level partition conventions, independent of immutable RDF files."""

from __future__ import annotations

import hashlib
from collections import defaultdict

from ontology_core.semantic_models import (
    SemanticCatalog,
    TemporalDefaultStrategy,
    TemporalGrain,
    TemporalPartitionPolicy,
)


def partition_convention(
    name: str,
) -> tuple[str, TemporalGrain, TemporalDefaultStrategy] | None:
    """Return the physical field, grain and default for a recognized table suffix."""
    if name.upper().endswith("_D"):
        return "P_DAY", TemporalGrain.DAY, TemporalDefaultStrategy.T_MINUS_2
    if name.upper().endswith("_M"):
        return "P_MON", TemporalGrain.MONTH, TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH
    return None


def catalog_partition_rules(catalog: SemanticCatalog):
    """Resolve conventions through enabled physical mappings; never invent fields."""
    mappings = defaultdict(list)
    properties = defaultdict(list)
    for mapping in catalog.mappings:
        if mapping.enabled:
            mappings[mapping.semantic_element_uri].append(mapping)
    for property_ in catalog.properties:
        properties[property_.concept_uri].append(property_)
    rules = {}
    for concept in catalog.concepts:
        objects = sorted(
            (m for m in mappings[concept.uri] if m.object_name),
            key=lambda m: (-m.priority, m.uri),
        )
        if not objects:
            continue
        object_ = objects[0]
        convention = partition_convention(object_.object_name)
        if convention is None:
            continue
        field_name, grain, strategy = convention
        matches = []
        for property_ in properties[concept.uri]:
            fields = sorted(
                (
                    m
                    for m in mappings[property_.uri]
                    if m.field_name and m.data_source_uri == object_.data_source_uri
                ),
                key=lambda m: (-m.priority, m.uri),
            )
            if fields and fields[0].field_name.upper() == field_name:
                matches.append(property_.uri)
        rules[concept.uri] = (object_.object_name, field_name, grain, strategy, matches)
    return rules


def with_automatic_temporal_policies(catalog: SemanticCatalog) -> SemanticCatalog:
    """Derive effective policies without changing the package bytes or content digest.

    Legacy policies for non-conventional names remain readable. For _D/_M names,
    old manual overrides cannot disable the convention or select another field.
    Missing/ambiguous fields deliberately leave no usable policy.
    """
    rules = catalog_partition_rules(catalog)
    policies = [p for p in catalog.temporal_policies if p.applies_to_uri not in rules]
    for concept_uri, (name, _, grain, strategy, matches) in rules.items():
        if len(matches) != 1:
            continue
        existing = next(
            (
                p
                for p in catalog.temporal_policies
                if p.applies_to_uri == concept_uri and p.partition_property_uri == matches[0]
            ),
            None,
        )
        values = {
            "applies_to_uri": concept_uri,
            "partition_property_uri": matches[0],
            "grain": grain,
            "default_strategy": strategy,
            "allow_query_override": True,
            "status": "active",
            "priority": 100,
        }
        if existing:
            policy = existing.model_copy(update=values)
        else:
            identity = hashlib.sha256(concept_uri.encode()).hexdigest()
            policy = TemporalPartitionPolicy(
                uri=f"urn:ontology-agent:automatic-temporal:{identity}",
                short_name=f"AutomaticTemporal_{identity}",
                label=f"{name} 自动账期",
                labels=(),
                **values,
            )
        policies.append(policy)
    return catalog.model_copy(update={"temporal_policies": tuple(policies)})
