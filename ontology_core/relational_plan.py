"""Immutable, metadata-bound contracts for canonical relational plans."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field, model_validator

from ontology_core.inference_models import (
    CandidateObject,
    SemanticRef,
    InferenceEvidence,
    ValidatedInferenceTemporalDecision,
)
from ontology_core.models import FrozenModel
from ontology_core.normalization import datatype_group
from ontology_core.program_models import ProgramStepKind
from ontology_core.semantic_models import RuleOperator

_NODE_ID = r"^[a-z][a-z0-9_]{0,63}$"
_COLUMN_NAME = r"^[A-Za-z_][A-Za-z0-9_]{0,127}$"
_XSD_INTEGER = "http://www.w3.org/2001/XMLSchema#integer"

NodeId = Annotated[str, Field(pattern=_NODE_ID)]
ColumnName = Annotated[str, Field(pattern=_COLUMN_NAME)]


class LogicalColumnRef(FrozenModel):
    node_id: NodeId
    column: ColumnName


class ScanColumn(FrozenModel):
    name: ColumnName
    field_ref: SemanticRef


class UnionColumn(FrozenModel):
    name: ColumnName
    sources: tuple[LogicalColumnRef, ...] = Field(min_length=1)


class DerivedColumn(FrozenModel):
    name: ColumnName
    source: LogicalColumnRef


class AggregateColumn(FrozenModel):
    name: ColumnName
    function: Literal["count", "sum", "avg", "min", "max"]
    source: LogicalColumnRef | None = None
    distinct: bool = False

    @model_validator(mode="after")
    def require_source_for_value_aggregation(self) -> AggregateColumn:
        if self.function != "count" and self.source is None:
            raise ValueError("数值聚合必须引用逻辑列")
        if self.source is None and self.distinct:
            raise ValueError("COUNT DISTINCT 必须引用逻辑列")
        return self


class JoinCondition(FrozenModel):
    left: LogicalColumnRef
    right: LogicalColumnRef


class FilterPredicate(FrozenModel):
    column: LogicalColumnRef
    operator: RuleOperator
    values: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_values(self) -> FilterPredicate:
        if self.operator == RuleOperator.IS_NULL:
            if self.values:
                raise ValueError("空值判断不能携带比较值")
            return self
        if not self.values:
            raise ValueError("过滤条件缺少比较值")
        if self.operator == RuleOperator.BETWEEN and len(self.values) != 2:
            raise ValueError("区间过滤必须包含两个比较值")
        if self.operator not in {RuleOperator.IN, RuleOperator.BETWEEN} and len(self.values) != 1:
            raise ValueError("过滤条件的比较值数量无效")
        return self


class ScanNode(FrozenModel):
    kind: Literal["scan"] = "scan"
    node_id: NodeId
    object_ref: SemanticRef
    columns: tuple[ScanColumn, ...] = Field(min_length=1)


class UnionAllNode(FrozenModel):
    kind: Literal["union_all"] = "union_all"
    node_id: NodeId
    inputs: tuple[NodeId, ...] = Field(min_length=2)
    columns: tuple[UnionColumn, ...] = Field(min_length=1)


class JoinNode(FrozenModel):
    kind: Literal["join"] = "join"
    node_id: NodeId
    left_input: NodeId
    right_input: NodeId
    join_type: Literal["inner", "left", "anti"]
    anti_strategy: Literal["left_join", "not_exists"] = "left_join"
    conditions: tuple[JoinCondition, ...] = Field(min_length=1)
    match_filters: tuple[FilterPredicate, ...] = ()
    columns: tuple[DerivedColumn, ...] = Field(min_length=1)


class FilterNode(FrozenModel):
    kind: Literal["filter"] = "filter"
    node_id: NodeId
    input: NodeId
    predicates: tuple[FilterPredicate, ...] = Field(min_length=1)


class ProjectNode(FrozenModel):
    kind: Literal["project"] = "project"
    node_id: NodeId
    input: NodeId
    columns: tuple[DerivedColumn, ...] = Field(min_length=1)


class AggregateNode(FrozenModel):
    kind: Literal["aggregate"] = "aggregate"
    node_id: NodeId
    input: NodeId
    group_by: tuple[DerivedColumn, ...] = ()
    aggregations: tuple[AggregateColumn, ...] = Field(min_length=1)


class MaterializeNode(FrozenModel):
    kind: Literal["materialize"] = "materialize"
    node_id: NodeId
    input: NodeId
    step_kind: ProgramStepKind


RelationalNode: TypeAlias = Annotated[
    ScanNode | UnionAllNode | JoinNode | FilterNode | ProjectNode | AggregateNode | MaterializeNode,
    Field(discriminator="kind"),
]


class CanonicalRelationalPlan(FrozenModel):
    package_id: str = Field(min_length=1)
    package_version: str = Field(min_length=1)
    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_source_ref: str = Field(min_length=1)
    dialect: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    objects: tuple[CandidateObject, ...] = Field(min_length=1)
    nodes: tuple[RelationalNode, ...] = Field(min_length=1)
    result_node_id: NodeId
    temporal_decisions: tuple[ValidatedInferenceTemporalDecision, ...] = ()
    inference_evidence: InferenceEvidence | None = None

    @model_validator(mode="after")
    def validate_relational_graph(self) -> CanonicalRelationalPlan:
        objects = {item.ref: item for item in self.objects}
        if len(objects) != len(self.objects):
            raise ValueError("关系计划中的候选对象引用必须唯一")
        if any(item.data_source_ref != self.data_source_ref for item in self.objects):
            raise ValueError("关系计划对象必须来自同一数据源和本体快照")

        schemas: dict[str, dict[str, str]] = {}
        result_materializations: list[str] = []
        for node in self.nodes:
            if node.node_id in schemas:
                raise ValueError("关系计划节点标识必须唯一")
            schema = self._validate_node(node, objects, schemas)
            schemas[node.node_id] = schema
            if isinstance(node, MaterializeNode) and node.step_kind == ProgramStepKind.RESULT:
                result_materializations.append(node.node_id)

        if result_materializations != [self.result_node_id]:
            raise ValueError("结果节点必须指向唯一的 RESULT 物化节点")
        return self

    @classmethod
    def _validate_node(
        cls,
        node: RelationalNode,
        objects: dict[str, CandidateObject],
        schemas: dict[str, dict[str, str]],
    ) -> dict[str, str]:
        if isinstance(node, ScanNode):
            try:
                object_ = objects[node.object_ref]
            except KeyError as error:
                raise ValueError("扫描节点引用了未知候选对象") from error
            fields = {item.ref: item for item in object_.fields}
            output: dict[str, str] = {}
            for column in node.columns:
                try:
                    field = fields[column.field_ref]
                except KeyError as error:
                    raise ValueError("扫描字段不属于声明的候选对象") from error
                cls._add_output(output, column.name, field.datatype_uri)
            return output

        if isinstance(node, UnionAllNode):
            input_schemas = tuple(cls._upstream(item, schemas) for item in node.inputs)
            output = {}
            for column in node.columns:
                if tuple(item.node_id for item in column.sources) != node.inputs:
                    raise ValueError("并集列必须按输入顺序提供一个来源列")
                datatypes = tuple(
                    cls._column_type(source, input_schema, "并集")
                    for source, input_schema in zip(column.sources, input_schemas, strict=True)
                )
                if len(set(datatypes)) != 1:
                    raise ValueError("并集来源列的数据类型必须一致")
                cls._add_output(output, column.name, datatypes[0])
            return output

        if isinstance(node, JoinNode):
            left = cls._upstream(node.left_input, schemas)
            right = cls._upstream(node.right_input, schemas)
            for condition in node.conditions:
                if (
                    condition.left.node_id != node.left_input
                    or condition.right.node_id != node.right_input
                ):
                    raise ValueError("连接条件必须保持声明的左右输入")
                left_type = cls._column_type(condition.left, left, "连接")
                right_type = cls._column_type(condition.right, right, "连接")
                if datatype_group(left_type) != datatype_group(right_type):
                    raise ValueError("连接条件两侧的数据类型必须一致")
            for predicate in node.match_filters:
                cls._require_direct_ref(predicate.column, node.right_input, right, "匹配过滤")
            output = {}
            allowed = {node.left_input: left, node.right_input: right}
            for column in node.columns:
                if node.join_type == "anti" and column.source.node_id != node.left_input:
                    raise ValueError("排除连接只能输出保留的左侧输入列")
                datatype = cls._type_from_allowed(column.source, allowed, "连接输出")
                cls._add_output(output, column.name, datatype)
            return output

        if isinstance(node, FilterNode):
            input_schema = cls._upstream(node.input, schemas)
            for predicate in node.predicates:
                cls._require_direct_ref(predicate.column, node.input, input_schema, "过滤")
            return dict(input_schema)

        if isinstance(node, ProjectNode):
            input_schema = cls._upstream(node.input, schemas)
            output = {}
            for column in node.columns:
                datatype = cls._require_direct_ref(
                    column.source,
                    node.input,
                    input_schema,
                    "投影",
                )
                cls._add_output(output, column.name, datatype)
            return output

        if isinstance(node, AggregateNode):
            input_schema = cls._upstream(node.input, schemas)
            output = {}
            for column in node.group_by:
                datatype = cls._require_direct_ref(
                    column.source,
                    node.input,
                    input_schema,
                    "聚合分组",
                )
                cls._add_output(output, column.name, datatype)
            for column in node.aggregations:
                source_type = None
                if column.source is not None:
                    source_type = cls._require_direct_ref(
                        column.source,
                        node.input,
                        input_schema,
                        "聚合",
                    )
                datatype = _XSD_INTEGER if column.function == "count" else source_type
                assert datatype is not None
                cls._add_output(output, column.name, datatype)
            return output

        if isinstance(node, MaterializeNode):
            return dict(cls._upstream(node.input, schemas))

        raise AssertionError(f"unsupported relational node: {type(node)!r}")

    @staticmethod
    def _upstream(node_id: str, schemas: dict[str, dict[str, str]]) -> dict[str, str]:
        try:
            return schemas[node_id]
        except KeyError as error:
            raise ValueError("关系节点必须引用已声明的上游节点") from error

    @staticmethod
    def _add_output(output: dict[str, str], name: str, datatype: str) -> None:
        if name in output:
            raise ValueError("关系节点包含重复输出列")
        output[name] = datatype

    @staticmethod
    def _column_type(
        reference: LogicalColumnRef,
        schema: dict[str, str],
        context: str,
    ) -> str:
        try:
            return schema[reference.column]
        except KeyError as error:
            raise ValueError(f"{context}引用了未知输出列") from error

    @classmethod
    def _require_direct_ref(
        cls,
        reference: LogicalColumnRef,
        input_node: str,
        schema: dict[str, str],
        context: str,
    ) -> str:
        if reference.node_id != input_node:
            raise ValueError(f"{context}只能引用直接输入")
        return cls._column_type(reference, schema, context)

    @classmethod
    def _type_from_allowed(
        cls,
        reference: LogicalColumnRef,
        allowed: dict[str, dict[str, str]],
        context: str,
    ) -> str:
        try:
            schema = allowed[reference.node_id]
        except KeyError as error:
            raise ValueError(f"{context}只能引用连接的左右输入") from error
        return cls._column_type(reference, schema, context)
