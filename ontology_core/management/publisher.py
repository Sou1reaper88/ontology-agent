"""Immutable managed-package publication and coordinated runtime activation."""

from __future__ import annotations

import os
import shutil
import threading
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_hex

from pydantic import ValidationError

from agent.ontology_shadow import (
    OntologyRuntime,
    RuntimeHealth,
    get_ontology_runtime,
)
from ontology_core.errors import OntologyError
from ontology_core.management.builder import PackageBuilder
from ontology_core.management.models import VersionSummary
from ontology_core.management.paths import safe_child
from ontology_core.management.store import DraftRevisionConflict, FileDraftStore
from ontology_core.management.validation import DraftNotPublishableError
from ontology_core.repository import OntologyRepository, OntologySnapshot


class OntologyPublishError(OntologyError):
    """Raised when publication cannot complete at an operational boundary."""

    code = "ontology_publish_error"

    def __init__(self, *, operation: str) -> None:
        super().__init__("本体版本发布失败", details={"operation": operation})


class VersionAlreadyExistsError(OntologyError):
    """Raised when an immutable version identifier has already been committed."""

    code = "ontology_version_already_exists"
    status_code = 409

    def __init__(self) -> None:
        super().__init__("本体版本已存在，版本号不可复用")


class PublishedVersionNotFoundError(OntologyError):
    """Raised when an exact published version or active pointer is absent."""

    code = "published_version_not_found"
    status_code = 404

    def __init__(self) -> None:
        super().__init__("未找到已发布本体版本")


_coordination_lock = threading.RLock()
_workspace_locks_guard = threading.Lock()
_workspace_locks: dict[tuple[str, str], threading.RLock] = {}


