# Conversation Feedback Retention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add durable per-message SQL feedback, a maintainer review panel, and remove the non-editable automatic-period UI while preserving backend period inference.

**Architecture:** Store one feedback row per assistant SQL message and expose a small authenticated feedback API. Reuse conversation ownership for writes, the existing ontology maintainer dependency for aggregate reads, and the existing chat/workbench components for presentation; no LLM call or knowledge automation is introduced.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy, Alembic, Pydantic, React 18, TypeScript, Ant Design, Axios, pytest, esbuild/Vite.

## Global Constraints

- Only completed assistant messages containing SQL can receive feedback.
- `correct` stores the generated SQL; `needs_revision` requires a non-empty note and accepts an optional final SQL.
- One message has at most one feedback row; resubmission updates it.
- Deleting a conversation deletes its feedback; published ontology content remains independent.
- Users can write and remove only their own feedback; ontology maintainers and administrators can read all feedback.
- Feedback actions never call an LLM, infer frequency, cluster requirements, or modify ontology drafts.
- Remove only the automatic-period workbench UI and metric; keep `_D`/`_M` inference, historical data, publishing, and compatibility APIs.
- Add no dependency and no speculative interface for future Reflection.
- Do not stage `frontend/tsconfig.tsbuildinfo`, `.codex-artifacts/`, or `docs/prompts/`.
- Run focused checks only; do not rerun the seven real requirements, call paid models, execute business SQL, or perform a broad audit.
- Commit and push each completed task to `main`.

---

## File Structure

- Create `models/message_feedback.py`: one SQL feedback record per assistant message.
- Create `alembic/versions/b74e9f1c2a60_add_message_feedback.py`: schema, uniqueness, indexes, and cascading foreign keys.
- Create `api/routes/feedback.py`: owned write/delete endpoints and maintainer aggregate list.
- Modify `models/conversation_message.py`: one-to-one ORM relationship so ORM deletes also cascade in tests.
- Modify `models/__init__.py`: export the new model for application and Alembic metadata.
- Modify `api/routes/conversation.py`: include feedback in historical message responses.
- Modify `api/main.py`: register the feedback router.
- Create `tests/test_message_feedback.py`: API, authorization, validation, upsert, and cascade coverage.
- Create `frontend/src/features/chat/feedback.ts`: feedback types, request helpers, and note validation.
- Create `frontend/src/features/chat/MessageFeedbackControls.tsx`: correct/revision/withdraw interactions.
- Modify `frontend/src/features/chat/types.ts` and `MessageTimeline.tsx`: carry and render feedback.
- Create `frontend/tests/chat-feedback.test.ts`: feedback path and validation contract.
- Create `frontend/src/features/ontology-package/FeedbackPanel.tsx`: maintainer feedback table and detail modal.
- Modify `frontend/src/features/ontology-package/api.ts` and `types.ts`: aggregate feedback response mapping.
- Modify `frontend/src/features/ontology-package/OntologyWorkbench.tsx`, `WorkbenchShell.tsx`, and `workbenchModel.ts`: add feedback stage and remove automatic-period UI/metric.
- Modify `frontend/src/features/ontology-package/DiagnosticsPanel.tsx` and `diagnosticRouting.ts`: route period-related diagnostics to objects after the period panel is removed.
- Delete `frontend/src/features/ontology-package/TemporalPanel.tsx`: remove the non-editable panel only.
- Modify `frontend/src/pages/Chat.tsx`: open a conversation specified by the feedback panel query parameter.
- Modify `frontend/tests/ontology-workbench-model.test.ts`: stage order and diagnostic destination contract.
- Modify `docs/project-journal/2026-09.md`: record the feedback boundary, deletion semantics, and UI simplification.

---

### Task 1: Persist and authorize message feedback

**Files:**
- Create: `models/message_feedback.py`
- Create: `alembic/versions/b74e9f1c2a60_add_message_feedback.py`
- Create: `api/routes/feedback.py`
- Create: `tests/test_message_feedback.py`
- Modify: `models/conversation_message.py`
- Modify: `models/__init__.py`
- Modify: `api/routes/conversation.py`
- Modify: `api/main.py`

