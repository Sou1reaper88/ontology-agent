"""Preview and atomically confirm a batch of parsed metadata objects."""

from __future__ import annotations

import hashlib
import json
import secrets
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import PureWindowsPath
from typing import Literal

from pydantic import Field

from ontology_core.errors import OntologyError, OntologyImportError
from ontology_core.management.models import (
    DraftDiagnostic,
    DraftObject,
    ImportSession,
    UploadLimits,
    WorkspaceDraft,
)
from ontology_core.management.parsers import parse_metadata_upload
from ontology_core.management.store import DraftRevisionConflict, FileDraftStore
from ontology_core.management.validation import stable_diagnostic_id
from ontology_core.models import FrozenModel
from ontology_core.normalization import normalize_text


class UploadPayload(FrozenModel):
    """One untrusted metadata upload held only for preview parsing."""

    file_name: str = Field(min_length=1)
    content: bytes


class ImportPreview(FrozenModel):
    """A non-mutating preview, optionally carrying a single-use confirmation token."""

    status: Literal["ready", "blocked"]
    token: str | None = None
    object_count: int = Field(ge=0)
    field_count: int = Field(ge=0)
    diagnostics: tuple[DraftDiagnostic, ...] = ()


class ImportTokenExpiredError(OntologyImportError):
    code = "import_token_expired"
    status_code = 410

    def __init__(self) -> None:
        super().__init__("导入确认令牌已过期")


class ImportTokenUsedError(OntologyImportError):
    code = "import_token_used"

    def __init__(self) -> None:
        super().__init__("导入确认令牌已使用")


class ImportTokenWorkspaceMismatchError(OntologyImportError):
    code = "import_token_workspace_mismatch"

    def __init__(self) -> None:
        super().__init__("导入确认令牌不属于当前工作区")


class ImportDigestMismatchError(OntologyImportError):
    code = "import_digest_mismatch"

    def __init__(self) -> None:
        super().__init__("导入确认内容校验失败")


class DuplicateObjectInBatchError(OntologyImportError):
    code = "duplicate_object_in_batch"

    def __init__(self) -> None:
        super().__init__("导入批次包含重复对象")


class DuplicateObjectInDraftError(OntologyImportError):
    code = "duplicate_object_in_draft"

    def __init__(self) -> None:
        super().__init__("导入对象已存在于草稿")


