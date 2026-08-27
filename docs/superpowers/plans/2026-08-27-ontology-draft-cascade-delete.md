# Ontology Draft Cascade Delete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add administrator-only, previewed, name-confirmed, atomic cascade deletion for draft objects and fields in the ontology workbench.

**Architecture:** The Python management editor remains the source of truth for impact calculation and performs reference removal plus target deletion in one revision-checked copy-on-write commit. FastAPI exposes safe impact previews and extends existing delete resources with an explicit cascade request. React uses one reusable confirmation modal and never computes authoritative impact counts itself.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, pytest, React 18, TypeScript, Ant Design, Axios, Vite.

## Global Constraints

- Only the “全省管理员” role may preview or execute deletion.
- Deletion must require `cascade=true`, exact physical-name confirmation, and the current `expected_revision`.
- Deletion must remove references and the target in one draft commit; no partial revisions are allowed.
- Published object and field identifiers remain immutable and cannot be deleted through ordinary draft editing.
- Audit data may contain target identifiers and aggregate counts, but not descriptions, uploaded rows, or business values.
- Do not push or merge; commit every independently working task on `codex/ontology-package-core`.
- After implementation, keep services running and verify the deletion through the real browser page rather than relying on `/health` alone.

---

## File Structure

- Modify `ontology_core/management/models.py`: define the immutable delete-impact DTO.
- Modify `ontology_core/management/editor.py`: calculate impact and perform atomic cascade mutations.
- Modify `ontology_core/management/service.py`: expose editor operations while loading published identifiers.
- Modify `ontology_core/management/__init__.py`: export the public delete-impact type.
- Modify `api/schemas/ontology_packages.py`: validate the cascade delete request.
- Modify `api/routes/ontology_packages.py`: add impact-preview routes and extend object/field delete routes.
- Modify `tests/ontology_management/test_editor.py`: prove impact calculation, atomic cascade behavior, and immutable boundaries.
- Modify `tests/ontology_management/test_api.py`: prove permissions, payload validation, revision handling, envelopes, and audit counts.
- Modify `frontend/src/features/ontology-package/types.ts`: expose the UI delete-impact model.
- Modify `frontend/src/features/ontology-package/api.ts`: map preview responses and issue Axios DELETE requests with bodies.
- Create `frontend/src/features/ontology-package/DeleteDraftModal.tsx`: own impact loading, exact-name confirmation, and delete submission UI.
- Modify `frontend/src/features/ontology-package/ObjectPanel.tsx`: add object/field delete entry points and refresh selection safely.
- Modify `frontend/tests/ontology-package-client.test.ts`: verify encoded paths, response mapping, and request payload construction.
- Modify `docs/project-journal/2026-08.md`: record the atomic-delete design and browser-path validation evidence.

---

### Task 1: Domain impact calculation and atomic cascade mutation

**Files:**
- Modify: `ontology_core/management/models.py`
- Modify: `ontology_core/management/editor.py`
- Modify: `ontology_core/management/__init__.py`
- Test: `tests/ontology_management/test_editor.py`

**Interfaces:**
- Produces: `DraftDeleteImpact(target_type, target_id, physical_name, object_count, field_count, relation_count, temporal_policy_count)`.
- Produces: `DraftEditor.object_delete_impact(workspace_id, object_id) -> DraftDeleteImpact`.
- Produces: `DraftEditor.field_delete_impact(workspace_id, object_id, field_id) -> DraftDeleteImpact`.
- Produces: `DraftEditor.delete_draft_object(..., confirmation_name: str, cascade: bool) -> WorkspaceDraft`.
- Produces: `DraftEditor.delete_draft_field(..., confirmation_name: str, cascade: bool) -> WorkspaceDraft`.

- [ ] **Step 1: Write failing editor tests for object and field impact**

Add tests that create a confirmed relation and a temporal policy, then assert authoritative counts:

```python
impact = editor.object_delete_impact("evaluation", order.id)
assert impact.model_dump() == {
    "target_type": "object",
    "target_id": order.id,
    "physical_name": "ORDER",
    "object_count": 1,
    "field_count": 3,
    "relation_count": 1,
    "temporal_policy_count": 1,
}

field_impact = editor.field_delete_impact(
    "evaluation", order.id, order.fields[2].id
)
assert field_impact.target_type == "field"
assert field_impact.field_count == 1
assert field_impact.temporal_policy_count == 1
```

