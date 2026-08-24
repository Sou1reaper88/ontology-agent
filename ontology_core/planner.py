from __future__ import annotations

from collections.abc import Iterable

from ontology_core.errors import (
    AmbiguousQueryConceptError,
    NoMatchingConceptError,
    UnsupportedQueryPlanError,
)
from ontology_core.normalization import normalize_text
from ontology_core.query_plan import (
    BoundProperty,
    QueryPlan,
    ResolvedFilter,
    TemporalDecision,
)
from ontology_core.resolver import OntologyResolver
from ontology_core.semantic_models import (
    Concept,
    Property,
    RdfLiteral,
    RuleOperator,
    SemanticElement,
)
from ontology_core.temporal import (
    TemporalIntent,
    TemporalTarget,
    parse_system_date,
    parse_temporal_intents,
)

_XSD_DATE = "http://www.w3.org/2001/XMLSchema#date"


def _aliases(element: SemanticElement) -> tuple[str, ...]:
    values = {element.short_name, element.label, *(item.value for item in element.labels)}
    return tuple(sorted({normalize_text(value) for value in values if normalize_text(value)}))


def _match_score(query: str, element: SemanticElement) -> int | None:
    matches = [len(alias) for alias in _aliases(element) if alias in query]
    return max(matches) if matches else None


def _target(property_: Property) -> TemporalTarget:
    return TemporalTarget(
        property_uri=property_.uri,
        aliases=_aliases(property_),
        datatype_uri=property_.datatype_uri,
    )


def _could_be_business_date(property_: Property) -> bool:
    aliases = _aliases(property_)
    return property_.datatype_uri == _XSD_DATE or any(
        marker in alias for alias in aliases for marker in ("日期", "时间")
    )


def _resolved_filter(intent: TemporalIntent, binding: BoundProperty) -> ResolvedFilter:
    operator = RuleOperator.EQ if intent.start == intent.end else RuleOperator.BETWEEN
    values = (intent.start,) if operator is RuleOperator.EQ else (intent.start, intent.end)
    return ResolvedFilter(
        property=binding,
        operator=operator,
        values=tuple(
            RdfLiteral(
                lexical_form=value,
                datatype_uri=binding.semantic.datatype_uri,
            )
            for value in values
        ),
        source=intent.source.value,
        explanation=intent.explanation,
    )


def _best_concept(query: str, concepts: Iterable[Concept]) -> Concept:
    ranked = [
        (score, concept)
        for concept in concepts
        if (score := _match_score(query, concept)) is not None
    ]
    if not ranked:
        raise NoMatchingConceptError("未匹配到本体概念")
    best_score = max(score for score, _ in ranked)
    winners = sorted(
        (concept for score, concept in ranked if score == best_score),
        key=lambda item: item.uri,
    )
    if len(winners) != 1:
        raise AmbiguousQueryConceptError(
            "本体概念匹配存在歧义",
            details={"candidates": tuple(item.short_name for item in winners)},
        )
    return winners[0]


def _infer_concept_from_properties(
    query: str,
    resolver: OntologyResolver,
    concepts: Iterable[Concept],
) -> tuple[Concept, tuple[Property, ...]]:
    ranked: list[tuple[int, int, Concept, tuple[Property, ...]]] = []
    for concept in concepts:
        matches = tuple(
            property_
            for property_ in resolver.list_properties(concept.uri)
            if _match_score(query, property_) is not None
        )
        if not matches:
            continue
        total_score = sum(_match_score(query, property_) or 0 for property_ in matches)
        ranked.append((total_score, len(matches), concept, matches))
    if not ranked:
        raise NoMatchingConceptError("未匹配到本体概念")
    best_rank = max((score, count) for score, count, _, _ in ranked)
    winners = sorted(
        (
            (concept, matches)
            for score, count, concept, matches in ranked
            if (score, count) == best_rank
        ),
        key=lambda item: item[0].uri,
    )
    if len(winners) != 1:
        raise AmbiguousQueryConceptError(
            "查询命中了多个同等本体概念",
            details={"candidates": tuple(item[0].short_name for item in winners)},
        )
    return winners[0]


