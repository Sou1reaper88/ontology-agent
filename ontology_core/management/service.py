"""Thin composition façade for managed ontology package operations."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from urllib.parse import unquote

from ontology_core.errors import OntologyError
from ontology_core.management.editor import DraftEditor
from ontology_core.management.imports import BatchImportService, ImportPreview, UploadPayload
from ontology_core.management.models import (
    DraftDeleteImpact,
    DraftDiagnostic,
    DraftRelation,
    DraftTemporalPolicy,
    UploadLimits,
    VersionSummary,
    WorkspaceDraft,
)
from ontology_core.management.paths import OntologyManagementConfigurationError, safe_child
from ontology_core.management.publisher import PackagePublisher, PublishedVersionNotFoundError
from ontology_core.management.store import FileDraftStore
from ontology_core.management.templates import GeneratedImportTemplate, build_import_template
from ontology_core.management.validation import DraftValidator
from ontology_core.repository import OntologyRepository


class OntologyManagementUnavailableError(OntologyError):
    """Report an unavailable external management root without exposing paths."""

    code = "ontology_management_unavailable"
    status_code = 503

    def __init__(self) -> None:
        super().__init__("本体管理服务当前不可用")


class DraftFieldNotFoundError(OntologyError):
    """Report a missing draft field through the stable management API envelope."""

    code = "draft_field_not_found"
    status_code = 404

    def __init__(self) -> None:
        super().__init__("未找到属性")


@dataclass(frozen=True)
class WorkspaceOverview:
    """Public service result composed from a draft and immutable version summaries."""

    draft: WorkspaceDraft
    diagnostics: tuple[DraftDiagnostic, ...]
    active_version: VersionSummary | None
    versions: tuple[VersionSummary, ...]

    def public_data(self) -> dict[str, object]:
        """Return only structured public draft state, never backing filesystem data."""
        return {
            "workspace_id": self.draft.workspace_id,
            "display_name": self.draft.display_name,
            "package_id": self.draft.package_id,
            "data_source": self.draft.data_source.model_dump(mode="json"),
            "objects": [item.model_dump(mode="json") for item in self.draft.objects],
            "relations": [item.model_dump(mode="json") for item in self.draft.relations],
            "temporal_policies": [
                item.model_dump(mode="json") for item in self.draft.temporal_policies
            ],
            "dispositions": [item.model_dump(mode="json") for item in self.draft.dispositions],
            "diagnostics": [item.model_dump(mode="json") for item in self.diagnostics],
            "active_version": (
                self.active_version.model_dump(mode="json") if self.active_version else None
            ),
            "counts": {
                "objects": len(self.draft.objects),
                "fields": sum(len(item.fields) for item in self.draft.objects),
                "relations": len(self.draft.relations),
                "temporal_policies": len(self.draft.temporal_policies),
            },
        }


class OntologyManagementService:
    """Compose existing import, editor, validator, and publisher services."""

    def __init__(
        self,
        root: Path,
        *,
        repository_root: Path | None = None,
        limits: UploadLimits | None = None,
        import_token_ttl: timedelta = timedelta(minutes=15),
    ) -> None:
        try:
            self._store = FileDraftStore(root, repository_root=repository_root)
        except OntologyManagementConfigurationError as error:
            raise OntologyManagementUnavailableError() from error
        self.root = Path(root).resolve()
        self._validator = DraftValidator()
        self._imports = BatchImportService(
            self._store,
            limits=limits
            or UploadLimits(
                max_upload_bytes=20 * 1024 * 1024,
                max_xlsx_uncompressed_bytes=100 * 1024 * 1024,
            ),
            token_ttl=import_token_ttl,
        )
        self._publisher = PackagePublisher(self._store, self.root)

    @staticmethod
    def upload_payload(file_name: str, content: bytes) -> UploadPayload:
        """Create the existing import DTO without exposing route parsing internally."""
        return UploadPayload(file_name=file_name, content=content)

    def overview(self, workspace_id: str) -> WorkspaceOverview:
        draft = self._store.read(workspace_id)
        try:
            active = self._publisher.active_version(workspace_id)
        except PublishedVersionNotFoundError:
            active = None
        return WorkspaceOverview(
            draft=draft,
            diagnostics=self._validator.validate(draft),
            active_version=active,
            versions=self._publisher.list_versions(workspace_id),
        )

    def draft_revision(self, workspace_id: str) -> int:
        """Read only the current persisted draft revision for audit correlation."""
        return self._store.read(workspace_id).revision

    def import_template(self, workspace_id: str, variant: str) -> GeneratedImportTemplate:
        """Generate a sample only after confirming the requested workspace exists."""
        self._store.read(workspace_id)
        return build_import_template(variant)

    def preview_import(
        self, workspace_id: str, *, expected_revision: int, uploads: tuple[UploadPayload, ...]
    ) -> ImportPreview:
        return self._imports.preview(workspace_id, expected_revision, uploads)

    def confirm_import(
        self, workspace_id: str, token: str, *, expected_revision: int
    ) -> WorkspaceDraft:
        return self._imports.confirm(workspace_id, token, expected_revision)

    def update_object(
        self,
        workspace_id: str,
        object_id: str,
        *,
        expected_revision: int,
        changes: dict[str, str | None],
    ) -> WorkspaceDraft:
        return self._editor_for(workspace_id).update_object(
            workspace_id, object_id, expected_revision=expected_revision, **changes
        )

    def update_field(
        self,
        workspace_id: str,
        field_id: str,
        *,
        expected_revision: int,
        changes: dict[str, str | None],
    ) -> WorkspaceDraft:
        return self._editor_for(workspace_id).update_field(
            workspace_id,
            self._field_owner(workspace_id, field_id),
            field_id,
            expected_revision=expected_revision,
            **changes,
        )

    def upsert_relation(
        self, workspace_id: str, relation: DraftRelation, *, expected_revision: int
    ) -> WorkspaceDraft:
        return self._editor_for(workspace_id).upsert_relation(
            workspace_id, relation, expected_revision=expected_revision
        )

    def delete_relation(
        self, workspace_id: str, relation_id: str, *, expected_revision: int
    ) -> WorkspaceDraft:
        return self._editor_for(workspace_id).delete_relation(
            workspace_id, relation_id, expected_revision=expected_revision
        )

    def upsert_temporal_policy(
        self, workspace_id: str, policy: DraftTemporalPolicy, *, expected_revision: int
    ) -> WorkspaceDraft:
        return self._editor_for(workspace_id).upsert_temporal_policy(
            workspace_id, policy, expected_revision=expected_revision
        )

    def delete_object(
        self,
        workspace_id: str,
        object_id: str,
        *,
        expected_revision: int,
        cascade: bool,
        confirmation_name: str,
    ) -> WorkspaceDraft:
        return self._editor_for(workspace_id).delete_draft_object(
            workspace_id,
            object_id,
            expected_revision=expected_revision,
            cascade=cascade,
            confirmation_name=confirmation_name,
        )

    def object_delete_impact(
        self, workspace_id: str, object_id: str
    ) -> DraftDeleteImpact:
        return self._editor_for(workspace_id).object_delete_impact(workspace_id, object_id)

    def delete_field(
        self,
        workspace_id: str,
        field_id: str,
        *,
        expected_revision: int,
        cascade: bool,
        confirmation_name: str,
    ) -> WorkspaceDraft:
        return self._editor_for(workspace_id).delete_draft_field(
            workspace_id,
            self._field_owner(workspace_id, field_id),
            field_id,
            expected_revision=expected_revision,
            cascade=cascade,
            confirmation_name=confirmation_name,
        )

    def field_delete_impact(self, workspace_id: str, field_id: str) -> DraftDeleteImpact:
        return self._editor_for(workspace_id).field_delete_impact(
            workspace_id,
            self._field_owner(workspace_id, field_id),
            field_id,
        )

    def resolve_diagnostic(
        self,
        workspace_id: str,
        diagnostic_id: str,
        *,
        expected_revision: int,
        actor: str,
        explanation: str,
        status: str,
    ) -> WorkspaceDraft:
        from datetime import UTC, datetime

        return self._editor_for(workspace_id).resolve_diagnostic(
            workspace_id,
            diagnostic_id,
            expected_revision=expected_revision,
            actor=actor,
            explanation=explanation,
            resolved_at=datetime.now(UTC),
            status=status,
        )

    def validate(self, workspace_id: str) -> tuple[DraftDiagnostic, ...]:
        return self._validator.validate(self._store.read(workspace_id))

    def publish(
        self,
        workspace_id: str,
        version: str,
        release_notes: str,
        expected_revision: int,
        actor: str,
    ) -> VersionSummary:
        return self._publisher.publish(
            workspace_id, version, release_notes, expected_revision, actor
        )

    def rollback(self, workspace_id: str, version: str, reason: str, actor: str) -> VersionSummary:
        return self._publisher.rollback(workspace_id, version, reason, actor)

    def list_versions(self, workspace_id: str) -> tuple[VersionSummary, ...]:
        return self._publisher.list_versions(workspace_id)

    def active_version(self, workspace_id: str) -> VersionSummary:
        return self._publisher.active_version(workspace_id)

    def recover(self, workspace_id: str):
        return self._publisher.recover(workspace_id)

    def _editor_for(self, workspace_id: str) -> DraftEditor:
        object_ids, field_ids = self._published_identifiers(workspace_id)
        return DraftEditor(
            self._store,
            published_object_ids=object_ids,
            published_field_ids=field_ids,
            validator=self._validator,
        )

    def _published_identifiers(self, workspace_id: str) -> tuple[frozenset[str], frozenset[str]]:
        """Read all immutable published catalogs on every editor construction.

        Catalog URIs retain the stable managed IDs, so protections survive a process restart and
        do not rely on an in-memory publisher history.
        """
        object_ids: set[str] = set()
        field_ids: set[str] = set()
        versions_dir = safe_child(self.root, "workspaces", workspace_id, "versions")
        for summary in self._publisher.list_versions(workspace_id):
            repository = OntologyRepository()
            repository.publish(safe_child(versions_dir, summary.version))
            catalog = repository.current().catalog
            object_ids.update(_managed_ids((item.uri for item in catalog.concepts), "concept"))
            field_ids.update(_managed_ids((item.uri for item in catalog.properties), "property"))
        return frozenset(object_ids), frozenset(field_ids)

    def _field_owner(self, workspace_id: str, field_id: str) -> str:
        for object_ in self._store.read(workspace_id).objects:
            if any(field.id == field_id for field in object_.fields):
                return object_.id
        raise DraftFieldNotFoundError()


def _managed_ids(uris: Iterable[str], category: str) -> set[str]:
    marker = f"/{category}/"
    stable_ids: set[str] = set()
    for uri in uris:
        _, separator, encoded = uri.rpartition(marker)
        if not separator or not encoded:
            raise OntologyManagementUnavailableError()
        stable_ids.add(unquote(encoded))
    return stable_ids