**Interfaces:**
- Produces: `MessageFeedback(message_id, user_id, status, note, final_sql)` with one row per message.
- Produces: `PUT /feedback/messages/{message_id}`, `DELETE /feedback/messages/{message_id}`, and maintainer-only `GET /feedback?status=...`.
- Produces: `MessageOut.feedback` with `{id, status, note, final_sql, created_at, updated_at}` or `null`.
- Consumes: existing `get_current_user`, `require_ontology_maintainer`, `Conversation`, `ConversationMessage`, and message trace payloads.

- [ ] **Step 1: Write focused failing API tests**

Create `tests/test_message_feedback.py` with a database helper that inserts one user message and one completed assistant SQL message for the authenticated admin. Cover the exact contracts below:

```python
from models import Conversation, ConversationMessage, MessageFeedback, User
from models.base import SessionLocal


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def seed_completed_sql_message(username: str) -> tuple[int, int, str]:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).one()
        conversation = Conversation(user_id=user.id, title="反馈测试")
        db.add(conversation)
        db.flush()
        db.add(
            ConversationMessage(
                conversation_id=conversation.id,
                role="user",
                content="查询测试用户",
            )
        )
        sql = "DROP TABLE IF EXISTS temp_oa_test_result_table;\nCREATE TABLE temp_oa_test_result_table AS SELECT 1 AS user_id;"
        answer = ConversationMessage(
            conversation_id=conversation.id,
            role="assistant",
            content="已生成取数脚本。",
            sql=sql,
            trace=[],
        )
        db.add(answer)
        db.commit()
        db.refresh(answer)
        return conversation.id, answer.id, sql
    finally:
        db.close()


def seed_assistant_message_without_sql(username: str) -> int:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).one()
        conversation = Conversation(user_id=user.id, title="普通问答测试")
        db.add(conversation)
        db.flush()
        answer = ConversationMessage(
            conversation_id=conversation.id,
            role="assistant",
            content="请补充取数范围。",
            sql=None,
            trace=[],
        )
        db.add(answer)
        db.commit()
        db.refresh(answer)
        return answer.id
    finally:
        db.close()


def test_correct_feedback_is_upserted_and_returned_with_history(client, admin_token):
    conversation_id, message_id, sql = seed_completed_sql_message("admin")
    response = client.put(
        f"/feedback/messages/{message_id}",
        json={"status": "correct"},
        headers=auth(admin_token),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "correct"
    assert response.json()["final_sql"] == sql

    updated = client.put(
        f"/feedback/messages/{message_id}",
        json={
            "status": "needs_revision",
            "note": "有效用户还要排除测试号码",
            "final_sql": sql + "\n-- corrected",
        },
        headers=auth(admin_token),
    )
    assert updated.status_code == 200
    assert updated.json()["id"] == response.json()["id"]

    history = client.get(f"/conversations/{conversation_id}", headers=auth(admin_token))
    answer = next(item for item in history.json()["messages"] if item["id"] == message_id)
    assert answer["feedback"]["status"] == "needs_revision"


def test_revision_feedback_requires_note_and_sql_message_ownership(client, admin_token):
    _, message_id, _ = seed_completed_sql_message("admin")
    missing_note = client.put(
        f"/feedback/messages/{message_id}",
        json={"status": "needs_revision", "note": "   "},
        headers=auth(admin_token),
    )
    assert missing_note.status_code == 422

    no_sql_id = seed_assistant_message_without_sql("admin")
    no_sql = client.put(
        f"/feedback/messages/{no_sql_id}",
        json={"status": "correct"},
        headers=auth(admin_token),
    )
    assert no_sql.status_code == 409


def test_feedback_list_is_maintainer_only_and_conversation_delete_cascades(client, admin_token):
    conversation_id, message_id, _ = seed_completed_sql_message("admin")
    saved = client.put(
        f"/feedback/messages/{message_id}",
        json={"status": "correct"},
        headers=auth(admin_token),
    )
    feedback_id = saved.json()["id"]

    listing = client.get("/feedback?status=correct", headers=auth(admin_token))
    assert listing.status_code == 200
    row = next(item for item in listing.json() if item["id"] == feedback_id)
    assert row["conversation_id"] == conversation_id
    assert row["message_id"] == message_id
    assert row["request_text"] == "查询测试用户"
    assert row["ontology_version"] in {None, "test-version"}

    assert client.delete(f"/conversations/{conversation_id}", headers=auth(admin_token)).status_code == 204
    assert not any(item["id"] == feedback_id for item in client.get("/feedback", headers=auth(admin_token)).json())
```