- [ ] **Step 2: Run impact tests and verify RED**

Run:

```powershell
D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/ontology_management/test_editor.py -k "delete_impact" -q
```

Expected: FAIL because `object_delete_impact`, `field_delete_impact`, and `DraftDeleteImpact` do not exist.

- [ ] **Step 3: Add the impact DTO and pure impact helpers**

Add to `models.py`:

```python
class DraftDeleteImpact(FrozenModel):
    target_type: Literal["object", "field"]
    target_id: str = Field(min_length=1)
    physical_name: str = Field(min_length=1)
    object_count: int = Field(ge=0)
    field_count: int = Field(ge=0)
    relation_count: int = Field(ge=0)
    temporal_policy_count: int = Field(ge=0)
```

Implement editor methods by reading the current draft, resolving the target with `_object_by_id` / `_field_by_id`, and counting only relations and policies that directly reference the target. Export `DraftDeleteImpact` from `ontology_core.management`.

- [ ] **Step 4: Run impact tests and verify GREEN**

Run the command from Step 2.

Expected: PASS.

- [ ] **Step 5: Write failing atomic cascade and safety tests**

Replace the old reference-blocking assertions with explicit cascade behavior and retain published protection:

```python
updated = editor.delete_draft_object(
    "evaluation",
    order.id,
    expected_revision=2,
    cascade=True,
    confirmation_name="ORDER",
)
assert updated.revision == 3
assert [item.id for item in updated.objects] == [customer.id]
assert updated.relations == ()
assert updated.temporal_policies == ()
```

Add separate assertions that `cascade=False`, a mismatched `confirmation_name`, a stale revision, and a published identifier each leave the stored draft bytes and revision unchanged. Add the equivalent field case, including removal of a referencing relation or partition policy without removing sibling fields.

- [ ] **Step 6: Run cascade tests and verify RED**

Run:

```powershell
D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/ontology_management/test_editor.py -k "delet" -q
```

Expected: FAIL because delete methods do not accept or apply the cascade contract.

- [ ] **Step 7: Implement one-commit cascade deletion**

Add stable domain errors:

```python
class DraftDeleteCascadeRequiredError(OntologyError):
    code = "draft_delete_cascade_required"
    status_code = 422

    def __init__(self) -> None:
        super().__init__("删除草稿元素必须明确确认级联")


class DraftDeleteConfirmationError(OntologyError):
    code = "draft_delete_confirmation_mismatch"
    status_code = 422

    def __init__(self) -> None:
        super().__init__("删除确认名称不匹配")
```

Inside each `DraftStore.commit` mutation: resolve the current target, validate `cascade` and exact physical name, reject published identifiers, filter affected relations and policies, filter the object or field, and return `_validated(candidate)`. Do not call another editor mutation from inside the delete operation.

- [ ] **Step 8: Run editor tests and verify GREEN**

Run:

```powershell
D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/ontology_management/test_editor.py -q
```

Expected: all editor tests pass.

- [ ] **Step 9: Commit the domain task**

```powershell
git add -- ontology_core/management/models.py ontology_core/management/editor.py ontology_core/management/__init__.py tests/ontology_management/test_editor.py
git diff --cached --check
git commit -m "feat: 原子级联删除本体草稿元素"
```

---

### Task 2: Administrator API, revision checks, and audit counts

**Files:**
- Modify: `ontology_core/management/service.py`
- Modify: `api/schemas/ontology_packages.py`
- Modify: `api/routes/ontology_packages.py`
- Test: `tests/ontology_management/test_api.py`
- Test: `tests/ontology_management/test_permissions.py`

**Interfaces:**
- Consumes: all `DraftEditor` interfaces from Task 1.
- Produces: `CascadeDeleteRequest(expected_revision, cascade, confirmation_name)`.
- Produces: GET object/field `delete-impact` routes returning an API envelope.
- Produces: DELETE object/field routes accepting the cascade request and returning the updated draft envelope.

- [ ] **Step 1: Write failing API tests for preview and atomic deletion**

Use the real management service fixture to import two synthetic objects, create a relation and time policy, switch `role_name[0]` to `"全省管理员"`, and assert:

