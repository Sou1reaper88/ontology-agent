# Default Materialized SQL Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make formal data requests default to a paired `DROP TABLE IF EXISTS` / `CREATE TABLE AS SELECT` result program while preserving explicit query-only requests.

**Architecture:** The conversation model declares `delivery_mode` as `table` or `query`; the existing Python delivery boundary verifies that declaration against the already parsed `CompiledProgram`. No keyword parser, SQL rewrite, additional model call, frontend change, or database migration is introduced.

**Tech Stack:** Python 3.13, Pydantic, sqlglot-backed existing authored SQL validator, pytest.

## Global Constraints

- `delivery_mode` defaults to `table` when omitted.
- `query` is allowed only when the model understands an explicit user request for query-only output.
- Every table step remains a `DROP TABLE IF EXISTS` / `CREATE TABLE AS SELECT` pair in the current `temp_oa_<program_id>_` namespace.
- The final target must be `temp_oa_<program_id>_result_table`.
- Preserve authored SQL exactly; never execute or rewrite it and never add trailing cleanup.
- Do not stage `frontend/tsconfig.tsbuildinfo`, `.codex-artifacts/`, or `docs/prompts/`.

---

### Task 1: Enforce model-declared delivery mode

**Files:**
- Modify: `tests/test_conversation_capabilities.py`
- Modify: `agent/conversation_agent.py`
- Modify: `docs/project-journal/2026-09.md`

**Interfaces:**
- Consumes: `Answer`, `ConversationTools.validate()`, and returned `CompiledProgram | None`.
- Produces: `Answer.delivery_mode: Literal["table", "query"]` with default `"table"`; unchanged public `run_conversation_agent()` result schema.

- [ ] **Step 1: Write failing delivery-contract tests**

Add tests proving:

```python
def test_default_delivery_rejects_a_bare_query(monkeypatch):
    provider(monkeypatch, [final("SELECT ID FROM dm.TEST_M WHERE P_MON='202607'")])
    output = agent.run_conversation_agent('正式取数', request_id='synthetic')
    assert not output['success']
    assert output['generation_mode'] == 'authored_draft'
    assert '默认需要物化结果表' in output['errors'][0]


def test_explicit_query_delivery_accepts_a_bare_query(monkeypatch):
    provider(monkeypatch, [final(
        "SELECT ID FROM dm.TEST_M WHERE P_MON='202607'",
        delivery_mode='query',
    )])
    output = agent.run_conversation_agent('仅查询预览', request_id='synthetic')
    assert output['success']
    assert output['generation_mode'] == 'authored_query'


def test_table_delivery_requires_the_result_table(monkeypatch):
    sql = script("SELECT ID FROM dm.TEST_M WHERE P_MON='202607'", target=f'temp_oa_{PID}_work')
    provider(monkeypatch, [final(sql, delivery_mode='table')])
    output = agent.run_conversation_agent('正式取数', request_id='synthetic')
    assert not output['success']
    assert 'result_table' in output['errors'][0]


def test_query_delivery_rejects_a_materialized_program(monkeypatch):
    provider(monkeypatch, [final(
        script("SELECT ID FROM dm.TEST_M WHERE P_MON='202607'"),
        delivery_mode='query',
    )])
    output = agent.run_conversation_agent('仅查询预览', request_id='synthetic')
    assert not output['success']
    assert '仅查询' in output['errors'][0]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_conversation_capabilities.py -q`

Expected: new tests fail because `Answer` does not accept `delivery_mode` and bare queries remain valid by default.

- [ ] **Step 3: Implement the minimum contract**

In `agent/conversation_agent.py`:

```python
from typing import Literal

class Answer(BaseModel):
    ...
    delivery_mode: Literal['table', 'query'] = 'table'
```

Update `SYSTEM` so formal data requests use `table` by default and `query` only for explicit query-only requests. After existing SQL validation:

```python
program = artifact['program']
if answer.delivery_mode == 'table':
    if program is None:
        raise ValueError('正式取数默认需要物化结果表，请使用DROP TABLE IF EXISTS / CREATE TABLE AS SELECT')
    expected = f'temp_oa_{capabilities.program_id}_result_table'
    if program.result_table.casefold() != expected.casefold():
        raise ValueError(f'最后一个物化目标必须是{expected}')
elif program is not None:
    raise ValueError('用户要求仅查询时不得生成建表程序')
```

The existing parser already rejects unpaired DDL, unsafe targets, trailing cleanup, and source-table overwrite.

- [ ] **Step 4: Update existing synthetic responses intentionally**

Set `delivery_mode='query'` only in existing tests whose purpose is to verify an allowed read-only query. Leave omitted mode in the new default-materialization test so the default itself remains covered.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/test_conversation_agent.py tests/test_conversation_capabilities.py tests/test_conversation.py -q`

Expected: zero failures.

- [ ] **Step 6: Record the engineering decision**

Append a generalized entry to `docs/project-journal/2026-09.md`: prompt-only delivery preferences are not guarantees, so the model declares intent while Python checks shape; no business SQL or sensitive metadata is recorded.

- [ ] **Step 7: Restart and perform one authorized live verification**

Restart only the backend on port 8001. Re-run one previously accepted formal request through `/conversations`, then verify the returned SQL contains a paired result-table `DROP/CREATE`, has no trailing cleanup, and was not executed.

- [ ] **Step 8: Verify, commit, and push**

Run the focused tests again, run `git diff --check`, confirm `/ready` reports database and ontology `ok`, stage only the four task files, commit with `fix: default formal requests to result tables`, and push `main`.
