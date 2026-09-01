# Ontology Management Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make managed ontology drafts, immutable versions, and the active runtime snapshot survive service restarts in an explicitly configured directory outside the Git worktree.

**Architecture:** Keep the existing atomic `FileDraftStore` and `PackagePublisher`; add one startup recovery boundary that loads the active managed version before requests are served. Configuration remains external through `ONTOLOGY__MANAGEMENT_ROOT`, readiness reports a stable degraded reason, and the current local environment uses `D:\Projects\ontology-agent-data\ontology-management` without committing that path as a universal default.

**Tech Stack:** Python 3.13, FastAPI lifespan, Pydantic Settings, RDFLib ontology runtime, pytest.

## Global Constraints

- Managed ontology state must remain outside the Git worktree and must never be written to `.local`, `.worktrees`, or a system temporary directory.
- The current local runtime path is `D:\Projects\ontology-agent-data\ontology-management`; `.env.example` uses a neutral external-path example.
- An empty or unsafe management root must produce a stable degraded readiness state and a sanitized management API error.
- Startup recovery loads only the version referenced by the durable active pointer; it must not select the newest directory implicitly.
- Recovery failure must not expose filesystem paths, package contents, credentials, requirements, or SQL.
- The application must preserve the last valid snapshot when a later publish operation fails.
- The deleted temporary draft is not recoverable; rebuilding it from user source files is an explicit operational step after persistence is installed.
- Each logical change is committed separately; no automatic push or merge.

---

## File Responsibility Map

- `ontology_core/management/bootstrap.py`: one narrow startup recovery service returning sanitized runtime status.
- `ontology_core/management/service.py`: allow the bootstrap service to inject the shared `OntologyRuntime` into `PackagePublisher`.
- `api/main.py`: FastAPI lifespan calls bootstrap once; `/ready` reads the cached/current runtime health instead of performing recovery as a side effect.
- `config/settings.py`: expose a boolean indicating whether the management root was explicitly configured.
- `.env.example`: document all managed-package settings with a safe external path example.
- `docs/runbooks/ontology-management-storage.md`: local setup, restart verification, backup boundary, and recovery procedure.
- `tests/ontology_management/test_bootstrap.py`: startup recovery and sanitized failure tests.
- `tests/test_health.py`: readiness contract tests.

### Task 1: Add a testable managed-runtime bootstrap boundary

**Files:**
- Create: `ontology_core/management/bootstrap.py`
- Modify: `ontology_core/management/service.py`
- Modify: `ontology_core/management/__init__.py`
- Test: `tests/ontology_management/test_bootstrap.py`

**Interfaces:**
- Consumes: `OntologyManagementService`, `OntologyRuntime`, `RuntimeHealth`, configured root, workspace ID, repository root.
- Produces: `recover_managed_runtime(...) -> RuntimeHealth` and `ManagedRuntimeBootstrapError` with no backing path in its public message.

- [ ] **Step 1: Write failing tests for active-version recovery and sanitized configuration failure**

```python
def test_bootstrap_recovers_exact_active_version(tmp_path, synthetic_published_workspace):
    runtime = OntologyRuntime()
    health = recover_managed_runtime(
        root=synthetic_published_workspace.root,
        workspace_id="evaluation",
        repository_root=tmp_path / "repo",
        runtime=runtime,
    )
    assert health.status == "ok"
    assert runtime.snapshot().info.version == synthetic_published_workspace.version


def test_bootstrap_hides_unconfigured_root(tmp_path):
    with pytest.raises(ManagedRuntimeBootstrapError) as exc_info:
        recover_managed_runtime(
            root="",
            workspace_id="evaluation",
            repository_root=tmp_path / "repo",
            runtime=OntologyRuntime(),
        )
    assert exc_info.value.code == "ontology_runtime_bootstrap_failed"
    assert str(tmp_path) not in str(exc_info.value)
```

- [ ] **Step 2: Run the focused test and verify the new module is missing**

Run: `D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/ontology_management/test_bootstrap.py -q`

