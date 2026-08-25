"""Frozen, serializable DTOs used by ontology package management."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from ontology_core.models import FrozenModel
from ontology_core.semantic_models import TemporalDefaultStrategy, TemporalGrain


class DraftDataSource(FrozenModel):
    """A logical data source without connection credentials."""

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    platform_type: str = Field(min_length=1)
    dialect: str | None = None
    physical_namespace: str = ""


class DraftField(FrozenModel):
    """A stable field definition within a draft object."""

    id: str = Field(min_length=1)
    physical_name: str = Field(min_length=1)
    label: str | None = None
    description: str | None = None
    xsd_type: str = Field(min_length=1)
    primary_key: bool = False
    title: bool = False
    aliases: tuple[str, ...] = ()
    status: Literal["active", "inactive"] = "active"
    priority: int = 100


class DraftObject(FrozenModel):
    """A physical object and its field definitions."""

    id: str = Field(min_length=1)
    physical_name: str = Field(min_length=1)
    label: str | None = None
    description: str | None = None
    fields: tuple[DraftField, ...] = ()
    status: Literal["active", "inactive"] = "active"
    priority: int = 100

    @model_validator(mode="after")
    def require_unique_field_ids(self) -> Self:
        _require_unique_ids(self.fields, "属性")
        return self


class DraftRelation(FrozenModel):
    """A directed, explicit relationship between two distinct draft fields."""

    id: str = Field(min_length=1)
    label: str = ""
    source_object_id: str = Field(min_length=1)
    source_field_id: str = Field(min_length=1)
    target_object_id: str = Field(min_length=1)
    target_field_id: str = Field(min_length=1)
    cardinality: Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]
    status: Literal["active", "inactive"] = "active"
    priority: int = 100
    confirmed: bool = False

    @model_validator(mode="after")
    def require_distinct_endpoints(self) -> Self:
        if self.source_object_id == self.target_object_id:
            raise ValueError("关系源对象与目标对象必须不同")
        if self.source_field_id == self.target_field_id:
            raise ValueError("关系源属性与目标属性必须不同")
        return self


class DraftTemporalPolicy(FrozenModel):
    """A complete, table-scoped temporal partition policy."""

    object_id: str = Field(min_length=1)
    partition_field_id: str = Field(min_length=1)
    grain: TemporalGrain
    default_strategy: TemporalDefaultStrategy
    allow_query_override: bool = True
    status: Literal["active", "inactive"] = "active"
    priority: int = 100

    @model_validator(mode="after")
    def require_matching_default_strategy(self) -> Self:
        expected = {
            TemporalGrain.DAY: TemporalDefaultStrategy.T_MINUS_2,
            TemporalGrain.MONTH: TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH,
        }
        if self.default_strategy is not expected[self.grain]:
            raise ValueError("时间分区粒度与默认策略不匹配")
        return self


class DraftDiagnostic(FrozenModel):
    """A stable validation finding, independent from its rendered text."""

    id: str = Field(min_length=1)
    code: str = Field(min_length=1)
    severity: Literal["error", "warning", "confirmation_required"]
    message: str = Field(min_length=1)
    related_ids: tuple[str, ...] = ()


class DiagnosticDisposition(FrozenModel):
    """A recorded resolution or dismissal of a stable diagnostic."""

    diagnostic_id: str = Field(min_length=1)
    status: Literal["resolved", "dismissed"]
    note: str | None = None
    actor: str = Field(min_length=1)
    resolved_at: datetime


class ImportSession(FrozenModel):
    """A short-lived, single-use import preview session."""

    token_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    workspace_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    objects: tuple[DraftObject, ...] = ()
    diagnostics: tuple[DraftDiagnostic, ...] = ()
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None

    @model_validator(mode="after")
    def require_expiry_after_creation(self) -> Self:
        if self.expires_at <= self.created_at:
            raise ValueError("导入会话过期时间必须晚于创建时间")
        return self


class VersionSummary(FrozenModel):
    """Public, credential-free summary of an immutable published version."""

    version: str = Field(min_length=1)
    published_at: datetime
    actor: str = Field(min_length=1)
    release_notes: str = ""
    revision: int | None = Field(default=None, ge=0)
    active: bool = False


class UploadLimits(FrozenModel):
    """Maximum accepted compressed and expanded upload sizes."""

    max_upload_bytes: int = Field(gt=0)
    max_xlsx_uncompressed_bytes: int = Field(gt=0)


class WorkspaceDraft(FrozenModel):
    """The structured, mutable source of truth for one ontology workspace."""

    workspace_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    package_id: str = Field(min_length=1)
    base_uri: str = Field(min_length=1)
    revision: int = Field(ge=0)
    updated_at: datetime
    data_source: DraftDataSource
    objects: tuple[DraftObject, ...] = ()
    relations: tuple[DraftRelation, ...] = ()
    temporal_policies: tuple[DraftTemporalPolicy, ...] = ()
    dispositions: tuple[DiagnosticDisposition, ...] = ()

    @model_validator(mode="after")
    def require_consistent_references(self) -> Self:
        _require_unique_ids(self.objects, "对象")
        _require_unique_ids(self.relations, "关系")
        _require_unique_ids(self.dispositions, "诊断处置", attribute="diagnostic_id")

        fields_by_id: dict[str, str] = {}
        for object_ in self.objects:
            for field in object_.fields:
                if field.id in fields_by_id:
                    raise ValueError(f"属性 ID 重复: {field.id}")
                fields_by_id[field.id] = object_.id

        object_ids = {object_.id for object_ in self.objects}
        for relation in self.relations:
            _require_owned_field(
                relation.source_object_id,
                relation.source_field_id,
                object_ids,
                fields_by_id,
                "关系源",
            )
            _require_owned_field(
                relation.target_object_id,
                relation.target_field_id,
                object_ids,
                fields_by_id,
                "关系目标",
            )

        active_policy_objects: set[str] = set()
        for policy in self.temporal_policies:
            _require_owned_field(
                policy.object_id,
                policy.partition_field_id,
                object_ids,
                fields_by_id,
                "时间策略",
            )
            if policy.status == "active":
                if policy.object_id in active_policy_objects:
                    raise ValueError(f"对象只能有一个启用的时间策略: {policy.object_id}")
                active_policy_objects.add(policy.object_id)
        return self

    def canonical_json(self) -> str:
        """Return a stable, human-readable representation for audit and hashing."""
        normalized_objects = tuple(
            object_.model_copy(
                update={"fields": tuple(sorted(object_.fields, key=lambda item: item.id))}
            )
            for object_ in sorted(self.objects, key=lambda item: item.id)
        )
        normalized = self.model_copy(
            update={
                "objects": normalized_objects,
                "relations": tuple(sorted(self.relations, key=lambda item: item.id)),
                "temporal_policies": tuple(
                    sorted(
                        self.temporal_policies,
                        key=lambda item: (item.object_id, item.partition_field_id),
                    )
                ),
                "dispositions": tuple(
                    sorted(self.dispositions, key=lambda item: item.diagnostic_id)
                ),
            }
        )
        return normalized.model_dump_json(indent=2, exclude_none=True) + "\n"


def _require_unique_ids(items: tuple[object, ...], label: str, *, attribute: str = "id") -> None:
    ids = [getattr(item, attribute) for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{label} ID 重复")


def _require_owned_field(
    object_id: str,
    field_id: str,
    object_ids: set[str],
    fields_by_id: dict[str, str],
    label: str,
) -> None:
    if object_id not in object_ids:
        raise ValueError(f"{label}引用了不存在的对象: {object_id}")
    if fields_by_id.get(field_id) != object_id:
        raise ValueError(f"{label}属性不属于对象: {field_id}")