class PackagePublisher:
    """Commit validated packages once, then switch pointer and runtime together."""

    def __init__(
        self,
        store: FileDraftStore,
        root: Path,
        runtime: OntologyRuntime | None = None,
    ) -> None:
        self._store = store
        self._root = Path(root).resolve()
        self._runtime = runtime or get_ontology_runtime()
        self._builder = PackageBuilder()

    def publish(
        self,
        workspace_id: str,
        version: str,
        release_notes: str,
        expected_revision: int,
        actor: str,
    ) -> VersionSummary:
        """Build and activate one new immutable version."""
        with self._workspace_lock(workspace_id):
            versions_dir = self._versions_dir(workspace_id)
            target = safe_child(versions_dir, version)
            if self._version_is_reserved(workspace_id, version, target):
                raise VersionAlreadyExistsError()

            draft = self._store.read(workspace_id)
            if draft.revision != expected_revision:
                raise DraftRevisionConflict(current_revision=draft.revision)

            staging = safe_child(versions_dir, f".{version}.{token_hex(16)}.staging")
            committed = False
            try:
                versions_dir.mkdir(parents=True, exist_ok=True)
                self._builder.build(draft, staging, version)
                candidate = self._load_candidate(staging)
                self._commit_version(staging, target)
                committed = True
                candidate = _snapshot_at(candidate, target)
                summary = VersionSummary(
                    version=version,
                    published_at=datetime.now(UTC),
                    actor=actor,
                    release_notes=release_notes,
                    revision=draft.revision,
                    active=True,
                )
                self._write_version_summary(workspace_id, summary)
                with _coordination_lock:
                    self._write_active_pointer(workspace_id, summary)
                    self._runtime.install(candidate)
                return summary
            except (VersionAlreadyExistsError, DraftRevisionConflict, DraftNotPublishableError):
                raise
            except Exception as error:
                operation = "activate" if committed else "prepare"
                raise OntologyPublishError(operation=operation) from error
            finally:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)

    def rollback(
        self,
        workspace_id: str,
        version: str,
        reason: str,
        actor: str,
    ) -> VersionSummary:
        """Validate and reactivate one exact immutable version without rewriting it."""
        with self._workspace_lock(workspace_id):
            target = safe_child(self._versions_dir(workspace_id), version)
            if not target.is_dir():
                raise PublishedVersionNotFoundError()
            try:
                candidate = _snapshot_at(self._load_candidate(target), target)
                original = self._read_version_summary(workspace_id, version)
                summary = VersionSummary(
                    version=version,
                    published_at=datetime.now(UTC),
                    actor=actor,
                    release_notes=reason,
                    revision=original.revision,
                    active=True,
                )
                with _coordination_lock:
                    self._write_active_pointer(workspace_id, summary)
                    self._runtime.install(candidate)
                return summary
            except PublishedVersionNotFoundError:
                raise
            except Exception as error:
                raise OntologyPublishError(operation="rollback") from error

    def recover(self, workspace_id: str) -> RuntimeHealth:
        """Load only the exact active pointer target, otherwise mark readiness degraded."""
        pointer_version: str | None = None
        with self._workspace_lock(workspace_id):
            try:
                active = self.active_version(workspace_id)
                target = safe_child(self._versions_dir(workspace_id), active.version)
                pointer_version = active.version
                if not target.is_dir():
                    raise PublishedVersionNotFoundError()
                candidate = _snapshot_at(self._load_candidate(target), target)
                with _coordination_lock:
                    self._runtime.install(candidate)
                return self._runtime.health()
            except Exception as error:
                reason = getattr(error, "code", "recovery_failed")
                with _coordination_lock:
                    self._runtime._mark_degraded(str(reason))
                health = self._runtime.health()
                return health.model_copy(update={"version": pointer_version})

    def active_version(self, workspace_id: str) -> VersionSummary:
        """Read the durable active-version pointer."""
        path = self._active_pointer_path(workspace_id)
        try:
            return VersionSummary.model_validate_json(path.read_bytes())
        except FileNotFoundError as error:
            raise PublishedVersionNotFoundError() from error
        except (OSError, ValidationError) as error:
            raise OntologyPublishError(operation="read_active_pointer") from error

    def list_versions(self, workspace_id: str) -> tuple[VersionSummary, ...]:
        """List committed versions using metadata kept outside immutable packages."""
        versions_dir = self._versions_dir(workspace_id)
        try:
            active = self.active_version(workspace_id).version
        except PublishedVersionNotFoundError:
            active = None
        if not versions_dir.is_dir():
            return ()
        summaries: list[VersionSummary] = []
        for target in sorted(versions_dir.iterdir(), key=lambda item: item.name):
            if not target.is_dir() or target.name.startswith("."):
                continue
            try:
                summary = self._read_version_summary(workspace_id, target.name)
            except PublishedVersionNotFoundError:
                continue
            summaries.append(summary.model_copy(update={"active": summary.version == active}))
        return tuple(summaries)

    def _load_candidate(self, path: Path) -> OntologySnapshot:
        repository = OntologyRepository()
        repository.publish(path)
        return repository.current()

    def _version_is_reserved(self, workspace_id: str, version: str, target: Path) -> bool:
        if target.exists() or self._version_metadata_path(workspace_id, version).exists():
            return True
        try:
            return self.active_version(workspace_id).version == version
        except PublishedVersionNotFoundError:
            return False

    @staticmethod
    def _commit_version(staging: Path, target: Path) -> None:
        staging.rename(target)

    def _write_active_pointer(self, workspace_id: str, summary: VersionSummary) -> None:
        self._atomic_json_write(self._active_pointer_path(workspace_id), summary)

    def _write_version_summary(self, workspace_id: str, summary: VersionSummary) -> None:
        path = self._version_metadata_path(workspace_id, summary.version)
        self._atomic_json_write(path, summary.model_copy(update={"active": False}))

    def _read_version_summary(self, workspace_id: str, version: str) -> VersionSummary:
        path = self._version_metadata_path(workspace_id, version)
        try:
            return VersionSummary.model_validate_json(path.read_bytes())
        except FileNotFoundError as error:
            raise PublishedVersionNotFoundError() from error
        except (OSError, ValidationError) as error:
            raise OntologyPublishError(operation="read_version_metadata") from error

    @staticmethod
    def _atomic_json_write(path: Path, model: VersionSummary) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{token_hex(16)}.tmp")
        content = (model.model_dump_json(indent=2, exclude_none=True) + "\n").encode("utf-8")
        try:
            with temporary.open("xb") as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
        except OSError:
            with suppress(OSError):
                temporary.unlink()
            raise

    def _workspace_root(self, workspace_id: str) -> Path:
        return safe_child(self._root, "workspaces", workspace_id)

    def _versions_dir(self, workspace_id: str) -> Path:
        return safe_child(self._workspace_root(workspace_id), "versions")

    def _active_pointer_path(self, workspace_id: str) -> Path:
        return safe_child(self._workspace_root(workspace_id), "active-version.json")

    def _version_metadata_path(self, workspace_id: str, version: str) -> Path:
        return safe_child(
            self._workspace_root(workspace_id),
            "version-metadata",
            f"{version}.json",
        )

    def _workspace_lock(self, workspace_id: str) -> threading.RLock:
        key = (str(self._root), workspace_id)
        with _workspace_locks_guard:
            return _workspace_locks.setdefault(key, threading.RLock())


def _snapshot_at(snapshot: OntologySnapshot, target: Path) -> OntologySnapshot:
    info = snapshot.info.model_copy(update={"source": str(target.resolve())})
    return replace(snapshot, info=info)
