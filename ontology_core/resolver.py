from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterable
from types import MappingProxyType
from typing import TypeVar

from ontology_core.errors import (
    AmbiguousIdentifierError,
    ConceptNotFoundError,
    PropertyNotFoundError,
)
from ontology_core.repository import OntologySnapshot
from ontology_core.semantic_models import (
    BusinessRule,
    Concept,
    Property,
    Relation,
    SemanticElement,
)

_Element = TypeVar("_Element", bound=SemanticElement)


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _sort_key(element: SemanticElement) -> tuple[str, str]:
    return (_normalize(element.short_name), element.uri)


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
        self._concepts = tuple(sorted(catalog.concepts, key=_sort_key))
        self._concepts_by_uri = _index(self._concepts, lambda concept: concept.uri)
        self._concepts_by_short_name = _index(
            self._concepts,
            lambda concept: _normalize(concept.short_name),
        )
        self._concepts_by_label = _index(
            self._concepts,
            lambda concept: _normalize(concept.label),
        )
        self._properties_by_concept = _index(
            catalog.properties,
            lambda property_: property_.concept_uri,
        )
        self._relations_by_source = _index(
            catalog.relations,
            lambda relation: relation.source_concept_uri,
        )
        self._rules_by_concept = _index(
            catalog.rules,
            lambda rule: rule.applies_to_uri,
        )

    def list_concepts(self) -> tuple[Concept, ...]:
        return self._concepts

    def get_concept(self, identifier: str) -> Concept:
        uri_matches = self._concepts_by_uri.get(identifier.strip(), ())
        if uri_matches:
            return uri_matches[0]

        normalized = _normalize(identifier)
        short_name_matches = self._concepts_by_short_name.get(normalized, ())
        if short_name_matches:
            return short_name_matches[0]

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
        normalized = _normalize(text)
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

        normalized = _normalize(property_id)
        short_name_matches = tuple(
            property_ for property_ in properties if _normalize(property_.short_name) == normalized
        )
        if short_name_matches:
            return short_name_matches[0]
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

    def list_rules(self, concept_id: str) -> tuple[BusinessRule, ...]:
        concept = self.get_concept(concept_id)
        return self._rules_by_concept.get(concept.uri, ())

    @staticmethod
    def _concept_rank(concept: Concept, normalized: str) -> int | None:
        if normalized in {_normalize(concept.uri), _normalize(concept.short_name)}:
            return 0
        if normalized == _normalize(concept.label):
            return 1
        if _normalize(concept.short_name).startswith(normalized):
            return 2
        if normalized in _normalize(concept.label):
            return 3
        if concept.description is not None and normalized in _normalize(concept.description):
            return 4
        return None