Add an autouse cleanup fixture scoped to this test module that records seeded conversation IDs and deletes those conversations after each test. Create a temporary ordinary-role user using the existing `Role(name="地市生产岗")`, issue a token with `create_access_token`, then assert that this user receives `403` from `GET /feedback` and `404` when attempting to write another user's message. Delete the temporary user after the assertion.

- [ ] **Step 2: Run the new tests and confirm the missing feature**

Run:

```powershell
\.venv\Scripts\python.exe -m pytest tests/test_message_feedback.py -q
```

Expected: collection or request assertions fail because `MessageFeedback` and `/feedback` do not exist.

- [ ] **Step 3: Add the model and migration**

Implement `models/message_feedback.py` with these exact persisted fields and constraints:

```python
class MessageFeedback(Base):
    __tablename__ = "message_feedback"
    __table_args__ = (
        CheckConstraint(
            "status IN ('correct', 'needs_revision')",
            name="ck_message_feedback_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("conversation_messages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    message: Mapped["ConversationMessage"] = relationship(back_populates="feedback")
```

Add a one-to-one `ConversationMessage.feedback` relationship using `uselist=False`, `cascade="all, delete-orphan"`, and `single_parent=True`. Export `MessageFeedback` from `models/__init__.py`.

Create migration `b74e9f1c2a60_add_message_feedback.py` with `down_revision = "f93b2c14d8e7"`, the same columns/check constraint, cascading foreign keys, a unique constraint on `message_id`, and indexes on `message_id`, `user_id`, and `status`. Downgrade drops indexes before the table.

- [ ] **Step 4: Implement the minimal API and history response**

In `api/routes/feedback.py`, define:

```python
router = APIRouter(prefix="/feedback", tags=["feedback"])
FeedbackStatus = Literal["correct", "needs_revision"]


class FeedbackWrite(BaseModel):
    status: FeedbackStatus
    note: str | None = None
    final_sql: str | None = None

    @model_validator(mode="after")
    def require_revision_note(self):
        self.note = self.note.strip() if self.note else None
        if self.status == "needs_revision" and not self.note:
            raise ValueError("需要修改时必须填写问题说明或补充口径")
        return self
```

The owned-message helper must join `ConversationMessage` to `Conversation`, filter by `Conversation.user_id == user.id`, return `404` for missing/foreign messages, and reject non-assistant or SQL-empty messages with `409`.

The `PUT` endpoint must upsert by `message_id`. For `correct`, force `note=None` and `final_sql=message.sql`; for `needs_revision`, store the stripped note and stripped optional `final_sql`. The `DELETE` endpoint must be idempotent after owned-message validation.

The maintainer `GET` endpoint must order by `updated_at DESC`, optionally filter by status, and return:

```python
{
    "id": feedback.id,
    "conversation_id": message.conversation_id,
    "message_id": message.id,
    "status": feedback.status,
    "request_text": nearest_preceding_user_message.content,
    "generated_sql": message.sql,
    "note": feedback.note,
    "final_sql": feedback.final_sql,
    "ontology_version": ontology_version_from_trace_or_none,
    "username": user.username,
    "created_at": feedback.created_at.isoformat(),
    "updated_at": feedback.updated_at.isoformat(),
}
```

Extract `ontology_version` only from an existing trace `package.version`; do not call runtime services or reconstruct a version. Register the router in `api/main.py`.

Add a compact `FeedbackSummary` model to `api/routes/conversation.py`, add `feedback: FeedbackSummary | None = None` to `MessageOut`, and map `m.feedback` in `get_conversation`.

- [ ] **Step 5: Run focused backend tests**

Run:

```powershell
\.venv\Scripts\python.exe -m pytest tests/test_message_feedback.py tests/test_conversation.py -q
```

Expected: all selected tests pass; no real model call and no business SQL execution occurs.

- [ ] **Step 6: Commit and push Task 1**

Run:

```powershell
git add -- models/message_feedback.py models/conversation_message.py models/__init__.py alembic/versions/b74e9f1c2a60_add_message_feedback.py api/routes/feedback.py api/routes/conversation.py api/main.py tests/test_message_feedback.py
git diff --cached --check
git commit -m "feat: retain SQL message feedback"
git push
```

Expected: only Task 1 files are committed and `main` is pushed.

---

### Task 2: Add feedback controls to SQL answers