class OntologyPlanner:
    def __init__(self, resolver: OntologyResolver) -> None:
        self._resolver = resolver

    def plan(self, query: str, *, system_time: str | None = None) -> QueryPlan:
        normalized_query = normalize_text(query)
        concepts = self._resolver.list_concepts()
        try:
            concept = _best_concept(normalized_query, concepts)
        except NoMatchingConceptError:
            concept, inferred_properties = _infer_concept_from_properties(
                normalized_query,
                self._resolver,
                concepts,
            )
        else:
            inferred_properties = ()
        sources = {item.uri: item for item in self._resolver.list_data_sources()}
        object_mappings = tuple(
            item
            for item in self._resolver.list_mappings(concept.uri)
            if item.object_name and item.data_source_uri in sources
        )
        if not object_mappings:
            raise UnsupportedQueryPlanError("本体概念缺少可用的对象映射")
        object_binding = object_mappings[0]
        source = sources[object_binding.data_source_uri]

        properties = self._resolver.list_properties(concept.uri)
        matched_properties = inferred_properties or tuple(
            property_
            for property_ in properties
            if _match_score(normalized_query, property_) is not None
        )
        bindings: list[BoundProperty] = []
        by_property_uri: dict[str, BoundProperty] = {}
        for property_ in properties:
            mapping = next(
                (
                    item
                    for item in self._resolver.list_mappings(property_.uri, source.uri)
                    if item.field_name
                ),
                None,
            )
            if mapping is not None:
                bound = BoundProperty(semantic=property_, binding=mapping)
                bindings.append(bound)
                by_property_uri[property_.uri] = bound

        requested = matched_properties
        if not requested:
            raise UnsupportedQueryPlanError("未匹配到查询属性")
        if any(item.uri not in by_property_uri for item in requested):
            raise UnsupportedQueryPlanError("查询属性缺少可用的字段映射")
        selections = tuple(by_property_uri[item.uri] for item in requested)
        rules = tuple(
            item for item in self._resolver.list_rules(concept.uri) if item.status == "active"
        )
        policy = self._resolver.get_temporal_policy(concept.uri)
        filters: tuple[ResolvedFilter, ...] = ()
        temporal_decision = None
        if policy is not None:
            partition_binding = by_property_uri.get(policy.partition_property_uri)
            if partition_binding is None:
                raise UnsupportedQueryPlanError(
                    "分区属性缺少可用的字段映射",
                    details={"property_uri": policy.partition_property_uri},
                )
            parsed_system_date = parse_system_date(system_time)
            business_targets = tuple(
                _target(property_)
                for property_ in properties
                if property_.uri != policy.partition_property_uri
                and _could_be_business_date(property_)
            )
            parsed = parse_temporal_intents(
                query,
                system_date=parsed_system_date,
                grain=policy.grain,
                default_strategy=policy.default_strategy,
                partition_target=_target(partition_binding.semantic),
                other_targets=business_targets,
            )
            resolved_filters = [_resolved_filter(parsed.partition, partition_binding)]
            for intent in parsed.property_intents:
                business_binding = by_property_uri.get(intent.target_property_uri)
                if business_binding is None:
                    raise UnsupportedQueryPlanError(
                        "业务日期属性缺少可用的字段映射",
                        details={"property_uri": intent.target_property_uri},
                    )
                resolved_filters.append(_resolved_filter(intent, business_binding))
            filters = tuple(resolved_filters)
            temporal_decision = TemporalDecision(
                partition_property_uri=policy.partition_property_uri,
                grain=policy.grain,
                source=parsed.partition.source,
                system_date=parsed_system_date,
                matched_text=parsed.partition.matched_text,
                resolved_start=parsed.partition.start,
                resolved_end=parsed.partition.end,
                default_strategy=policy.default_strategy,
                explanation=parsed.partition.explanation,
            )
        return QueryPlan(
            concept=concept,
            data_source=source,
            object_binding=object_binding,
            selections=selections,
            property_bindings=tuple(bindings),
            rules=rules,
            filters=filters,
            temporal_policy=policy,
            temporal_decision=temporal_decision,
        )
