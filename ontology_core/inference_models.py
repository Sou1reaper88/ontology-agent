"""Closed contracts for metadata-grounded candidate inference.

The language model may only produce ``InferredProgramDraft``. Physical metadata
is populated by Python from one immutable ontology snapshot.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from ontology_core.models import FrozenModel
from ontology_core.semantic_models import (
    RuleOperator,
    TemporalDefaultStrategy,
    TemporalGrain,
)

_SEMANTIC_REF = r"^[A-Za-z][A-Za-z0-9._:-]*$"
_FAMILY_REF = r"^family\.[a-z0-9][a-z0-9._-]*$"
SemanticRef = Annotated[str, Field(pattern=_SEMANTIC_REF)]
FamilyRef = Annotated[str, Field(pattern=_FAMILY_REF)]


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CandidateTemporalPolicy(FrozenModel):
    ref: SemanticRef
    partition_field_ref: SemanticRef
    grain: TemporalGrain
    default_strategy: TemporalDefaultStrategy
    allow_query_override: bool = True


class CandidateField(FrozenModel):
    ref: SemanticRef
    object_ref: SemanticRef
    label: str = Field(min_length=1)
    description: str | None = None
    datatype_uri: str = Field(min_length=1)
    physical_name: str = Field(min_length=1)
    retrieval_score: int = Field(default=0, ge=0)
    matched_terms: tuple[str, ...] = ()
    details_loaded: bool = True


class CandidateObject(FrozenModel):
    ref: SemanticRef
    label: str = Field(min_length=1)
    description: str | None = None
    data_source_ref: str = Field(min_length=1)
    physical_namespace: str | None = None
    physical_name: str = Field(min_length=1)
    fields: tuple[CandidateField, ...] = Field(min_length=1)
    temporal_policy: CandidateTemporalPolicy | None = None
    family_ref: FamilyRef | None = None
    retrieval_score: int = Field(default=0, ge=0)
    matched_terms: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_field_ownership(self) -> CandidateObject:
        refs = tuple(item.ref for item in self.fields)
        if len(set(refs)) != len(refs):
            raise ValueError("候选字段引用必须唯一")
        if any(item.object_ref != self.ref for item in self.fields):
            raise ValueError("候选字段必须属于候选对象")
        return self


class CandidateTableFamily(FrozenModel):
    ref: FamilyRef
    label: str = Field(min_length=1)
    member_refs: tuple[SemanticRef, ...] = Field(min_length=2)
    varying_token_index: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_members(self) -> CandidateTableFamily:
        if len(set(self.member_refs)) != len(self.member_refs):
            raise ValueError("表族成员引用必须唯一")
        return self


class CandidateContext(FrozenModel):
    package_id: str = Field(min_length=1)
    package_version: str = Field(min_length=1)
    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    objects: tuple[CandidateObject, ...] = ()
    families: tuple[CandidateTableFamily, ...] = ()


class InferredJoinDraft(FrozenModel):
    left_object_ref: SemanticRef
    left_field_ref: SemanticRef
    right_object_ref: SemanticRef
    right_field_ref: SemanticRef
    confidence: Confidence
    evidence: tuple[str, ...] = Field(min_length=1)


class InferredFilterDraft(FrozenModel):
    field_ref: SemanticRef
    operator: RuleOperator
    values: tuple[str, ...] = ()
    confidence: Confidence
    evidence: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_values_when_operator_needs_them(self) -> InferredFilterDraft:
        unary = {RuleOperator.IS_NULL}
        if self.operator not in unary and not self.values:
            raise ValueError("候选过滤条件缺少值")
        if self.operator in unary and self.values:
            raise ValueError("空值判断不能携带比较值")
        return self


class InferredProgramDraft(FrozenModel):
    selected_object_refs: tuple[SemanticRef, ...] = Field(min_length=1)
    selected_family_refs: tuple[FamilyRef, ...] = ()
    requested_field_refs: tuple[SemanticRef, ...] = Field(min_length=1)
    joins: tuple[InferredJoinDraft, ...] = ()
    filters: tuple[InferredFilterDraft, ...] = ()
    time_expression: str | None = None
    unresolved_items: tuple[str, ...] = ()
    ontology_suggestions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def require_unique_references(self) -> InferredProgramDraft:
        collections = (
            self.selected_object_refs,
            self.selected_family_refs,
            self.requested_field_refs,
        )
        if any(len(set(items)) != len(items) for items in collections):
            raise ValueError("候选计划引用必须唯一")
        return self


class ValidatedInferredJoin(FrozenModel):
    left_object_ref: SemanticRef
    left_field: CandidateField
    right_object_ref: SemanticRef
    right_field: CandidateField
    confidence: Confidence
    evidence: tuple[str, ...] = Field(min_length=1)
    join_type: Literal["inner"] = "inner"


class ValidatedInferredFilter(FrozenModel):
    field: CandidateField
    operator: RuleOperator
    values: tuple[str, ...] = ()
    confidence: Confidence
    evidence: tuple[str, ...] = Field(min_length=1)


class ValidatedInferenceTemporalDecision(FrozenModel):
    object_ref: SemanticRef
    partition_field: CandidateField
    grain: TemporalGrain
    source: Literal["user", "default"]
    resolved_start: str = Field(min_length=1)
    resolved_end: str = Field(min_length=1)
    explanation: str = Field(min_length=1)


class InferenceEvidence(FrozenModel):
    overall_confidence: Confidence
    reasons: tuple[str, ...] = Field(min_length=1)
    unresolved_items: tuple[str, ...] = ()
    ontology_suggestions: tuple[str, ...] = ()


class ValidatedInferredProgram(FrozenModel):
    package_id: str = Field(min_length=1)
    package_version: str = Field(min_length=1)
    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_source_ref: str = Field(min_length=1)
    dialect: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    objects: tuple[CandidateObject, ...] = Field(min_length=1)
    families: tuple[CandidateTableFamily, ...] = ()
    requested_fields: tuple[CandidateField, ...] = Field(min_length=1)
    joins: tuple[ValidatedInferredJoin, ...] = ()
    filters: tuple[ValidatedInferredFilter, ...] = ()
    temporal_decisions: tuple[ValidatedInferenceTemporalDecision, ...] = ()
    evidence: InferenceEvidence