**Files:**
- Create: `frontend/src/features/chat/feedback.ts`
- Create: `frontend/src/features/chat/MessageFeedbackControls.tsx`
- Create: `frontend/tests/chat-feedback.test.ts`
- Modify: `frontend/src/features/chat/types.ts`
- Modify: `frontend/src/features/chat/MessageTimeline.tsx`
- Modify: `frontend/src/features/chat/chat-components.css`
- Modify: `frontend/src/pages/Chat.tsx`

**Interfaces:**
- Consumes: Task 1 message-level feedback endpoints and `MessageOut.feedback`.
- Produces: `MessageFeedback`, `FeedbackStatus`, `feedbackPath(messageId)`, `feedbackValidationMessage(status, note)`, and `MessageFeedbackControls`.

- [ ] **Step 1: Write the failing frontend contract test**

Create `frontend/tests/chat-feedback.test.ts`:

```typescript
import {
  feedbackPath,
  feedbackValidationMessage,
} from "../src/features/chat/feedback";

if (feedbackPath(27) !== "/feedback/messages/27") {
  throw new Error("feedback path must be message scoped");
}
if (feedbackValidationMessage("correct", "") !== null) {
  throw new Error("correct feedback needs no note");
}
if (feedbackValidationMessage("needs_revision", "   ") !== "请填写问题说明或补充口径") {
  throw new Error("revision feedback must require a note");
}
if (feedbackValidationMessage("needs_revision", "字段口径有误") !== null) {
  throw new Error("revision feedback accepts a non-empty note");
}
```

- [ ] **Step 2: Run the contract test and verify it fails**

Run from `frontend`:

```powershell
$testOut = Join-Path ([System.IO.Path]::GetTempPath()) 'chat-feedback-test.cjs'
& '.\node_modules\.bin\esbuild.cmd' '.\tests\chat-feedback.test.ts' --bundle --platform=node --format=cjs --outfile=$testOut
node $testOut
```

Expected: esbuild fails because `src/features/chat/feedback.ts` does not exist.

- [ ] **Step 3: Add feedback types and request helpers**

Create `feedback.ts` with:

```typescript
import client from "../../api/client";

export type FeedbackStatus = "correct" | "needs_revision";
export interface MessageFeedback {
  id: number;
  status: FeedbackStatus;
  note: string | null;
  final_sql: string | null;
  created_at: string;
  updated_at: string;
}

export const feedbackPath = (messageId: number) => `/feedback/messages/${messageId}`;
export const feedbackValidationMessage = (status: FeedbackStatus, note: string) =>
  status === "needs_revision" && !note.trim() ? "请填写问题说明或补充口径" : null;

export async function saveMessageFeedback(
  messageId: number,
  payload: { status: FeedbackStatus; note?: string; final_sql?: string }
): Promise<MessageFeedback> {
  return (await client.put<MessageFeedback>(feedbackPath(messageId), payload)).data;
}

export async function deleteMessageFeedback(messageId: number): Promise<void> {
  await client.delete(feedbackPath(messageId));
}
```

Add `feedback: MessageFeedback | null` to `ChatMessage` in `types.ts`.

In `Chat.tsx`, add `feedback: null` to both locally created optimistic messages. Historical API messages already carry the persisted feedback field.

- [ ] **Step 4: Build the self-contained controls**

Create `MessageFeedbackControls.tsx` with local state initialized from `message.feedback`. Render only when `!message.generating && message.sql`.

Required behavior:

```tsx
<Button onClick={() => void saveCorrect()} type={feedback?.status === "correct" ? "primary" : "default"}>
  结果正确
</Button>
<Button onClick={openRevision} type={feedback?.status === "needs_revision" ? "primary" : "default"}>
  需要修改
</Button>
{feedback ? <Button type="text" onClick={() => void withdraw()}>撤销反馈</Button> : null}
```

`saveCorrect()` calls `saveMessageFeedback(message.id, {status: "correct"})`. The revision modal initializes note and final SQL from existing feedback or the current generated SQL, validates with `feedbackValidationMessage`, and closes only after a successful request. Failed requests show `message.error(...)` and preserve both input fields.

Do not add a global store, context provider, optimistic cache, or LLM request.

- [ ] **Step 5: Render controls in the existing message action area**

Import `MessageFeedbackControls` in `MessageTimeline.tsx` and render it inside `.assistant-actions` before copy/execute actions:

```tsx
<MessageFeedbackControls message={message} />
```