class BatchImportService:
    """Parse, preview, and atomically append an all-or-nothing object batch."""

    def __init__(
        self,
        store: FileDraftStore,
        *,
        limits: UploadLimits,
        token_ttl: timedelta,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._limits = limits
        self._token_ttl = token_ttl
        self._now = now or (lambda: datetime.now(UTC))

    def preview(
        self,
        workspace_id: str,
        expected_revision: int,
        uploads: Sequence[UploadPayload],
    ) -> ImportPreview:
        """Parse every upload and issue a token only for a clean candidate batch."""
        draft = self._store.read(workspace_id)
        if draft.revision != expected_revision:
            raise DraftRevisionConflict(current_revision=draft.revision)

        candidates, diagnostics = self._parse_all(uploads)
        candidates = _sorted_objects(candidates)
        diagnostics.extend(_duplicate_diagnostics(draft, candidates))
        diagnostics = sorted(diagnostics, key=lambda item: item.id)
        object_count = len(candidates)
        field_count = sum(len(object_.fields) for object_ in candidates)
        if any(item.severity == "error" for item in diagnostics):
            return ImportPreview(
                status="blocked",
                object_count=object_count,
                field_count=field_count,
                diagnostics=tuple(diagnostics),
            )

        token = secrets.token_urlsafe(32)
        created_at = self._now()
        session = ImportSession(
            token_hash=_token_hash(token),
            workspace_id=workspace_id,
            expected_revision=expected_revision,
            content_digest=_candidate_digest(candidates),
            objects=candidates,
            diagnostics=tuple(diagnostics),
            created_at=created_at,
            expires_at=created_at + self._token_ttl,
        )
        self._store.write_import_session(token, session)
        return ImportPreview(
            status="ready",
            token=token,
            object_count=object_count,
            field_count=field_count,
            diagnostics=tuple(diagnostics),
        )

    def confirm(self, workspace_id: str, token: str, expected_revision: int) -> WorkspaceDraft:
        """Append all previewed objects with one revision-checked store commit."""
        session = self._store.read_import_session(token)
        self._validate_session(session, workspace_id, expected_revision)
        committed_session: ImportSession | None = None

        def append_all(current: WorkspaceDraft) -> WorkspaceDraft:
            nonlocal committed_session
            committed_session = self._store.read_import_session(token)
            self._validate_session(committed_session, workspace_id, expected_revision)
            self._assert_no_duplicates(current, committed_session.objects)
            marked_session = committed_session.model_copy(
                update={"committed_revision": current.revision + 1}
            )
            self._store.write_import_session(token, marked_session)
            committed_session = marked_session
            return current.model_copy(
                update={"objects": (*current.objects, *committed_session.objects)}
            )

        updated = self._store.commit(workspace_id, expected_revision, append_all)
        if committed_session is None:
            raise RuntimeError("导入会话未在提交锁内校验")
        self._store.consume_import_session(token)
        return updated

    def _parse_all(
        self, uploads: Sequence[UploadPayload]
    ) -> tuple[list[DraftObject], list[DraftDiagnostic]]:
        candidates: list[DraftObject] = []
        diagnostics: list[DraftDiagnostic] = []
        for upload in uploads:
            file_name = _safe_upload_name(upload.file_name)
            try:
                parsed = parse_metadata_upload(file_name, upload.content, self._limits)
            except OntologyError as error:
                diagnostics.append(_parser_error_diagnostic(error.code, file_name, error.message))
                continue
            except Exception:
                diagnostics.append(
                    _parser_error_diagnostic(
                        "metadata_parse_error",
                        file_name,
                        "上传文件解析失败",
                    )
                )
                continue
            candidates.extend(parsed.objects)
            diagnostics.extend(parsed.diagnostics)
        return candidates, diagnostics

    def _validate_session(
        self, session: ImportSession, workspace_id: str, expected_revision: int
    ) -> None:
        if session.workspace_id != workspace_id:
            raise ImportTokenWorkspaceMismatchError()
        if session.committed_revision is not None or session.consumed_at is not None:
            raise ImportTokenUsedError()
        if session.expires_at <= self._now():
            raise ImportTokenExpiredError()
        if session.expected_revision != expected_revision:
            current_revision = self._store.read(workspace_id).revision
            raise DraftRevisionConflict(current_revision=current_revision)
        if session.content_digest != _candidate_digest(session.objects):
            raise ImportDigestMismatchError()

    @staticmethod
    def _assert_no_duplicates(current: WorkspaceDraft, objects: Sequence[DraftObject]) -> None:
        identities = [physical_identity(current, object_) for object_ in objects]
        if len(identities) != len(set(identities)):
            raise DuplicateObjectInBatchError()
        existing = {physical_identity(current, object_) for object_ in current.objects}
        if existing.intersection(identities):
            raise DuplicateObjectInDraftError()


def physical_identity(draft: WorkspaceDraft, object_: DraftObject) -> tuple[str, str, str]:
    """Return the sole comparison key for a physical object in one data source."""
    return (
        normalize_text(draft.data_source.id),
        normalize_text(draft.data_source.physical_namespace),
        normalize_text(object_.physical_name),
    )


def _duplicate_diagnostics(
    draft: WorkspaceDraft, candidates: Sequence[DraftObject]
) -> list[DraftDiagnostic]:
    identities = [physical_identity(draft, object_) for object_ in candidates]
    counts = Counter(identities)
    candidate_ids = {
        identity: _unique_ids(
            object_.id for object_ in candidates if physical_identity(draft, object_) == identity
        )
        for identity in counts
    }
    diagnostics = [
        _diagnostic(
            "duplicate_object_in_batch",
            "导入批次包含重复对象",
            related_ids=candidate_ids[identity],
        )
        for identity, count in counts.items()
        if count > 1
    ]
    existing_ids = {
        identity: _unique_ids(
            object_.id for object_ in draft.objects if physical_identity(draft, object_) == identity
        )
        for identity in {physical_identity(draft, object_) for object_ in draft.objects}
    }
    diagnostics.extend(
        _diagnostic(
            "duplicate_object_in_draft",
            "导入对象已存在于草稿",
            related_ids=_unique_ids((*candidate_ids[identity], *existing_ids[identity])),
        )
        for identity in counts
        if identity in existing_ids
    )
    return diagnostics


def _parser_error_diagnostic(code: str, file_name: str, message: str) -> DraftDiagnostic:
    return _diagnostic(code, f"{file_name}：{message}")


def _diagnostic(
    code: str,
    message: str,
    *,
    related_ids: tuple[str, ...] = (),
) -> DraftDiagnostic:
    return DraftDiagnostic(
        id=stable_diagnostic_id(code, related_ids),
        code=code,
        severity="error",
        message=message,
        related_ids=related_ids,
    )


def _safe_upload_name(file_name: str) -> str:
    return PureWindowsPath(file_name.replace("/", "\\")).name


def _unique_ids(ids: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(ids))


def _candidate_digest(objects: Sequence[DraftObject]) -> str:
    payload = {
        "objects": [
            object_.model_copy(
                update={"fields": tuple(sorted(object_.fields, key=lambda field: field.id))}
            ).model_dump(mode="json", exclude_none=True)
            for object_ in _sorted_objects(objects)
        ]
    }
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sorted_objects(objects: Sequence[DraftObject]) -> tuple[DraftObject, ...]:
    return tuple(
        sorted(
            objects,
            key=lambda object_: (
                normalize_text(object_.physical_name),
                object_.physical_name,
                object_.id,
            ),
        )
    )


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
