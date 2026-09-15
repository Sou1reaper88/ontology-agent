# Semantic Requirement Priority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the conversational SQL agent interpret changing natural-language requirement formats by semantic role and stop background text from expanding or unnecessarily blocking the requested output.

**Architecture:** Keep the existing single DeepSeek conversation loop and five read-only tools. Add only a system-prompt contract; do not add a Python parser, new model call, dependency, database change, or automatic SQL rewrite.

**Tech Stack:** Python 3.13, Pydantic, pytest, existing OpenAI-compatible DeepSeek chat-completions API.

## Global Constraints

- Requirement headings and templates are optional; interpretation is semantic.
- Explicit current task, requested output, business constraints, and time/region limits outrank background.
- Reasonable inference is recorded in `assumptions`; only result-changing contradictions or missing core facts enter `unresolved_items`.
- Existing SQL safety and structural validation remains unchanged.
- Do not stage `frontend/tsconfig.tsbuildinfo`, `.codex-artifacts/`, or `docs/prompts/`.

---

### Task 1: Add the semantic-priority prompt contract

**Files:**
- Modify: `tests/test_conversation_agent.py`
- Modify: `agent/conversation_agent.py`
- Modify: `docs/project-journal/2026-09.md`

**Interfaces:**
- Consumes: `run_conversation_agent(user_query, ...)` and its first OpenAI-compatible system message.
- Produces: the same public function and response schema, with stronger model instructions only.

- [x] **Step 1: Write the failing contract test**

```python
def test_system_prompt_prioritizes_semantics_without_fixed_template(monkeypatch):
    requests = provider(monkeypatch, [final()])
    agent.run_conversation_agent('自然语言取数需求')
    prompt = requests[0]['messages'][0]['content']
    assert '不依赖固定栏目名称或需求模板' in prompt
    assert '背景只用于理解目的，不得扩展查询周期、输出表或指标' in prompt
    assert '不影响核心输出的信息不得放入unresolved_items' in prompt
```

- [x] **Step 2: Run the test and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_conversation_agent.py::test_system_prompt_prioritizes_semantics_without_fixed_template -q`

Expected: one assertion failure because the semantic-priority contract is absent from `SYSTEM`.

- [x] **Step 3: Add the minimum system-prompt instructions**

Insert into `SYSTEM` immediately after the current-turn/history rules:

```python
"不依赖固定栏目名称或需求模板，按语义识别当前任务、请求输出、业务定义与筛选范围、时间地区限制和背景。"
"当前明确任务、请求输出和用户最新纠正优先；背景只用于理解目的，不得扩展查询周期、输出表或指标。"
"未指定输出字段时可选择完成任务所需的最小字段集并写入assumptions；能由元数据和上下文合理推断的口径也写入assumptions并继续生成。"
"未登记关系、用户明确给出的外部表字段、可选分析缺口或不影响核心输出的信息不得放入unresolved_items。"
"只有会实质改变结果的直接冲突，或缺少导致请求输出无法计算的核心事实，才写入unresolved_items并阻止正式交付。"
```

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/test_conversation_agent.py tests/test_conversation_capabilities.py -q`

Expected: all selected tests pass.

- [x] **Step 5: Record the generalized engineering lesson**

Append to `docs/project-journal/2026-09.md` that static SQL success did not prove requirement-scope correctness, and that the fix preserved model flexibility by defining semantic priority rather than parsing fixed headings. Do not include business table names, SQL, or sensitive requirement text.

- [x] **Step 6: Verify, commit, and push**

Run: `.venv\Scripts\python.exe -m pytest tests/test_conversation_agent.py tests/test_conversation_capabilities.py -q`

Expected: zero failures.

Then stage only the three task files, commit with `fix: prioritize explicit requirement semantics`, and push `main`.

## Execution finding

The first live verification exposed a separate loop-budget defect: when the eighth model call returned a successful `validate_sql` tool call, no call remained for the final JSON response. The implementation therefore preserves the 16-tool cap and adds one ninth, final-only model call with `tool_choice="none"`. A regression test covers eight tool rounds followed by a final response.