Add only the spacing and selected-state CSS needed to align the controls with existing small action buttons. Do not redesign the SQL card.

- [ ] **Step 6: Run the contract test and production build**

Run from `frontend`:

```powershell
$testOut = Join-Path ([System.IO.Path]::GetTempPath()) 'chat-feedback-test.cjs'
& '.\node_modules\.bin\esbuild.cmd' '.\tests\chat-feedback.test.ts' --bundle --platform=node --format=cjs --outfile=$testOut
node $testOut
npm.cmd run build
```

Expected: the contract script exits `0`; TypeScript and Vite production build succeed.

- [ ] **Step 7: Commit and push Task 2**

Run:

```powershell
git add -- frontend/src/features/chat/feedback.ts frontend/src/features/chat/MessageFeedbackControls.tsx frontend/src/features/chat/types.ts frontend/src/features/chat/MessageTimeline.tsx frontend/src/features/chat/chat-components.css frontend/src/pages/Chat.tsx frontend/tests/chat-feedback.test.ts
git diff --cached --check
git commit -m "feat: collect SQL answer feedback"
git push
```

Expected: generated `frontend/tsconfig.tsbuildinfo` remains unstaged.

---

### Task 3: Add maintainer review and remove the automatic-period panel

**Files:**
- Create: `frontend/src/features/ontology-package/FeedbackPanel.tsx`
- Modify: `frontend/src/features/ontology-package/api.ts`
- Modify: `frontend/src/features/ontology-package/types.ts`
- Modify: `frontend/src/features/ontology-package/OntologyWorkbench.tsx`
- Modify: `frontend/src/features/ontology-package/WorkbenchShell.tsx`
- Modify: `frontend/src/features/ontology-package/workbenchModel.ts`
- Modify: `frontend/src/features/ontology-package/DiagnosticsPanel.tsx`
- Modify: `frontend/src/features/ontology-package/diagnosticRouting.ts`
- Modify: `frontend/src/pages/Chat.tsx`
- Modify: `frontend/tests/ontology-workbench-model.test.ts`
- Delete: `frontend/src/features/ontology-package/TemporalPanel.tsx`

**Interfaces:**
- Consumes: Task 1 `GET /feedback?status=...`.
- Produces: `FeedbackRecord`, `fetchFeedbackRecords(status?)`, a `feedback` workbench stage, and `/chat?conversation=<id>` navigation.
- Preserves: all backend temporal-policy models, APIs, counts, publishing behavior, and runtime inference.

- [ ] **Step 1: Change the workbench contract test first**

Update `frontend/tests/ontology-workbench-model.test.ts` to require this order:

```typescript
const stageOrder = WORKBENCH_STAGES.map((stage) => stage.key).join(",");
if (stageOrder !== "import,objects,relations,feedback,diagnostics,versions") {
  throw new Error(`unexpected stage order: ${stageOrder}`);
}
if (workbenchStageSummary("feedback", overview, 5) !== "人工复盘 SQL 与口径") {
  throw new Error("feedback stage must describe manual review");
}
```

Import `diagnosticDestination` and assert that a temporal-policy-only diagnostic now returns `objects`, while a relation diagnostic still returns `relations`.

- [ ] **Step 2: Run the workbench test and confirm failure**

Run from `frontend`:

```powershell
$testOut = Join-Path ([System.IO.Path]::GetTempPath()) 'ontology-workbench-model-test.cjs'
& '.\node_modules\.bin\esbuild.cmd' '.\tests\ontology-workbench-model.test.ts' --bundle --platform=node --format=cjs --outfile=$testOut
node $testOut
```

Expected: fails because `feedback` is not a workbench stage and `temporal` is still present.

- [ ] **Step 3: Add aggregate feedback mapping and panel**

Add this type to `types.ts`:

```typescript
export interface FeedbackRecord {
  id: number;
  conversationId: number;
  messageId: number;
  status: "correct" | "needs_revision";
  requestText: string;
  generatedSql: string;
  note: string | null;
  finalSql: string | null;
  ontologyVersion: string | null;
  username: string;
  createdAt: string;
  updatedAt: string;
}
```

Add `fetchFeedbackRecords(status?: FeedbackRecord["status"])` to `api.ts`; call `/feedback` with an optional Axios `params.status` and map snake_case once at the boundary.

