from __future__ import annotations

from collections.abc import Callable, Iterable
from types import MappingProxyType
from typing import TypeVar

from ontology_core.errors import (
    AmbiguousIdentifierError,
    ConceptNotFoundError,
    PropertyNotFoundError,
    TemporalIntentError,
)
from ontology_core.normalization import normalize_text
from ontology_core.repository import OntologySnapshot
from ontology_core.semantic_models import (
    BusinessRule,
    Concept,
    DataSource,
    PhysicalMapping,
    Property,
    Relation,
    SemanticElement,
    TemporalPartitionPolicy,
)
from ontology_core.temporal_conventions import catalog_partition_rules

_Element = TypeVar("_Element", bound=SemanticElement)


def _sort_key(element: SemanticElement) -> tuple[str, str]:
    return (normalize_text(element.short_name), element.uri)


def _index(
    elements: Iterable[_Element],
    key: Callable[[_Element], str],
) -> MappingProxyType[str, tuple[_Element, ...]]:
    grouped: dict[str, list[_Element]] = {}
    for element in elements:
        grouped.setdefault(key(element), []).append(element)
    return MappingProxyType(
        {index_key: tuple(sorted(items, key=_sort_key)) for index_key, items in grouped.items()}
    )


class OntologyResolver:
    """Read-only deterministic lookup service for one published ontology snapshot."""

    def __init__(self, snapshot: OntologySnapshot) -> None:
        catalog = snapshot.catalog
        self._partition_rules = catalog_partition_rules(catalog)
        self._concepts = tuple(sorted(catalog.concepts, key=_sort_key))
        self._concepts_by_uri = _index(self._concepts, lambda concept: concept.uri)
        self._concepts_by_short_name = _index(
            self._concepts,
            lambda concept: normalize_text(concept.short_name),
        )
        self._concepts_by_label = _index(
            self._concepts,
            lambda concept: normalize_text(concept.label),
        )
        self._properties_by_concept = _index(
            catalog.properties,
            lambda property_: property_.concept_uri,
        )
        self._relations_by_source = _index(
            catalog.relations,
            lambda relation: relation.source_concept_uri,
        )
        grouped_relations: dict[tuple[str, str], list[Relation]] = {}
        for relation in catalog.relations:
            key = tuple(sorted((relation.source_concept_uri, relation.target_concept_uri)))
            grouped_relations.setdefault(key, []).append(relation)
        self._relations_by_pair = MappingProxyType(
            {
                key: tuple(sorted(items, key=lambda item: (-item.priority, item.uri)))
                for key, items in grouped_relations.items()
            }
        )
        self._rules_by_concept = _index(
            catalog.rules,
            lambda rule: rule.applies_to_uri,
        )
        self._temporal_policies_by_concept = _index(
            catalog.temporal_policies,
            lambda policy: policy.applies_to_uri,
        )
        self._data_sources = tuple(sorted(catalog.data_sources, key=_sort_key))
        grouped_mappings: dict[str, list[PhysicalMapping]] = {}
        for mapping in catalog.mappings:
            if mapping.enabled:
                grouped_mappings.setdefault(mapping.semantic_element_uri, []).append(mapping)
        self._mappings_by_element = MappingProxyType(
            {
                element_uri: tuple(
                    sorted(
                        mappings,
                        key=lambda item: (-item.priority, *_sort_key(item)),
                    )
                )
                for element_uri, mappings in grouped_mappings.items()
            }
        )

    def list_concepts(self) -> tuple[Concept, ...]:
        return self._concepts

    def get_concept(self, identifier: str) -> Concept:
        uri_matches = self._concepts_by_uri.get(identifier.strip(), ())
        if uri_matches:
            return uri_matches[0]

        normalized = normalize_text(identifier)
        short_name_matches = self._concepts_by_short_name.get(normalized, ())
        if len(short_name_matches) == 1:
            return short_name_matches[0]
        if short_name_matches:
            raise AmbiguousIdentifierError(
                "本体概念标识符存在歧义",
                details={
                    "identifier": identifier,
                    "candidates": sorted(item.uri for item in short_name_matches),
                },
            )

        label_matches = self._concepts_by_label.get(normalized, ())
        if len(label_matches) == 1:
            return label_matches[0]
        if label_matches:
            raise AmbiguousIdentifierError(
                "本体概念标识符存在歧义",
                details={
                    "identifier": identifier,
                    "candidates": sorted(item.uri for item in label_matches),
                },
            )
        raise ConceptNotFoundError(
            "未找到本体概念",
            details={"identifier": identifier},
        )

    def search_concepts(self, text: str) -> tuple[Concept, ...]:
        normalized = normalize_text(text)
        if not normalized:
            return ()

        ranked: list[tuple[int, Concept]] = []
        for concept in self._concepts:
            rank = self._concept_rank(concept, normalized)
            if rank is not None:
                ranked.append((rank, concept))
        ranked.sort(key=lambda item: (item[0], *_sort_key(item[1])))
        return tuple(item[1] for item in ranked)

    def list_properties(self, concept_id: str) -> tuple[Property, ...]:
        concept = self.get_concept(concept_id)
        return self._properties_by_concept.get(concept.uri, ())

    def resolve_property(self, concept_id: str, property_id: str) -> Property:
        properties = self.list_properties(concept_id)
        uri_matches = tuple(
            property_ for property_ in properties if property_.uri == property_id.strip()
        )
        if uri_matches:
            return uri_matches[0]

        normalized = normalize_text(property_id)
        short_name_matches = tuple(
            property_
            for property_ in properties
            if normalize_text(property_.short_name) == normalized
        )
        if len(short_name_matches) == 1:
            return short_name_matches[0]
        if short_name_matches:
            raise AmbiguousIdentifierError(
                "本体属性标识符存在歧义",
                details={
                    "identifier": property_id,
                    "candidates": sorted(item.uri for item in short_name_matches),
                },
            )
        raise PropertyNotFoundError(
            "未找到本体属性",
            details={
                "concept_id": concept_id,
                "property_id": property_id,
            },
        )

    def list_relations(self, concept_id: str) -> tuple[Relation, ...]:
        concept = self.get_concept(concept_id)
        return self._relations_by_source.get(concept.uri, ())

    def resolve_direct_relation(self, left_concept_id: str, right_concept_id: str) -> Relation:
        left = self.get_concept(left_concept_id)
        right = self.get_concept(right_concept_id)
        candidates = tuple(
            item
            for item in self._relations_by_pair.get(tuple(sorted((left.uri, right.uri))), ())
            if item.status == "active"
            and item.confirmed
            and item.source_property_uri is not None
            and item.target_property_uri is not None
        )
        if not candidates:
            raise ConceptNotFoundError(
                "未找到已确认的直接关系",
                details={"concepts": tuple(sorted((left.uri, right.uri)))},
            )
        highest_priority = candidates[0].priority
        winners = tuple(item for item in candidates if item.priority == highest_priority)
        if len(winners) != 1:
            raise AmbiguousIdentifierError(
                "直接关系存在歧义",
                details={"candidates": tuple(sorted(item.uri for item in winners))},
            )
        relation = winners[0]
        key_uris = (relation.source_property_uri, relation.target_property_uri)
        if any(
            not any(mapping.field_name for mapping in self.list_mappings(property_uri))
            for property_uri in key_uris
        ):
            raise PropertyNotFoundError(
                "直接关系缺少可用的关联键映射",
                details={"relation": relation.uri},
            )
        return relation

    def list_rules(self, concept_id: str) -> tuple[BusinessRule, ...]:
        concept = self.get_concept(concept_id)
        return self._rules_by_concept.get(concept.uri, ())

    def get_temporal_policy(self, concept_id: str) -> TemporalPartitionPolicy | None:
        concept = self.get_concept(concept_id)
        rule = self._partition_rules.get(concept.uri)
        if rule is not None and len(rule[4]) != 1:
            raise TemporalIntentError(
                f"表 {rule[0]} 缺少唯一启用的 {rule[1]} 分区字段，请补充字段定义",
                details={"reason": "automatic_partition_field_missing"},
            )
        active = tuple(
            item
            for item in self._temporal_policies_by_concept.get(concept.uri, ())
            if item.status == "active"
        )
        return active[0] if active else None

    def list_data_sources(self) -> tuple[DataSource, ...]:
        return self._data_sources

    def list_mappings(
        self,
        semantic_element_uri: str,
        data_source_uri: str | None = None,
    ) -> tuple[PhysicalMapping, ...]:
        mappings = self._mappings_by_element.get(semantic_element_uri.strip(), ())
        if data_source_uri is None:
            return mappings
        source_uri = data_source_uri.strip()
        return tuple(item for item in mappings if item.data_source_uri == source_uri)

    @staticmethod
    def _concept_rank(concept: Concept, normalized: str) -> int | None:
        if normalized in {normalize_text(concept.uri), normalize_text(concept.short_name)}:
            return 0
        if normalized == normalize_text(concept.label):
            return 1
        if normalize_text(concept.short_name).startswith(normalized):
            return 2
        if normalized in normalize_text(concept.label):
            return 3
        if concept.description is not None and normalized in normalize_text(concept.description):
            return 4
        return None
