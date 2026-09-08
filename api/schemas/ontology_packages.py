"""Request DTOs for ontology package management routes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ontology_core.management.models import DraftRelation, DraftTemporalPolicy
from ontology_core.semantic_models import TemporalDefaultStrategy, TemporalGrain


class RevisionRequest(BaseModel):
    expected_revision: int = Field(ge=0)


class CascadeDeleteRequest(RevisionRequest):
    cascade: bool
    confirmation_name: str = Field(min_length=1)

    @field_validator("confirmation_name")
    @classmethod
    def require_nonblank_confirmation_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("删除确认名称不能为空")
        return value


class DescriptivePatch(RevisionRequest):
    label: str | None = None
    description: str | None = None

    def changes(self) -> dict[str, str | None]:
        return {
            name: getattr(self, name)
            for name in ("label", "description")
            if name in self.model_fields_set
        }


class RelationRequest(RevisionRequest):
    label: str = ""
    source_object_id: str
    source_field_id: str
    target_object_id: str
    target_field_id: str
    cardinality: Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]
    status: Literal["active", "inactive"] = "active"
    priority: int = 100
    confirmed: bool = False

    def relation(self, relation_id: str) -> DraftRelation:
        return DraftRelation(id=relation_id, **self.model_dump(exclude={"expected_revision"}))


class TemporalPolicyRequest(RevisionRequest):
    partition_field_id: str
    grain: TemporalGrain
    default_strategy: TemporalDefaultStrategy
    allow_query_override: bool = True
    status: Literal["active", "inactive"] = "active"
    priority: int = 100

    def policy(self, object_id: str) -> DraftTemporalPolicy:
        return DraftTemporalPolicy(
            object_id=object_id, **self.model_dump(exclude={"expected_revision"})
        )


class DiagnosticResolutionRequest(RevisionRequest):
    explanation: str = Field(min_length=1)
    status: Literal["resolved", "dismissed"] = "resolved"


class PublishRequest(RevisionRequest):
    version: str = Field(min_length=1)
    release_notes: str = Field(min_length=1)

    @field_validator("release_notes")
    @classmethod
    def require_nonblank_release_notes(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("发布说明不能为空")
        return stripped


class RollbackRequest(BaseModel):
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def require_nonblank_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("回滚原因不能为空")
        return stripped
