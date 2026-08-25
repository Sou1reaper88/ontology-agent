"""Atomic, file-backed persistence for ontology-management drafts."""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_hex
from typing import Protocol

from ontology_core.errors import OntologyError
from ontology_core.management.models import ImportSession, WorkspaceDraft
from ontology_core.management.paths import safe_child


class DraftNotFoundError(OntologyError):
    """Raised when a requested workspace draft does not exist."""

    code = "draft_not_found"
    status_code = 404

    def __init__(self) -> None:
        super().__init__("未找到本体草稿")


class DraftRevisionConflict(OntologyError):  # noqa: N818
    """Raised when a draft commit is based on an obsolete revision."""

    code = "draft_revision_conflict"
    status_code = 409

    def __init__(self, *, current_revision: int) -> None:
        super().__init__("草稿已更新，请刷新后重试", details={"current_revision": current_revision})


class ImportSessionNotFoundError(OntologyError):
    """Raised when an import session cannot be found or has been consumed."""

    code = "import_session_not_found"
    status_code = 404

    def __init__(self) -> None:
        super().__init__("未找到导入会话")


class DraftStore(Protocol):
    """Persistence boundary for mutable workspace drafts."""

    def read(self, workspace_id: str) -> WorkspaceDraft:
        """Read one workspace draft."""

    def commit(
        self,
        workspace_id: str,
        expected_revision: int,
        mutate: Callable[[WorkspaceDraft], WorkspaceDraft],
    ) -> WorkspaceDraft:
        """Atomically apply a revision-checked draft mutation."""


class FileDraftStore:
    """Store workspace drafts and single-use import sessions below one safe root."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    def create_workspace(self, draft: WorkspaceDraft) -> WorkspaceDraft:
        """Persist the initial state for a new workspace."""
        with self._lock_for(f"workspace:{draft.workspace_id}"):
            path = self._draft_path(draft.workspace_id)
            if path.exists():
                raise ValueError("本体草稿已存在")
            self._atomic_write(path, draft.canonical_json().encode("utf-8"))
        return draft

    def read(self, workspace_id: str) -> WorkspaceDraft:
        """Read one workspace draft without exposing its backing path."""
        try:
            return WorkspaceDraft.model_validate_json(self._draft_path(workspace_id).read_bytes())
        except FileNotFoundError as error:
            raise DraftNotFoundError() from error

    def commit(
        self,
        workspace_id: str,
        expected_revision: int,
        mutate: Callable[[WorkspaceDraft], WorkspaceDraft],
    ) -> WorkspaceDraft:
        """Apply a mutation only when its expected revision is current."""
        with self._lock_for(f"workspace:{workspace_id}"):
            current = self.read(workspace_id)
            if current.revision != expected_revision:
                raise DraftRevisionConflict(current_revision=current.revision)
            candidate = mutate(current).model_copy(
                update={
                    "revision": current.revision + 1,
                    "updated_at": datetime.now(UTC),
                }
            )
            self._atomic_write(
                self._draft_path(workspace_id),
                candidate.canonical_json().encode("utf-8"),
            )
            return candidate

    def write_import_session(self, token: str, session: ImportSession) -> ImportSession:
        """Persist a session under the supplied bearer token's digest only."""
        token_hash = _token_hash(token)
        if session.token_hash != token_hash:
            raise ValueError("导入会话令牌与摘要不匹配")
        with self._lock_for(f"import:{token_hash}"):
            self._atomic_write(
                self._import_session_path(token_hash),
                (session.model_dump_json(indent=2, exclude_none=True) + "\n").encode("utf-8"),
            )
        return session

    def read_import_session(self, token: str) -> ImportSession:
        """Read a session by bearer token without persisting that token."""
        token_hash = _token_hash(token)
        try:
            return ImportSession.model_validate_json(
                self._import_session_path(token_hash).read_bytes()
            )
        except FileNotFoundError as error:
            raise ImportSessionNotFoundError() from error

    def consume_import_session(self, token: str) -> ImportSession:
        """Return and delete a session so a bearer token is single-use."""
        token_hash = _token_hash(token)
        with self._lock_for(f"import:{token_hash}"):
            session = self.read_import_session(token)
            path = self._import_session_path(token_hash)
            try:
                path.unlink()
            except FileNotFoundError as error:
                raise ImportSessionNotFoundError() from error
            return session

    def _draft_path(self, workspace_id: str) -> Path:
        return safe_child(self._root, "workspaces", workspace_id, "draft.json")

    def _import_session_path(self, token_hash: str) -> Path:
        return safe_child(self._root, "import_sessions", f"{token_hash}.json")

    def _lock_for(self, key: str) -> threading.RLock:
        with self._locks_guard:
            return self._locks.setdefault(key, threading.RLock())

    def _atomic_write(self, path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{token_hex(16)}.tmp")
        try:
            with temporary.open("xb") as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
        except BaseException:
            self._remove_temporary_file(path, temporary)
            raise

    @staticmethod
    def _remove_temporary_file(path: Path, temporary: Path) -> None:
        if temporary.parent != path.parent or not temporary.name.startswith(f".{path.name}."):
            return
        with suppress(FileNotFoundError):
            temporary.unlink()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
