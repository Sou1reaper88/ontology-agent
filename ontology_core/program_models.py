"""Immutable, platform-neutral contracts for multi-step SQL programs."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from ontology_core.inference_models import InferenceEvidence
from ontology_core.models import FrozenModel
from ontology_core.query_plan import QueryPlan
from ontology_core.semantic_models import RuleOperator

_SEMANTIC_REF = r"^[A-Za-z][A-Za-z0-9._:-]*$"
_STEP_ID = r"^[a-z][a-z0-9_]{0,63}$"
_PROGRAM_ID = r"^[a-z0-9_]{8,64}$"
SemanticRef = Annotated[str, Field(pattern=_SEMANTIC_REF)]


class ProgramModel(FrozenModel):
    """Base contract that rejects undeclared LLM-supplied fields."""


class ProgramStepKind(StrEnum):
    INTERMEDIATE = "intermediate"
    RESULT = "result"


class BusinessConstraintSpec(ProgramModel):
    property_ref: SemanticRef
    operator: RuleOperator
    values: tuple[str, ...] = ()
    negated: bool = False


class TimeIntentSpec(ProgramModel):
    source: Literal["user", "default", "unspecified"] = "unspecified"
    expression: str | None = None
    grain: Literal["day", "month"] | None = None
    requires_default: bool = False


class AggregationSpec(ProgramModel):
    function: Literal["count", "sum", "avg", "min", "max"]
    property_ref: SemanticRef | None = None
    distinct: bool = False

    @model_validator(mode="after")
    def require_property_for_value_aggregation(self) -> AggregationSpec:
        if self.function != "count" and self.property_ref is None:
            raise ValueError("数值聚合必须引用语义属性")
        return self


class OrderBySpec(ProgramModel):
    property_ref: SemanticRef
    direction: Literal["asc", "desc"] = "asc"


class ResultShapeSpec(ProgramModel):
    distinct: bool = False
    aggregations: tuple[AggregationSpec, ...] = ()
    group_by: tuple[SemanticRef, ...] = ()
    order_by: tuple[OrderBySpec, ...] = ()
    limit: int | None = Field(default=None, ge=1)


class IntentSpec(ProgramModel):
    task_type: Literal["data_extraction"] = "data_extraction"
    output_mode: Literal["materialized_table"] = "materialized_table"
    normalized_request: str = Field(min_length=1)
    business_concepts: tuple[SemanticRef, ...] = Field(min_length=1)
    requested_properties: tuple[SemanticRef, ...] = Field(min_length=1)
    business_constraints: tuple[BusinessConstraintSpec, ...] = ()
    time_intent: TimeIntentSpec
    result_shape: ResultShapeSpec
    ambiguities: tuple[str, ...] = ()


class StepSourceBinding(ProgramModel):
    object_ref: SemanticRef
    source_step_id: str | None = Field(default=None, pattern=_STEP_ID)


class DraftProgramStep(ProgramModel):
    step_id: str = Field(pattern=_STEP_ID)
    kind: ProgramStepKind
    purpose: str = Field(min_length=1)
    source_objects: tuple[SemanticRef, ...] = Field(min_length=1)
    source_bindings: tuple[StepSourceBinding, ...] = Field(min_length=1)
    requested_properties: tuple[SemanticRef, ...] = Field(min_length=1)
    relation_refs: tuple[SemanticRef, ...] = ()
    rule_refs: tuple[SemanticRef, ...] = ()
    constraints: tuple[BusinessConstraintSpec, ...] = ()

    @model_validator(mode="after")
    def require_one_binding_per_source_object(self) -> DraftProgramStep:
        object_refs = tuple(item.object_ref for item in self.source_bindings)
        if len(set(self.source_objects)) != len(self.source_objects):
            raise ValueError("步骤源对象必须唯一")
        if len(set(object_refs)) != len(object_refs) or set(object_refs) != set(
            self.source_objects
        ):
            raise ValueError("步骤源对象必须各有一个来源绑定")
        return self


class DraftSqlProgramPlan(ProgramModel):
    intent: IntentSpec
    steps: tuple[DraftProgramStep, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_intrinsic_step_references(self) -> DraftSqlProgramPlan:
        step_ids = tuple(item.step_id for item in self.steps)
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("步骤标识必须唯一")
        result_count = sum(item.kind == ProgramStepKind.RESULT for item in self.steps)
        if result_count != 1:
            raise ValueError("程序必须且只能包含一个结果步骤")
        known = set(step_ids)
        for step in self.steps:
            dependencies = {
                item.source_step_id
                for item in step.source_bindings
                if item.source_step_id is not None
            }
            if step.step_id in dependencies:
                raise ValueError("步骤依赖不能引用自身")
            if dependencies - known:
                raise ValueError("步骤依赖包含未知步骤")
        return self


class ProgramDiagnostic(ProgramModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    message: str = Field(min_length=1)
    step_id: str | None = Field(default=None, pattern=_STEP_ID)
    location: str | None = None
    candidates: tuple[str, ...] = ()


class ProgramStep(ProgramModel):
    step_id: str = Field(pattern=_STEP_ID)
    kind: ProgramStepKind
    purpose: str = Field(min_length=1)
    source_objects: tuple[SemanticRef, ...] = Field(min_length=1)
    source_bindings: tuple[StepSourceBinding, ...] = Field(min_length=1)
    query_plan: QueryPlan

    @model_validator(mode="after")
    def require_one_binding_per_source_object(self) -> ProgramStep:
        object_refs = tuple(item.object_ref for item in self.source_bindings)
        if len(set(object_refs)) != len(object_refs) or set(object_refs) != set(
            self.source_objects
        ):
            raise ValueError("已绑定步骤的源对象与来源不一致")
        return self


class SqlProgramPlan(ProgramModel):
    program_id: str = Field(pattern=_PROGRAM_ID)
    package_id: str = Field(min_length=1)
    package_version: str = Field(min_length=1)
    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_source_id: str = Field(min_length=1)
    dialect: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    intent: IntentSpec
    steps: tuple[ProgramStep, ...] = Field(min_length=1)
    result_step_id: str = Field(pattern=_STEP_ID)
    diagnostics: tuple[ProgramDiagnostic, ...] = ()
    repair_count: int = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_result_identity(self) -> SqlProgramPlan:
        step_ids = tuple(item.step_id for item in self.steps)
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("步骤标识必须唯一")
        result_ids = tuple(
            item.step_id for item in self.steps if item.kind == ProgramStepKind.RESULT
        )
        if result_ids != (self.result_step_id,):
            raise ValueError("结果步骤标识必须指向唯一结果步骤")
        if any(item.query_plan.data_source.uri != self.data_source_id for item in self.steps):
            raise ValueError("所有步骤必须绑定到同一数据源")
        return self


class CompiledStatement(ProgramModel):
    step_id: str = Field(pattern=_STEP_ID)
    target_table: str = Field(min_length=1)
    drop_sql: str = Field(min_length=1)
    create_sql: str = Field(min_length=1)


class LineageEdge(ProgramModel):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    kind: Literal["ontology_source", "step"]


class TemporalCompilationEvidence(ProgramModel):
    partition_property_ref: SemanticRef
    grain: Literal["day", "month"]
    source: Literal["user", "default"]
    resolved_start: str = Field(min_length=1)
    resolved_end: str = Field(min_length=1)
    explanation: str = Field(min_length=1)


class ProgramCompilationEvidence(ProgramModel):
    source_tables: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()
    relations: tuple[str, ...] = ()
    rules: tuple[str, ...] = ()
    temporal_decisions: tuple[TemporalCompilationEvidence, ...] = ()
    inference: InferenceEvidence | None = None


class CompiledProgram(ProgramModel):
    program_id: str = Field(pattern=_PROGRAM_ID)
    dialect: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    sql: str = Field(min_length=1)
    statements: tuple[CompiledStatement, ...] = Field(min_length=1)
    intermediate_tables: tuple[str, ...] = ()
    result_table: str = Field(min_length=1)
    lineage: tuple[LineageEdge, ...] = ()
    evidence: ProgramCompilationEvidence
    diagnostics: tuple[ProgramDiagnostic, ...] = ()

    @model_validator(mode="after")
    def validate_materialized_targets(self) -> CompiledProgram:
        targets = tuple(item.target_table for item in self.statements)
        if len(set(targets)) != len(targets):
            raise ValueError("编译程序包含重复目标表")
        if self.result_table in self.intermediate_tables:
            raise ValueError("结果表不能同时作为中间表")
        if set(targets) != {*self.intermediate_tables, self.result_table}:
            raise ValueError("编译语句目标与程序物化表不一致")
        return self