```python
current_revision = policy_response.json()["revision"]
impact = client.get(
    f"/ontology-packages/workspaces/evaluation/objects/{order['id']}/delete-impact"
)
assert impact.status_code == 200
assert impact.json()["revision"] == current_revision
assert impact.json()["data"]["relation_count"] == 1

deleted = client.request(
    "DELETE",
    f"/ontology-packages/workspaces/evaluation/objects/{order['id']}",
    json={
        "expected_revision": current_revision,
        "cascade": True,
        "confirmation_name": "SYNTHETIC_ORDER",
    },
)
assert deleted.status_code == 200
assert deleted.json()["revision"] == current_revision + 1
assert deleted.json()["data"]["relations"] == []
assert deleted.json()["data"]["temporal_policies"] == []
```

Add field equivalents and assert no partial write for stale revision or mismatched name.

- [ ] **Step 2: Write failing permission and audit tests**

Assert a maintainer receives `403` from both preview and delete. Capture `write_audit_log` and require successful deletion counts to equal the impact snapshot:

```python
assert records[0]["detail"]["counts"] == {
    "objects": 1,
    "fields": len(order["fields"]),
    "relations": 1,
    "temporal_policies": 1,
}
```

Assert the audit detail does not contain labels, descriptions, or uploaded row text.

- [ ] **Step 3: Run new API tests and verify RED**

Run:

```powershell
D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/ontology_management/test_api.py tests/ontology_management/test_permissions.py -k "delete or impact" -q
```

Expected: FAIL because preview routes and cascade request fields are absent.

- [ ] **Step 4: Implement service and request DTOs**

Add to `api/schemas/ontology_packages.py`:

```python
class CascadeDeleteRequest(RevisionRequest):
    cascade: bool
    confirmation_name: str = Field(min_length=1)

    @field_validator("confirmation_name")
    @classmethod
    def require_exact_nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("删除确认名称不能为空")
        return value
```

Expose impact and cascade delete methods from `OntologyManagementService`, passing the exact contract through to the editor.

- [ ] **Step 5: Implement routes and aggregate-only audit**

Add administrator-protected impact GET routes before the existing object/field path routes. Update DELETE handlers to accept `CascadeDeleteRequest`, fetch the impact for audit, set `_audit_context`, perform the delete, and pass impact counts to `_audit_success`.

The success counts must be built explicitly:

```python
counts = {
    "objects": impact.object_count,
    "fields": impact.field_count,
    "relations": impact.relation_count,
    "temporal_policies": impact.temporal_policy_count,
}
```

- [ ] **Step 6: Run API and permission tests and verify GREEN**

Run the command from Step 3 without the `-k` filter.

Expected: all API and permission tests pass.

- [ ] **Step 7: Run Ruff on the changed Python boundary**

```powershell
D:\Projects\ontology-agent\.venv\Scripts\python.exe -m ruff check ontology_core/management/models.py ontology_core/management/editor.py ontology_core/management/service.py api/schemas/ontology_packages.py api/routes/ontology_packages.py tests/ontology_management/test_editor.py tests/ontology_management/test_api.py tests/ontology_management/test_permissions.py
```

Expected: `All checks passed!`.

- [ ] **Step 8: Commit the API task**

```powershell
git add -- ontology_core/management/service.py api/schemas/ontology_packages.py api/routes/ontology_packages.py tests/ontology_management/test_api.py tests/ontology_management/test_permissions.py
git diff --cached --check
git commit -m "feat: 提供草稿级联删除接口"
```

---

### Task 3: Frontend API contract and reusable delete modal

**Files:**
- Modify: `frontend/src/features/ontology-package/types.ts`
- Modify: `frontend/src/features/ontology-package/api.ts`
- Create: `frontend/src/features/ontology-package/DeleteDraftModal.tsx`
- Modify: `frontend/tests/ontology-package-client.test.ts`

**Interfaces:**
- Consumes: Task 2 API envelopes and error codes.
- Produces: `DraftDeleteImpact` TypeScript interface.
- Produces: `objectDeleteImpactPath`, `fieldDeleteImpactPath`, `mapDeleteImpact`, `fetchObjectDeleteImpact`, `fetchFieldDeleteImpact`, `deleteDraftObject`, and `deleteDraftField`.
- Produces: `DeleteDraftModal` controlled component accepting a target and `onDeleted` / `onConflict` callbacks.

- [ ] **Step 1: Write failing frontend contract assertions**

Extend `ontology-package-client.test.ts`:

