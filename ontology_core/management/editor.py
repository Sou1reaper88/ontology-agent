"""Revision-checked copy-on-write edits for workspace drafts."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from ontology_core.errors import OntologyError
from ontology_core.management.models import (
    DiagnosticDisposition,
    DraftDeleteImpact,
    DraftField,
    DraftObject,
    DraftRelation,
    DraftTemporalPolicy,
    WorkspaceDraft,
)
from ontology_core.management.store import DraftStore
from ontology_core.management.validation import DraftValidator

_UNSET = object()


class DraftEditValidationError(OntologyError):
    """Raised for invalid public draft-edit input without exposing internal state."""

    code = "draft_edit_validation_error"
    status_code = 422

    def __init__(self) -> None:
        super().__init__("草稿编辑请求无效")


class DraftEditReferenceConflictError(OntologyError):
    """Raised when a draft element remains referenced by another element."""

    code = "draft_edit_reference_conflict"
    status_code = 409

    def __init__(self) -> None:
        super().__init__("草稿元素仍被引用，不能删除")


class DraftEditPublishedIdentifierError(OntologyError, ValueError):
    """Raised when ordinary editing targets a published stable identifier."""

    code = "draft_edit_published_identifier"
    status_code = 409

    def __init__(self) -> None:
        super().__init__("已发布标识不能通过普通编辑删除")


class DraftDeleteCascadeRequiredError(OntologyError):
    """Raised unless a destructive edit explicitly opts into cascade behavior."""

    code = "draft_delete_cascade_required"
    status_code = 422

    def __init__(self) -> None:
        super().__init__("删除草稿元素必须明确确认级联")


class DraftDeleteConfirmationError(OntologyError):
    """Raised when the typed physical name does not match the current target."""

    code = "draft_delete_confirmation_mismatch"
    status_code = 422

    def __init__(self) -> None:
        super().__init__("删除确认名称不匹配")


class DraftDiagnosticDispositionError(OntologyError):
    """Raised when a non-confirmation diagnostic is submitted for disposition."""

    code = "draft_diagnostic_disposition_invalid"
    status_code = 422

    def __init__(self) -> None:
        super().__init__("仅确认类诊断可处置")


class DraftEditor:
    """Apply constrained descriptive and structural mutations through ``DraftStore``."""

    def __init__(
        self,
        store: DraftStore,
        *,
        published_object_ids: Iterable[str] = (),
        published_field_ids: Iterable[str] = (),
        validator: DraftValidator | None = None,
    ) -> None:
        self._store = store
        self._published_object_ids = frozenset(published_object_ids)
        self._published_field_ids = frozenset(published_field_ids)
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
        changes = _descriptive_changes(label=label, description=description)

        def mutate(draft: WorkspaceDraft) -> WorkspaceDraft:
            target = _object_by_id(draft, object_id)
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
        changes = _descriptive_changes(label=label, description=description)

        def mutate(draft: WorkspaceDraft) -> WorkspaceDraft:
            target_object = _object_by_id(draft, object_id)
            target_field = _field_by_id(target_object, field_id)
            updated_field = target_field.model_copy(update=changes)
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
        self,
        workspace_id: str,
        object_id: str,
        *,
        expected_revision: int,
        cascade: bool,
        confirmation_name: str,
    ) -> WorkspaceDraft:
        """Atomically delete a never-published object and all draft references."""

        def mutate(draft: WorkspaceDraft) -> WorkspaceDraft:
            object_ = _object_by_id(draft, object_id)
            _require_delete_confirmation(object_.physical_name, cascade, confirmation_name)
            if object_id in self._published_object_ids or any(
                field.id in self._published_field_ids for field in object_.fields
            ):
                raise DraftEditPublishedIdentifierError()
            return _validated(
                draft.model_copy(
                    update={
                        "objects": tuple(
                            item for item in draft.objects if item.id != object_id
                        ),
                        "relations": tuple(
                            item
                            for item in draft.relations
                            if object_id not in {item.source_object_id, item.target_object_id}
                        ),
                        "temporal_policies": tuple(
                            item
                            for item in draft.temporal_policies
                            if item.object_id != object_id
                        ),
                    }
                )
            )

        return self._store.commit(workspace_id, expected_revision, mutate)

    def delete_draft_field(
        self,
        workspace_id: str,
        object_id: str,
        field_id: str,
        *,
        expected_revision: int,
        cascade: bool,
        confirmation_name: str,
    ) -> WorkspaceDraft:
        """Atomically delete an unpublished field and all draft references."""

        def mutate(draft: WorkspaceDraft) -> WorkspaceDraft:
            object_ = _object_by_id(draft, object_id)
            field = _field_by_id(object_, field_id)
            _require_delete_confirmation(field.physical_name, cascade, confirmation_name)
            if object_id in self._published_object_ids or field_id in self._published_field_ids:
                raise DraftEditPublishedIdentifierError()
            updated_object = object_.model_copy(
                update={"fields": tuple(item for item in object_.fields if item.id != field_id)}
            )
            return _validated(
                draft.model_copy(
                    update={
                        "objects": tuple(
                            updated_object if item.id == object_id else item
                            for item in draft.objects
                        ),
                        "relations": tuple(
                            item
                            for item in draft.relations
                            if field_id not in {item.source_field_id, item.target_field_id}
                        ),
                        "temporal_policies": tuple(
                            item
                            for item in draft.temporal_policies
                            if item.partition_field_id != field_id
                        ),
                    }
                )
            )

        return self._store.commit(workspace_id, expected_revision, mutate)

    def object_delete_impact(self, workspace_id: str, object_id: str) -> DraftDeleteImpact:
        """Calculate current aggregate impact for deleting one draft object."""
        draft = self._store.read(workspace_id)
        object_ = _object_by_id(draft, object_id)
        return DraftDeleteImpact(
            target_type="object",
            target_id=object_.id,
            physical_name=object_.physical_name,
            object_count=1,
            field_count=len(object_.fields),
            relation_count=sum(
                object_id in {item.source_object_id, item.target_object_id}
                for item in draft.relations
            ),
            temporal_policy_count=sum(
                item.object_id == object_id for item in draft.temporal_policies
            ),
        )

    def field_delete_impact(
        self, workspace_id: str, object_id: str, field_id: str
    ) -> DraftDeleteImpact:
        """Calculate current aggregate impact for deleting one draft field."""
        draft = self._store.read(workspace_id)
        object_ = _object_by_id(draft, object_id)
        field = _field_by_id(object_, field_id)
        return DraftDeleteImpact(
            target_type="field",
            target_id=field.id,
            physical_name=field.physical_name,
            object_count=0,
            field_count=1,
            relation_count=sum(
                field_id in {item.source_field_id, item.target_field_id}
                for item in draft.relations
            ),
            temporal_policy_count=sum(
                item.partition_field_id == field_id for item in draft.temporal_policies
            ),
        )

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
            diagnostic = next(
                (item for item in self.validator.validate(draft) if item.id == diagnostic_id),
                None,
            )
            if diagnostic is None:
                raise ValueError("未找到当前诊断")
            if diagnostic.severity != "confirmation_required":
                raise DraftDiagnosticDispositionError()
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
        changes["label"] = _descriptive_value(label)
    if description is not _UNSET:
        changes["description"] = _descriptive_value(description)
    return changes


def _object_by_id(draft: WorkspaceDraft, object_id: str) -> DraftObject:
    for object_ in draft.objects:
        if object_.id == object_id:
            return object_
    raise ValueError("未找到对象")


def _field_by_id(object_: DraftObject, field_id: str) -> DraftField:
    for field in object_.fields:
        if field.id == field_id:
            return field
    raise ValueError("未找到属性")


def _validated(draft: WorkspaceDraft) -> WorkspaceDraft:
    return WorkspaceDraft.model_validate(draft.model_dump())


def _descriptive_value(value: str | None | object) -> str | None:
    if isinstance(value, str) or value is None:
        return value
    raise DraftEditValidationError()


def _require_delete_confirmation(
    physical_name: str, cascade: bool, confirmation_name: str
) -> None:
    if not cascade:
        raise DraftDeleteCascadeRequiredError()
    if confirmation_name != physical_name:
        raise DraftDeleteConfirmationError()