Expected: FAIL during collection because `ontology_core.management.bootstrap` does not exist.

- [ ] **Step 3: Implement the bootstrap service and runtime injection**

```python
class ManagedRuntimeBootstrapError(OntologyError):
    code = "ontology_runtime_bootstrap_failed"

    def __init__(self, *, reason: str) -> None:
        super().__init__("本体运行时恢复失败", details={"reason": reason})


def recover_managed_runtime(
    *,
    root: str | Path,
    workspace_id: str,
    repository_root: Path,
    runtime: OntologyRuntime,
) -> RuntimeHealth:
    try:
        service = OntologyManagementService(
            Path(root),
            repository_root=repository_root,
            runtime=runtime,
        )
        health = service.recover(workspace_id)
    except OntologyError as error:
        raise ManagedRuntimeBootstrapError(reason=error.code) from error
    if health.status != "ok":
        raise ManagedRuntimeBootstrapError(reason=health.reason or "recovery_failed")
    return health
```

Update `OntologyManagementService.__init__` to accept `runtime: OntologyRuntime | None = None` and construct `PackagePublisher(self._store, self.root, runtime=runtime)`.

- [ ] **Step 4: Run bootstrap and publisher tests**

Run: `D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/ontology_management/test_bootstrap.py tests/ontology_management/test_publisher.py -q`

Expected: PASS, including exact active-pointer recovery and failed-publication snapshot preservation.

- [ ] **Step 5: Commit the bootstrap boundary**

```powershell
git add ontology_core/management/bootstrap.py ontology_core/management/service.py ontology_core/management/__init__.py tests/ontology_management/test_bootstrap.py
git commit -m "feat: 启动时恢复已发布本体"
```

### Task 2: Recover runtime during FastAPI startup and make readiness side-effect free

**Files:**
- Modify: `api/main.py`
- Modify: `config/settings.py`
- Modify: `tests/test_health.py`

**Interfaces:**
- Consumes: `recover_managed_runtime`, `get_ontology_runtime().health()`, `settings.ontology.management_root`, `settings.ontology.management_workspace`.
- Produces: FastAPI lifespan startup recovery and `/ready` payload with `ontology_reason` when degraded. The startup health is retained in `app.state` only as a fallback reason; a later successful publish may replace it with the shared runtime's healthy snapshot.

- [ ] **Step 1: Write failing readiness tests**

```python
def test_ready_reports_bootstrap_reason_without_triggering_recovery(monkeypatch):
    monkeypatch.setattr("api.main.get_runtime_health", lambda: RuntimeHealth(
        status="degraded", reason="ontology_runtime_bootstrap_failed"
    ))
    response = client.get("/ready")
    assert response.json()["ontology"] == "degraded"
    assert response.json()["ontology_reason"] == "ontology_runtime_bootstrap_failed"


def test_lifespan_recovers_once(monkeypatch):
    calls = []
    monkeypatch.setattr("api.main.bootstrap_runtime", lambda: calls.append("recover"))
    with TestClient(app):
        assert calls == ["recover"]
```

- [ ] **Step 2: Run the focused tests and verify the missing lifespan behavior**

Run: `D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/test_health.py -q`

Expected: FAIL because startup does not call a bootstrap function and `/ready` has no `ontology_reason`.

- [ ] **Step 3: Implement startup recovery and readiness reporting**

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        app.state.ontology_bootstrap = bootstrap_runtime()
    except ManagedRuntimeBootstrapError as error:
        app.state.ontology_bootstrap = RuntimeHealth(
            status="degraded",
            reason=error.details.get("reason", error.code),
        )
    yield


def get_runtime_health(app: FastAPI) -> RuntimeHealth:
    current = get_ontology_runtime().health()
    if current.status == "ok":
        return current
    return getattr(app.state, "ontology_bootstrap", current)
