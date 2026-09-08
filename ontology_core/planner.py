from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from ontology_core.errors import (
    AmbiguousIdentifierError,
    AmbiguousQueryConceptError,
    ConceptNotFoundError,
    NoMatchingConceptError,
    PropertyNotFoundError,
    UnsupportedQueryPlanError,
)
from ontology_core.normalization import normalize_text
from ontology_core.program_models import (
    BusinessConstraintSpec,
    DraftProgramStep,
    IntentSpec,
)
from ontology_core.query_plan import (
    BoundObject,
    BoundProperty,
    QueryPlan,
    ResolvedFilter,
    ResolvedJoin,
    TemporalDecision,
)
from ontology_core.repository import OntologySnapshot
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


def _property_position(query: str, property_: Property) -> int:
    positions = tuple(query.find(alias) for alias in _aliases(property_) if alias in query)
    return min(positions) if positions else len(query)


def _selected_concepts(
    query: str,
    resolver: OntologyResolver,
    concepts: tuple[Concept, ...],
) -> tuple[tuple[Concept, tuple[Property, ...]], ...]:
    matched = tuple(
        (concept, properties)
        for concept in concepts
        if (
            properties := tuple(
                property_
                for property_ in resolver.list_properties(concept.uri)
                if _match_score(query, property_) is not None
            )
        )
    )
    if len(matched) > 2:
        raise UnsupportedQueryPlanError("查询涉及超过两个本体概念")
    if len(matched) == 2:
        matched_aliases = [
            {
                alias
                for property_ in properties
                for alias in _aliases(property_)
                if alias in query
            }
            for _, properties in matched
        ]
        if matched_aliases[0] == matched_aliases[1]:
            raise AmbiguousQueryConceptError(
                "查询属性在多个本体概念中存在歧义",
                details={"candidates": tuple(item[0].short_name for item in matched)},
            )
    if matched:
        return tuple(
            sorted(
                matched,
                key=lambda item: (
                    min(_property_position(query, property_) for property_ in item[1]),
                    item[0].uri,
                ),
            )
        )
    concept = _best_concept(query, concepts)
    return ((concept, ()),)