Create `FeedbackPanel.tsx` using an Ant Design `Card`, status `Select`, `Table`, and detail `Modal`. Load records on mount and whenever the status filter changes. Columns must show status, `C-{conversationId} / M-{messageId}`, abbreviated request, ontology version, username, and updated time. The detail modal shows full request, note, generated SQL, and final SQL. A “查看原会话” button calls:

```tsx
navigate(`/chat?conversation=${selected.conversationId}`)
```

No edit, delete, LLM, or apply-to-ontology action belongs in this panel.

- [ ] **Step 4: Replace the automatic-period stage with feedback**

In `workbenchModel.ts`, set:

```typescript
export type WorkbenchStage =
  | "import"
  | "objects"
  | "relations"
  | "feedback"
  | "diagnostics"
  | "versions";

export const WORKBENCH_STAGES = [
  { key: "import", number: "01", title: "导入元数据", description: "载入对象与字段定义" },
  { key: "objects", number: "02", title: "对象与字段", description: "校准业务语义说明" },
  { key: "relations", number: "03", title: "关系", description: "确认跨对象关联路径" },
  { key: "feedback", number: "04", title: "反馈记录", description: "复盘已确认 SQL 与补充口径" },
  { key: "diagnostics", number: "05", title: "诊断", description: "处理质量与一致性问题" },
  { key: "versions", number: "06", title: "发布版本", description: "固化并切换活动版本" },
] as const;
```

Return `人工复盘 SQL 与口径` from `workbenchStageSummary("feedback", ...)` and remove its `temporal` case.

In `OntologyWorkbench.tsx`, remove the `TemporalPanel` import and `temporal` panel, add `feedback: <FeedbackPanel />`, and stop passing policies to `DiagnosticsPanel`. Delete `TemporalPanel.tsx`.

In `WorkbenchShell.tsx`, remove `{ key: "temporalPolicies", label: "时间策略" }` from `assetMetrics`. Do not alter `WorkspaceOverview.temporalPolicies`, version summaries, or any backend field.

- [ ] **Step 5: Keep diagnostic navigation valid and add conversation deep links**

Reduce `DiagnosticDestination` to `"objects" | "relations"`. `diagnosticDestination(relatedIds, relationIds)` returns `relations` for a related relation and `objects` otherwise. Remove the temporal-policy argument and the `policies` prop from `DiagnosticsPanel`.

In `Chat.tsx`, import `useSearchParams`, read `conversation`, and load it once when it is a positive integer and differs from the current conversation:

```tsx
const [searchParams] = useSearchParams();
const linkedConversationId = Number(searchParams.get("conversation"));

useEffect(() => {
  if (
    Number.isInteger(linkedConversationId) &&
    linkedConversationId > 0 &&
    linkedConversationId !== activeId
  ) {
    setIsNewDraft(false);
    setActiveId(linkedConversationId);
    setSelectedEvidenceId(null);
    void loadMessages(linkedConversationId);
  }
}, [activeId, linkedConversationId, loadMessages]);
```

The existing owned conversation endpoint supplies authorization; invalid/deleted links display the existing load error and expose no data.

- [ ] **Step 6: Run focused frontend checks**

Run from `frontend`:

```powershell
$testOut = Join-Path ([System.IO.Path]::GetTempPath()) 'ontology-workbench-model-test.cjs'
& '.\node_modules\.bin\esbuild.cmd' '.\tests\ontology-workbench-model.test.ts' --bundle --platform=node --format=cjs --outfile=$testOut
node $testOut
npm.cmd run build
```

Expected: the contract script exits `0`; production build succeeds; no `TemporalPanel` import remains.

- [ ] **Step 7: Commit and push Task 3**

Run:

```powershell
git add -- frontend/src/features/ontology-package/FeedbackPanel.tsx frontend/src/features/ontology-package/api.ts frontend/src/features/ontology-package/types.ts frontend/src/features/ontology-package/OntologyWorkbench.tsx frontend/src/features/ontology-package/WorkbenchShell.tsx frontend/src/features/ontology-package/workbenchModel.ts frontend/src/features/ontology-package/DiagnosticsPanel.tsx frontend/src/features/ontology-package/diagnosticRouting.ts frontend/src/pages/Chat.tsx frontend/tests/ontology-workbench-model.test.ts
git add -u -- frontend/src/features/ontology-package/TemporalPanel.tsx
git diff --cached --check
git commit -m "feat: review SQL feedback in ontology workbench"
git push
```

