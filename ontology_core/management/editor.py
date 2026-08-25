"""Revision-checked copy-on-write edits for workspace drafts."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from ontology_core.management.models import (
    DiagnosticDisposition,
    DraftObject,
    DraftRelation,
    DraftTemporalPolicy,
    WorkspaceDraft,
)
from ontology_core.management.store import DraftStore
from ontology_core.management.validation import DraftValidator

_UNSET = object()


class DraftEditor:
    """Apply constrained descriptive and structural mutations through ``DraftStore``."""

    def __init__(
        self,
        store: DraftStore,
        *,
        published_object_ids: Iterable[str] = (),
        validator: DraftValidator | None = None,
    ) -> None:
        self._store = store
        self._published_object_ids = frozenset(published_object_ids)
        self.validator = validator or DraftValidator()

    def update_object(
        self,
        workspace_id: str,
        object_id: str,
        *,
        expected_revision: int,
        label: str | None | object = _UNSET,
        description: str | None | object = _UNSET,
    ) -> WorkspaceDraft:
        """Update only descriptive object metadata, retaining its stable identity."""

        def mutate(draft: WorkspaceDraft) -> WorkspaceDraft:
            target = _object_by_id(draft, object_id)
            changes = _descriptive_changes(label=label, description=description)
            updated = target.model_copy(update=changes)
            return draft.model_copy(
                update={
                    "objects": tuple(
                        updated if item.id == object_id else item for item in draft.objects
                    )
                }
            )

        return self._store.commit(workspace_id, expected_revision, mutate)

    def update_field(
        self,
        workspace_id: str,
        object_id: str,
        field_id: str,
        *,
        expected_revision: int,
        label: str | None | object = _UNSET,
        description: str | None | object = _UNSET,
    ) -> WorkspaceDraft:
        """Update only descriptive field metadata, retaining physical identifiers."""

        def mutate(draft: WorkspaceDraft) -> WorkspaceDraft:
            target_object = _object_by_id(draft, object_id)
            target_field = _field_by_id(target_object, field_id)
            updated_field = target_field.model_copy(
                update=_descriptive_changes(label=label, description=description)
            )
            updated_object = target_object.model_copy(
                update={
                    "fields": tuple(
                        updated_field if item.id == field_id else item
                        for item in target_object.fields
                    )
                }
            )
            return draft.model_copy(
                update={
                    "objects": tuple(
                        updated_object if item.id == object_id else item for item in draft.objects
                    )
                }
            )

        return self._store.commit(workspace_id, expected_revision, mutate)

    def upsert_relation(
        self, workspace_id: str, relation: DraftRelation, *, expected_revision: int
    ) -> WorkspaceDraft:
        """Add or replace a relation after proving both endpoint fields are owned."""

        def mutate(draft: WorkspaceDraft) -> WorkspaceDraft:
            self._require_relation_endpoints(draft, relation)
            retained = tuple(item for item in draft.relations if item.id != relation.id)
            return _validated(draft.model_copy(update={"relations": (*retained, relation)}))

        return self._store.commit(workspace_id, expected_revision, mutate)

    def delete_relation(
        self, workspace_id: str, relation_id: str, *, expected_revision: int
    ) -> WorkspaceDraft:
        """Delete one explicitly identified relation."""

        def mutate(draft: WorkspaceDraft) -> WorkspaceDraft:
            if not any(item.id == relation_id for item in draft.relations):
                raise ValueError("未找到关系")
            return draft.model_copy(
                update={
                    "relations": tuple(item for item in draft.relations if item.id != relation_id)
                }
            )

        return self._store.commit(workspace_id, expected_revision, mutate)

    def upsert_temporal_policy(
        self, workspace_id: str, policy: DraftTemporalPolicy, *, expected_revision: int
    ) -> WorkspaceDraft:
        """Replace the table-scoped temporal policy after ownership validation."""

        def mutate(draft: WorkspaceDraft) -> WorkspaceDraft:
            self._require_owned_field(
                draft, policy.object_id, policy.partition_field_id, "时间策略"
            )
            retained = tuple(
                item for item in draft.temporal_policies if item.object_id != policy.object_id
            )
            return _validated(draft.model_copy(update={"temporal_policies": (*retained, policy)}))

        return self._store.commit(workspace_id, expected_revision, mutate)

    def delete_draft_object(
        self, workspace_id: str, object_id: str, *, expected_revision: int
    ) -> WorkspaceDraft:
        """Delete an unreferenced, never-published object and its owned fields."""

        def mutate(draft: WorkspaceDraft) -> WorkspaceDraft:
            _object_by_id(draft, object_id)
            if object_id in self._published_object_ids:
                raise ValueError("已发布对象不能通过普通编辑删除")
            if any(
                object_id in {item.source_object_id, item.target_object_id}
                for item in draft.relations
            ) or any(item.object_id == object_id for item in draft.temporal_policies):
                raise ValueError("对象仍被引用，不能删除")
            return draft.model_copy(
                update={"objects": tuple(item for item in draft.objects if item.id != object_id)}
            )

        return self._store.commit(workspace_id, expected_revision, mutate)

    def resolve_diagnostic(
        self,
        workspace_id: str,
        diagnostic_id: str,
        *,
        expected_revision: int,
        actor: str,
        explanation: str,
        resolved_at: datetime,
        status: str = "resolved",
    ) -> WorkspaceDraft:
        """Record an auditable disposition for one currently emitted diagnostic."""
        if not actor.strip():
            raise ValueError("处置人不能为空")
        if not explanation.strip():
            raise ValueError("处置说明不能为空")
        if status not in {"resolved", "dismissed"}:
            raise ValueError("诊断处置状态无效")

        def mutate(draft: WorkspaceDraft) -> WorkspaceDraft:
            if diagnostic_id not in {item.id for item in self.validator.validate(draft)}:
                raise ValueError("未找到当前诊断")
            disposition = DiagnosticDisposition(
                diagnostic_id=diagnostic_id,
                status=status,
                note=explanation,
                actor=actor,
                resolved_at=resolved_at,
            )
            retained = tuple(
                item for item in draft.dispositions if item.diagnostic_id != diagnostic_id
            )
            return draft.model_copy(update={"dispositions": (*retained, disposition)})

        return self._store.commit(workspace_id, expected_revision, mutate)

    def _require_relation_endpoints(self, draft: WorkspaceDraft, relation: DraftRelation) -> None:
        self._require_owned_field(
            draft, relation.source_object_id, relation.source_field_id, "关系源"
        )
        self._require_owned_field(
            draft, relation.target_object_id, relation.target_field_id, "关系目标"
        )

    @staticmethod
    def _require_owned_field(
        draft: WorkspaceDraft, object_id: str, field_id: str, label: str
    ) -> None:
        object_ = _object_by_id(draft, object_id)
        if not any(field.id == field_id for field in object_.fields):
            raise ValueError(f"{label}属性不属于对象")


def _descriptive_changes(
    *, label: str | None | object, description: str | None | object
) -> dict[str, str | None]:
    changes: dict[str, str | None] = {}
    if label is not _UNSET:
        changes["label"] = label if isinstance(label, str) or label is None else None
    if description is not _UNSET:
        changes["description"] = (
            description if isinstance(description, str) or description is None else None
        )
    return changes


def _object_by_id(draft: WorkspaceDraft, object_id: str) -> DraftObject:
    for object_ in draft.objects:
        if object_.id == object_id:
            return object_
    raise ValueError("未找到对象")


def _field_by_id(object_: DraftObject, field_id: str):
    for field in object_.fields:
        if field.id == field_id:
            return field
    raise ValueError("未找到属性")


def _validated(draft: WorkspaceDraft) -> WorkspaceDraft:
    return WorkspaceDraft.model_validate(draft.model_dump())
