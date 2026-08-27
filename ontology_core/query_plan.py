from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from ontology_core.models import FrozenModel
from ontology_core.semantic_models import (
    BusinessRule,
    Concept,
    DataSource,
    PhysicalMapping,
    Property,
    RdfLiteral,
    Relation,
    RuleOperator,
    TemporalDefaultStrategy,
    TemporalGrain,
    TemporalPartitionPolicy,
)
from ontology_core.temporal import TemporalIntentSource


class BoundObject(FrozenModel):
    alias: str = Field(pattern=r"^t[01]$")
    semantic: Concept
    binding: PhysicalMapping


class BoundProperty(FrozenModel):
    semantic: Property
    binding: PhysicalMapping
    object_alias: str = Field(pattern=r"^t[01]$")


class ResolvedJoin(FrozenModel):
    relation: Relation
    left: BoundProperty
    right: BoundProperty
    join_type: Literal["inner"] = "inner"


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
    concepts: tuple[Concept, ...] = Field(min_length=1, max_length=2)
    data_source: DataSource
    objects: tuple[BoundObject, ...] = Field(min_length=1, max_length=2)
    selections: tuple[BoundProperty, ...]
    property_bindings: tuple[BoundProperty, ...]
    joins: tuple[ResolvedJoin, ...] = Field(default=(), max_length=1)
    rules: tuple[BusinessRule, ...] = ()
    filters: tuple[ResolvedFilter, ...] = ()
    temporal_policies: tuple[TemporalPartitionPolicy, ...] = ()
    temporal_decisions: tuple[TemporalDecision, ...] = ()

    @model_validator(mode="after")
    def validate_structure(self) -> QueryPlan:
        if len(self.concepts) != len(self.objects):
            raise ValueError("概念与对象绑定数量不一致")
        if len({item.uri for item in self.concepts}) != len(self.concepts):
            raise ValueError("查询计划包含重复概念")
        if len({item.alias for item in self.objects}) != len(self.objects):
            raise ValueError("对象别名必须唯一")
        if len(self.objects) == 1 and self.joins:
            raise ValueError("单对象查询不能包含关系")
        if len(self.objects) == 2 and len(self.joins) != 1:
            raise ValueError("双对象查询必须包含一条关系")

        aliases_by_concept = {item.semantic.uri: item.alias for item in self.objects}
        concept_uris = {item.uri for item in self.concepts}
        if set(aliases_by_concept) != concept_uris:
            raise ValueError("对象绑定与查询概念不一致")
        for item in self.objects:
            if item.binding.semantic_element_uri != item.semantic.uri:
                raise ValueError("对象映射不属于绑定概念")
            if item.binding.data_source_uri != self.data_source.uri:
                raise ValueError("查询对象必须属于同一数据源")

        binding_keys: set[tuple[str, str]] = set()
        for item in self.property_bindings:
            expected_alias = aliases_by_concept.get(item.semantic.concept_uri)
            if expected_alias != item.object_alias:
                raise ValueError("属性绑定不属于指定对象")
            if item.binding.semantic_element_uri != item.semantic.uri:
                raise ValueError("属性映射不属于绑定属性")
            if item.binding.data_source_uri != self.data_source.uri:
                raise ValueError("查询属性必须属于同一数据源")
            binding_keys.add((item.object_alias, item.semantic.uri))
        if any(
            (item.object_alias, item.semantic.uri) not in binding_keys for item in self.selections
        ):
            raise ValueError("选择属性缺少查询绑定")

        for join in self.joins:
            if (join.left.object_alias, join.left.semantic.uri) not in binding_keys or (
                join.right.object_alias,
                join.right.semantic.uri,
            ) not in binding_keys:
                raise ValueError("关系关联键缺少查询绑定")
            actual = {
                (join.left.semantic.concept_uri, join.left.semantic.uri),
                (join.right.semantic.concept_uri, join.right.semantic.uri),
            }
            expected = {
                (join.relation.source_concept_uri, join.relation.source_property_uri),
                (join.relation.target_concept_uri, join.relation.target_property_uri),
            }
            if (
                actual != expected
                or not join.relation.confirmed
                or join.relation.status != "active"
            ):
                raise ValueError("查询关系与对象关联键不一致")

        if any(item.applies_to_uri not in concept_uris for item in self.temporal_policies):
            raise ValueError("时间策略不属于查询对象")
        policy_properties = {item.partition_property_uri for item in self.temporal_policies}
        if any(
            item.partition_property_uri not in policy_properties for item in self.temporal_decisions
        ):
            raise ValueError("时间决策缺少对应策略")
        return self

    @property
    def concept(self) -> Concept:
        return self.concepts[0]

    @property
    def object_binding(self) -> PhysicalMapping:
        return self.objects[0].binding

    @property
    def temporal_policy(self) -> TemporalPartitionPolicy | None:
        return self.temporal_policies[0] if self.temporal_policies else None

    @property
    def temporal_decision(self) -> TemporalDecision | None:
        return self.temporal_decisions[0] if self.temporal_decisions else None


class CompiledQuery(FrozenModel):
    sql: str
    tables: tuple[str, ...]
    fields: tuple[str, ...]
    predicates: tuple[str, ...] = ()