```typescript
equal(
  objectDeleteImpactPath("workspace / 中文", "object/alpha beta"),
  "/ontology-packages/workspaces/workspace%20%2F%20%E4%B8%AD%E6%96%87/objects/object%2Falpha%20beta/delete-impact",
  "object delete impact path is encoded"
);

const deletePayload = cascadeDeletePayload(12, "D_SAMPLE_OBJECT");
equal(String(deletePayload.expected_revision), "12", "delete payload keeps revision");
truthy(deletePayload.cascade, "delete payload explicitly enables cascade");
equal(deletePayload.confirmation_name, "D_SAMPLE_OBJECT", "delete payload keeps exact name");
```

Map a snake-case impact response and assert all four counts.

- [ ] **Step 2: Bundle and run the contract test to verify RED**

Run:

```powershell
$contractOutput = Join-Path $env:TEMP 'ontology-package-client-delete.test.cjs'
frontend/node_modules/.bin/esbuild.cmd frontend/tests/ontology-package-client.test.ts --bundle --platform=node --format=cjs --outfile=$contractOutput
node $contractOutput
```

Expected: TypeScript bundling fails because the new exports do not exist.

- [ ] **Step 3: Implement frontend types and API helpers**

Add to `types.ts`:

```typescript
export interface DraftDeleteImpact {
  targetType: "object" | "field";
  targetId: string;
  physicalName: string;
  objectCount: number;
  fieldCount: number;
  relationCount: number;
  temporalPolicyCount: number;
}
```

In `api.ts`, keep all path segments encoded through `stableSegment`, map the envelope response, and issue Axios DELETE bodies using:

```typescript
await client.delete(objectPath(workspaceId, objectId), {
  data: cascadeDeletePayload(expectedRevision, confirmationName),
});
```

- [ ] **Step 4: Run the frontend contract test and verify GREEN**

Run the command from Step 2.

Expected: process exits `0` with no thrown assertion.

- [ ] **Step 5: Implement the reusable confirmation modal**

Create `DeleteDraftModal.tsx` with this controlled target:

```typescript
export type DeleteTarget =
  | { kind: "object"; id: string; physicalName: string }
  | { kind: "field"; id: string; physicalName: string };

interface DeleteDraftModalProps {
  open: boolean;
  target: DeleteTarget | null;
  workspaceId: string;
  revision: number;
  onClose: () => void;
  onDeleted: () => Promise<void>;
  onConflict: () => Promise<void>;
}
```

When opened, fetch impact for the selected target. Render an Ant Design `Modal` with a destructive warning, four impact counts, an `Input` for the exact physical name, and a danger confirmation button disabled until the input matches. On revision conflict, close and call `onConflict`; on other failures, keep the modal safe and show `apiErrorMessage`.

- [ ] **Step 6: Run TypeScript production build**

```powershell
npm run build
```

Expected: `tsc -b` and Vite complete successfully; the existing bundle-size warning may remain.

- [ ] **Step 7: Commit frontend contract and modal**

```powershell
git add -- frontend/src/features/ontology-package/types.ts frontend/src/features/ontology-package/api.ts frontend/src/features/ontology-package/DeleteDraftModal.tsx frontend/tests/ontology-package-client.test.ts frontend/tsconfig.tsbuildinfo
git diff --cached --check
git commit -m "feat: 增加草稿删除确认组件"
```

---

### Task 4: Object and field deletion entry points

**Files:**
- Modify: `frontend/src/features/ontology-package/ObjectPanel.tsx`

**Interfaces:**
- Consumes: `DeleteDraftModal` and `DeleteTarget` from Task 3.
- Preserves: existing object/field descriptive editing and search behavior.

- [ ] **Step 1: Add delete-target state and object action**

Add:

```typescript
const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
```

Place a danger button in the object drawer footer next to “保存对象”:

```tsx
<Button
  danger
  onClick={() => selected && setDeleteTarget({
    kind: "object",
    id: selected.id,
    physicalName: selected.physicalName,
  })}
>
  删除对象
</Button>
```

- [ ] **Step 2: Add field action without removing Save**

Increase the operation column width and render both actions. The field delete button must select the exact field target and must not trigger row selection:

```tsx
<Space size={4}>
  <Button type="link" size="small" onClick={() => saveField(item)}>保存</Button>
  <Button
    type="link"
    danger
    size="small"
    onClick={() => setDeleteTarget({
      kind: "field",
      id: item.id,
      physicalName: item.physicalName,
    })}
  >
    删除
  </Button>
</Space>
```

- [ ] **Step 3: Mount modal and clear stale selection after success**

Mount one `DeleteDraftModal`. On object deletion, set `selectedId(null)` and close the edit drawer before awaiting `onChanged`; on field deletion, retain the selected object and refresh it. Always clear `deleteTarget` after success.

- [ ] **Step 4: Run frontend contract and build verification**

Run:

```powershell
$contractOutput = Join-Path $env:TEMP 'ontology-package-client-delete.test.cjs'
frontend/node_modules/.bin/esbuild.cmd frontend/tests/ontology-package-client.test.ts --bundle --platform=node --format=cjs --outfile=$contractOutput
node $contractOutput
npm --prefix frontend run build
```

Expected: contract process exits `0`; production build succeeds.

- [ ] **Step 5: Commit UI integration**

```powershell
git add -- frontend/src/features/ontology-package/ObjectPanel.tsx frontend/tsconfig.tsbuildinfo
git diff --cached --check
git commit -m "feat: 提供对象与字段删除入口"
```

---

### Task 5: Focused regression, runtime user-path acceptance, and journal

**Files:**
- Modify: `docs/project-journal/2026-08.md`

**Interfaces:**
- Consumes: complete Python API and React UI from Tasks 1–4.
- Produces: a running local version on ports `8001` and `5199`, plus reproducible engineering notes.

- [ ] **Step 1: Run focused backend regression**

```powershell
D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/ontology_management/test_editor.py tests/ontology_management/test_api.py tests/ontology_management/test_permissions.py -q
```

Expected: all selected tests pass with zero failures.

- [ ] **Step 2: Run changed-file Ruff and frontend build**

```powershell
D:\Projects\ontology-agent\.venv\Scripts\python.exe -m ruff check ontology_core/management/models.py ontology_core/management/editor.py ontology_core/management/service.py api/schemas/ontology_packages.py api/routes/ontology_packages.py tests/ontology_management/test_editor.py tests/ontology_management/test_api.py tests/ontology_management/test_permissions.py
npm --prefix frontend run build
```

Expected: Ruff reports `All checks passed!`; frontend build succeeds.

- [ ] **Step 3: Restart only the exact development service processes**

Resolve listener PIDs for `127.0.0.1:8001` and `127.0.0.1:5199`. Stop only those project processes. Start the backend from `D:\Projects\ontology-agent\.worktrees\ontology-package-core` with `ONTOLOGY__MANAGEMENT_ROOT=C:\Users\94918\AppData\Local\Temp\ontology-agent-management-dev`, after resolving the path and proving it remains outside the Git repository. Start or reuse the frontend at port `5199`. Use hidden windows for background processes.

- [ ] **Step 4: Verify the live route surface before browser work**

Check `/openapi.json` contains both delete-impact routes, then require `/health` and `/ontology` to return 200. A healthy service without the new routes is a failed acceptance.

- [ ] **Step 5: Execute the real browser deletion path**

Using only synthetic draft data in the external management root:

1. Open `/ontology`.
2. Select an object with a relation or time policy.
3. Click “删除对象” and verify impact counts are visible.
4. Verify an incorrect confirmation name keeps the final button disabled.
5. Enter the exact physical name and confirm.
6. Verify the page count decreases, references disappear, and a fresh workspace GET reports the same revision and counts.
7. Repeat the modal path for one unreferenced synthetic field, stopping before confirmation if preserving the synthetic object is useful for the user demo.

- [ ] **Step 6: Record the difficulty and evidence**

Append a journal section describing the consistency problem between mutable drafts and immutable published IDs, why the cascade is one atomic revision, how name confirmation reduces accidental deletion, and the real browser-path evidence. Do not include real table or field names.

- [ ] **Step 7: Commit journal and final metadata**

```powershell
git add -- docs/project-journal/2026-08.md frontend/tsconfig.tsbuildinfo
git diff --cached --check
git commit -m "docs: 记录草稿级联删除实践"
```

- [ ] **Step 8: Confirm a clean branch without push or merge**

```powershell
git status --short --branch
git log -6 --oneline
```

Expected: clean `codex/ontology-package-core` branch. Leave the worktree and both services available for user review.