class OntologyPlanner:
    def __init__(self, resolver: OntologyResolver) -> None:
        self._resolver = resolver

    def plan(self, query: str, *, system_time: str | None = None) -> QueryPlan:
        normalized_query = normalize_text(query)
        concepts = self._resolver.list_concepts()
        selected = _selected_concepts(normalized_query, self._resolver, concepts)
        sources = {item.uri: item for item in self._resolver.list_data_sources()}
        object_mappings = {
            concept.uri: tuple(
                item
                for item in self._resolver.list_mappings(concept.uri)
                if item.object_name and item.data_source_uri in sources
            )
            for concept, _ in selected
        }
        common_sources = tuple(
            source_uri
            for source_uri in sources
            if all(
                any(item.data_source_uri == source_uri for item in object_mappings[concept.uri])
                for concept, _ in selected
            )
        )
        if not common_sources:
            raise UnsupportedQueryPlanError("查询对象缺少同一数据源的对象映射")
        source = sources[common_sources[0]]
        objects = tuple(
            BoundObject(
                alias=f"t{index}",
                semantic=concept,
                binding=next(
                    item
                    for item in object_mappings[concept.uri]
                    if item.data_source_uri == source.uri
                ),
            )
            for index, (concept, _) in enumerate(selected)
        )
        bindings: list[BoundProperty] = []
        by_property_uri: dict[str, BoundProperty] = {}
        properties_by_concept: dict[str, tuple[Property, ...]] = {}
        for object_ in objects:
            properties = self._resolver.list_properties(object_.semantic.uri)
            properties_by_concept[object_.semantic.uri] = properties
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
                    bound = BoundProperty(
                        semantic=property_,
                        binding=mapping,
                        object_alias=object_.alias,
                    )
                    bindings.append(bound)
                    by_property_uri[property_.uri] = bound

        requested = tuple(
            sorted(
                (property_ for _, matches in selected for property_ in matches),
                key=lambda item: (_property_position(normalized_query, item), item.uri),
            )
        )
        if not requested:
            raise UnsupportedQueryPlanError("未匹配到查询属性")
        if any(item.uri not in by_property_uri for item in requested):
            raise UnsupportedQueryPlanError("查询属性缺少可用的字段映射")
        selections = tuple(by_property_uri[item.uri] for item in requested)
        rules = tuple(
            item
            for concept, _ in selected
            for item in self._resolver.list_rules(concept.uri)
            if item.status == "active"
        )
        policies = tuple(
            policy
            for concept, _ in selected
            if (policy := self._resolver.get_temporal_policy(concept.uri)) is not None
        )
        filters: list[ResolvedFilter] = []
        temporal_decisions: list[TemporalDecision] = []
        parsed_system_date = parse_system_date(system_time) if policies else None
        for policy in policies:
            partition_binding = by_property_uri.get(policy.partition_property_uri)
            if partition_binding is None:
                raise UnsupportedQueryPlanError(
                    "分区属性缺少可用的字段映射",
                    details={"property_uri": policy.partition_property_uri},
                )
            properties = properties_by_concept[policy.applies_to_uri]
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
            filters.append(_resolved_filter(parsed.partition, partition_binding))
            for intent in parsed.property_intents:
                business_binding = by_property_uri.get(intent.target_property_uri)
                if business_binding is None:
                    raise UnsupportedQueryPlanError(
                        "业务日期属性缺少可用的字段映射",
                        details={"property_uri": intent.target_property_uri},
                    )
                filters.append(_resolved_filter(intent, business_binding))
            temporal_decisions.append(
                TemporalDecision(
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
            )
        joins: tuple[ResolvedJoin, ...] = ()
        if len(selected) == 2:
            try:
                relation = self._resolver.resolve_direct_relation(
                    selected[0][0].uri,
                    selected[1][0].uri,
                )
                left = by_property_uri[str(relation.source_property_uri)]
                right = by_property_uri[str(relation.target_property_uri)]
            except AmbiguousIdentifierError as exc:
                raise AmbiguousQueryConceptError("直接关系存在歧义", details=exc.details) from exc
            except (ConceptNotFoundError, PropertyNotFoundError, KeyError) as exc:
                raise UnsupportedQueryPlanError("查询概念之间缺少可用的唯一直接关系") from exc
            joins = (ResolvedJoin(relation=relation, left=left, right=right),)
        return QueryPlan(
            concepts=tuple(item[0] for item in selected),
            data_source=source,
            objects=objects,
            selections=selections,
            property_bindings=tuple(bindings),
            joins=joins,
            rules=rules,
            filters=tuple(filters),
            temporal_policies=policies,
            temporal_decisions=tuple(temporal_decisions),
        )

    def plan_structured(
        self,
        step: DraftProgramStep,
        intent: IntentSpec,
        *,
        system_time: datetime,
        snapshot: OntologySnapshot,
    ) -> QueryPlan:
        """Bind one SQL-free program step against one immutable snapshot."""
        shape = intent.result_shape
        if (
            shape.distinct
            or shape.aggregations
            or shape.group_by
            or shape.order_by
            or shape.limit is not None
        ):
            raise UnsupportedQueryPlanError("结构化结果形态暂不受 QueryPlan 支持")
        resolver = OntologyResolver(snapshot)
        concepts = tuple(resolver.get_concept(item) for item in step.source_objects)
        if len(concepts) > 2:
            raise UnsupportedQueryPlanError("查询涉及超过两个本体概念")
        requested = self._resolve_structured_properties(
            resolver,
            concepts,
            step.requested_properties,
        )
        sources = {item.uri: item for item in resolver.list_data_sources()}
        object_mappings = {
            concept.uri: tuple(
                item
                for item in resolver.list_mappings(concept.uri)
                if item.object_name and item.data_source_uri in sources
            )
            for concept in concepts
        }
        common_sources = tuple(
            source_uri
            for source_uri in sources
            if all(
                any(item.data_source_uri == source_uri for item in object_mappings[concept.uri])
                for concept in concepts
            )
        )
        if not common_sources:
            raise UnsupportedQueryPlanError("查询对象缺少同一数据源的对象映射")
        source = sources[common_sources[0]]
        objects = tuple(
            BoundObject(
                alias=f"t{index}",
                semantic=concept,
                binding=next(
                    item
                    for item in object_mappings[concept.uri]
                    if item.data_source_uri == source.uri
                ),
            )
            for index, concept in enumerate(concepts)
        )
        bindings: list[BoundProperty] = []
        by_property_uri: dict[str, BoundProperty] = {}
        properties_by_concept: dict[str, tuple[Property, ...]] = {}
        for object_ in objects:
            properties = resolver.list_properties(object_.semantic.uri)
            properties_by_concept[object_.semantic.uri] = properties
            for property_ in properties:
                mapping = next(
                    (
                        item
                        for item in resolver.list_mappings(property_.uri, source.uri)
                        if item.field_name
                    ),
                    None,
                )
                if mapping is not None:
                    bound = BoundProperty(
                        semantic=property_,
                        binding=mapping,
                        object_alias=object_.alias,
                    )
                    bindings.append(bound)
                    by_property_uri[property_.uri] = bound
        if any(item.uri not in by_property_uri for item in requested):
            raise UnsupportedQueryPlanError("查询属性缺少可用的字段映射")
        selections = tuple(by_property_uri[item.uri] for item in requested)
        rules = self._structured_rules(resolver, concepts, step.rule_refs)
        policies = tuple(
            policy
            for concept in concepts
            if (policy := resolver.get_temporal_policy(concept.uri)) is not None
        )
        filters = list(
            self._structured_filters(
                (*intent.business_constraints, *step.constraints),
                concepts,
                resolver,
                by_property_uri,
            )
        )
        temporal_decisions: list[TemporalDecision] = []
        temporal_query = intent.time_intent.expression or ""
        parsed_system_date = parse_system_date(system_time.date().isoformat()) if policies else None
        for policy in policies:
            partition_binding = by_property_uri.get(policy.partition_property_uri)
            if partition_binding is None:
                raise UnsupportedQueryPlanError(
                    "分区属性缺少可用的字段映射",
                    details={"property_uri": policy.partition_property_uri},
                )
            properties = properties_by_concept[policy.applies_to_uri]
            parsed = parse_temporal_intents(
                temporal_query,
                system_date=parsed_system_date,
                grain=policy.grain,
                default_strategy=policy.default_strategy,
                partition_target=_target(partition_binding.semantic),
                other_targets=tuple(
                    _target(property_)
                    for property_ in properties
                    if property_.uri != policy.partition_property_uri
                    and _could_be_business_date(property_)
                ),
            )
            filters.append(_resolved_filter(parsed.partition, partition_binding))
            for property_intent in parsed.property_intents:
                business_binding = by_property_uri.get(property_intent.target_property_uri)
                if business_binding is None:
                    raise UnsupportedQueryPlanError(
                        "业务日期属性缺少可用的字段映射",
                        details={"property_uri": property_intent.target_property_uri},
                    )
                filters.append(_resolved_filter(property_intent, business_binding))
            temporal_decisions.append(
                TemporalDecision(
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
            )
        joins: tuple[ResolvedJoin, ...] = ()
        if len(concepts) == 2:
            try:
                relation = resolver.resolve_direct_relation(concepts[0].uri, concepts[1].uri)
                relation_matches = {
                    item
                    for item in step.relation_refs
                    if item in {relation.uri, relation.short_name}
                }
                if step.relation_refs and relation_matches != set(step.relation_refs):
                    raise UnsupportedQueryPlanError("步骤关系引用与本体直接关系不一致")
                left = by_property_uri[str(relation.source_property_uri)]
                right = by_property_uri[str(relation.target_property_uri)]
            except AmbiguousIdentifierError as exc:
                raise AmbiguousQueryConceptError("直接关系存在歧义", details=exc.details) from exc
            except (ConceptNotFoundError, PropertyNotFoundError, KeyError) as exc:
                raise UnsupportedQueryPlanError("查询概念之间缺少可用的唯一直接关系") from exc
            joins = (ResolvedJoin(relation=relation, left=left, right=right),)
        return QueryPlan(
            concepts=concepts,
            data_source=source,
            objects=objects,
            selections=selections,
            property_bindings=tuple(bindings),
            joins=joins,
            rules=rules,
            filters=tuple(filters),
            temporal_policies=policies,
            temporal_decisions=tuple(temporal_decisions),
        )

    @staticmethod
    def _resolve_structured_properties(
        resolver: OntologyResolver,
        concepts: tuple[Concept, ...],
        property_refs: tuple[str, ...],
    ) -> tuple[Property, ...]:
        requested: list[Property] = []
        for property_ref in property_refs:
            matches: list[Property] = []
            for concept in concepts:
                try:
                    matches.append(resolver.resolve_property(concept.uri, property_ref))
                except PropertyNotFoundError:
                    continue
            unique = {item.uri: item for item in matches}
            if not unique:
                raise PropertyNotFoundError(
                    "未找到本体属性",
                    details={"property_id": property_ref},
                )
            if len(unique) > 1:
                raise AmbiguousQueryConceptError(
                    "查询属性在多个本体概念中存在歧义",
                    details={"candidates": tuple(sorted(unique))},
                )
            requested.append(next(iter(unique.values())))
        return tuple(requested)

    @staticmethod
    def _structured_rules(
        resolver: OntologyResolver,
        concepts: tuple[Concept, ...],
        rule_refs: tuple[str, ...],
    ):
        available = tuple(
            rule
            for concept in concepts
            for rule in resolver.list_rules(concept.uri)
            if rule.status == "active"
        )
        if not rule_refs:
            return available
        selected = tuple(
            rule
            for rule in available
            if rule.uri in rule_refs or rule.short_name in rule_refs
        )
        if len(selected) != len(set(rule_refs)):
            raise UnsupportedQueryPlanError("步骤规则引用缺少唯一有效本体规则")
        return selected

    @classmethod
    def _structured_filters(
        cls,
        constraints: tuple[BusinessConstraintSpec, ...],
        concepts: tuple[Concept, ...],
        resolver: OntologyResolver,
        by_property_uri: dict[str, BoundProperty],
    ) -> tuple[ResolvedFilter, ...]:
        allowed = {
            RuleOperator.EQ,
            RuleOperator.NE,
            RuleOperator.GT,
            RuleOperator.GTE,
            RuleOperator.LT,
            RuleOperator.LTE,
            RuleOperator.IN,
            RuleOperator.BETWEEN,
            RuleOperator.IS_NULL,
        }
        filters: list[ResolvedFilter] = []
        for constraint in constraints:
            if constraint.negated or constraint.operator not in allowed:
                raise UnsupportedQueryPlanError("步骤过滤条件形态暂不支持")
            property_ = cls._resolve_structured_properties(
                resolver,
                concepts,
                (constraint.property_ref,),
            )[0]
            binding = by_property_uri.get(property_.uri)
            if binding is None:
                raise UnsupportedQueryPlanError("过滤属性缺少可用的字段映射")
            filters.append(
                ResolvedFilter(
                    property=binding,
                    operator=constraint.operator,
                    values=tuple(
                        RdfLiteral(
                            lexical_form=value,
                            datatype_uri=property_.datatype_uri,
                        )
                        for value in constraint.values
                    ),
                    source="structured_intent",
                    explanation="结构化业务过滤条件",
                )
            )
        return tuple(filters)