```

Construct `FastAPI(..., lifespan=lifespan)`. Accept `Request` in `/ready`, call `get_runtime_health(request.app)`, include only its safe `reason`, and remove the request-time `service.recover(...)` call.

Add `OntologySettings.management_configured` as a read-only property returning `bool(self.management_root.strip())`; do not create a filesystem default.

- [ ] **Step 4: Run health, management API, and runtime tests**

Run: `D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/test_health.py tests/ontology_management/test_api.py tests/test_ontology_shadow.py -q`

Expected: PASS; `/health` remains `{"status": "ok"}`, while `/ready` reports database and ontology independently.

- [ ] **Step 5: Commit startup recovery**

```powershell
git add api/main.py config/settings.py tests/test_health.py
git commit -m "feat: 持久恢复本体运行时"
```

### Task 3: Document and configure the external storage contract

**Files:**
- Modify: `.env.example`
- Create: `docs/runbooks/ontology-management-storage.md`
- Create: `docs/project-journal/2026-09.md`
- Test: `tests/ontology_management/test_paths.py`

**Interfaces:**
- Consumes: `ONTOLOGY__MANAGEMENT_ROOT`, `ONTOLOGY__MANAGEMENT_WORKSPACE`, existing `resolve_management_root` safety rules.
- Produces: a reproducible local setup and restart verification procedure that never commits managed state.

- [ ] **Step 1: Add a failing configuration-documentation test**

```python
def test_env_example_documents_external_management_root() -> None:
    content = (Path(__file__).resolve().parents[2] / ".env.example").read_text("utf-8")
    assert "ONTOLOGY__MANAGEMENT_ROOT=D:/path/outside/repository/ontology-management" in content
    assert "ONTOLOGY__MANAGEMENT_WORKSPACE=evaluation" in content
```

- [ ] **Step 2: Run the test and verify the settings are absent**

Run: `D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/ontology_management/test_paths.py::test_env_example_documents_external_management_root -q`

Expected: FAIL because `.env.example` does not document the two managed-package settings.

- [ ] **Step 3: Add the environment example and runbook**

Append to `.env.example`:

```dotenv
# Managed ontology state must be outside the source repository.
ONTOLOGY__MANAGEMENT_ROOT=D:/path/outside/repository/ontology-management
ONTOLOGY__MANAGEMENT_WORKSPACE=evaluation
```

The runbook must include these exact operational checks:

```powershell
New-Item -ItemType Directory -Path 'D:\Projects\ontology-agent-data\ontology-management' -Force
Invoke-RestMethod 'http://127.0.0.1:8001/ready'
Invoke-RestMethod 'http://127.0.0.1:8001/ontology-packages/active' -Headers $headers
```

State explicitly that rebuilding a deleted draft requires re-importing source metadata and publishing a new immutable version; the service cannot reconstruct deleted business semantics from evaluation SQL.

- [ ] **Step 4: Configure and verify the current local environment outside Git**

Add this line to the ignored root `.env`, without printing the rest of the file:

```dotenv
ONTOLOGY__MANAGEMENT_ROOT=D:/Projects/ontology-agent-data/ontology-management
```

Create the directory, restart the backend, verify `/ready` reports a durable bootstrap reason before publication, then import and publish user-provided ontology source data through the existing UI. Restart once more and verify `/ontology-packages/active` returns the same package version and digest.

- [ ] **Step 5: Run path and restart-focused verification**

Run: `D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/ontology_management/test_paths.py tests/ontology_management/test_store.py tests/ontology_management/test_publisher.py tests/test_health.py -q`

Expected: PASS. Manual restart check preserves the active version; no file below `D:\Projects\ontology-agent-data\ontology-management` appears in `git status`.

- [ ] **Step 6: Record the persistence issue and commit documentation**

Append a journal entry containing only sanitized facts: temporary runtime state was lost after restart, root cause was an ephemeral management path, and the fix was explicit external storage plus startup recovery.

```powershell
git add .env.example docs/runbooks/ontology-management-storage.md docs/project-journal/2026-09.md tests/ontology_management/test_paths.py
git commit -m "docs: 固化本体持久化运行约定"
```