Expected: the commit adds feedback review and removes only the automatic-period UI.

---

### Task 4: Migrate, verify, document, and restart shared services

**Files:**
- Modify: `docs/project-journal/2026-09.md`

**Interfaces:**
- Consumes: Tasks 1–3 and the existing local `.env`, `.venv`, Node 20 environment, backend port `8001`, and frontend port `5199`.
- Produces: upgraded local schema, fresh focused verification evidence, running services, and a project-journal record.

- [ ] **Step 1: Apply the migration and inspect the active head**

Run:

```powershell
\.venv\Scripts\python.exe -m alembic upgrade head
\.venv\Scripts\python.exe -m alembic current
```

Expected: migration reaches `b74e9f1c2a60 (head)` without altering ontology package files.

- [ ] **Step 2: Run the complete focused verification set**

Run from the repository root:

```powershell
\.venv\Scripts\python.exe -m pytest tests/test_message_feedback.py tests/test_conversation.py -q
```

Run from `frontend`:

```powershell
$chatTest = Join-Path ([System.IO.Path]::GetTempPath()) 'chat-feedback-test.cjs'
& '.\node_modules\.bin\esbuild.cmd' '.\tests\chat-feedback.test.ts' --bundle --platform=node --format=cjs --outfile=$chatTest
node $chatTest
$workbenchTest = Join-Path ([System.IO.Path]::GetTempPath()) 'ontology-workbench-model-test.cjs'
& '.\node_modules\.bin\esbuild.cmd' '.\tests\ontology-workbench-model.test.ts' --bundle --platform=node --format=cjs --outfile=$workbenchTest
node $workbenchTest
npm.cmd run build
```

Expected: focused backend tests pass, both frontend contract scripts exit `0`, and Vite build succeeds. Do not run the seven-case model evaluation.

- [ ] **Step 3: Restart exact local listeners and check readiness**

Resolve only listeners on ports `8001` and `5199`, verify their absolute process command lines belong to this project, stop those exact PIDs, then start hidden processes with logs under the already ignored `.codex-artifacts` directory:

```powershell
Start-Process -FilePath '.\.venv\Scripts\python.exe' -ArgumentList '-m','uvicorn','api.main:app','--host','127.0.0.1','--port','8001' -WorkingDirectory (Get-Location) -WindowStyle Hidden
Start-Process -FilePath 'npm.cmd' -ArgumentList 'run','dev','--','--host','127.0.0.1','--port','5199','--strictPort' -WorkingDirectory (Join-Path (Get-Location) 'frontend') -WindowStyle Hidden
Invoke-RestMethod 'http://127.0.0.1:8001/ready'
Invoke-WebRequest 'http://127.0.0.1:5199/ontology' -UseBasicParsing
```

Expected: backend readiness reports database and ontology `ok`; frontend returns HTTP `200`.

- [ ] **Step 4: Perform one local UI/API smoke path without a model call**

Use an existing completed SQL message in the browser:

1. Mark it “结果正确” and refresh the conversation; the selected status remains.
2. Change it to “需要修改”, enter a note, save, and refresh; note/status remain.
3. Open 本体工作台 → 反馈记录; the record displays and “查看原会话” opens the correct conversation.
4. Confirm no “自动账期” stage or “时间策略” metric is visible.
5. Withdraw the feedback and confirm it disappears from the aggregate list.

Expected: no DeepSeek request and no SQL execution is triggered by any step.

- [ ] **Step 5: Record the engineering outcome**

Append a dated section to `docs/project-journal/2026-09.md` covering:

- why full Reflection/high-frequency learning was deferred until enough independent accepted requirements exist;
- how one-to-one message feedback and conversation cascade deletion protect user expectations;
- how maintainer-only aggregate reads avoid exposing other users' SQL;
- why removing the non-editable automatic-period UI did not remove backend `_D/_M` inference;
- exact focused test/build/readiness results and the fact that no paid model or business SQL was used.

- [ ] **Step 6: Commit and push the journal only**

Run:

```powershell
git add -- docs/project-journal/2026-09.md
git diff --cached --check
git commit -m "docs: record SQL feedback retention"
git push
git status --short
```

Expected: the journal is pushed; only the pre-existing unrelated `frontend/tsconfig.tsbuildinfo`, `.codex-artifacts/`, and `docs/prompts/` remain outside commits.
