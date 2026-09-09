# 元数据优先生成链路 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让导入型本体优先通过候选元数据推断生成 SQL，避免每次先调用全量语义计划器，并提升结构化 JSON 返回的兼容性。

**Architecture:** `ProgramGenerationService` 先尝试检索后的元数据候选推断，成功即返回安全编译后的程序；候选失败才调用语义计划器，且不重复候选调用。`LLMClient` 仅规范模型回复的 JSON 外壳，随后仍用现有 Pydantic 契约严格校验。

**Tech Stack:** Python 3.13、FastAPI、Pydantic、pytest、DeepSeek OpenAI-compatible API。

## Global Constraints

- SQL 只生成和展示，绝不自动执行。
- 不保存或展示模型原文、业务数据、凭据或内部推理。
- 结构化对象必须通过既有 Pydantic Schema，不接受 SQL、物理标识符或额外字段。
- 每项改动完成后创建本地 Git 提交，不推送远程。

---

### Task 1: 严格 JSON 外壳归一化与工具参数一致性

**Files:**

- Modify: `tools/llm_client.py`
- Modify: `tools/metadata_lookup.py`
- Modify: `tests/test_program_planner.py`
- Modify: `tests/test_metadata_lookup.py`

**Interfaces:** `LLMClient._normalize_json_object(raw: str) -> str` 返回一个顶层 JSON 对象或抛出 `StructuredPlanningError(category="invalid_json")`。工具调用的两轮 payload 均包含 `temperature`、`max_tokens`。

- [ ] **Step 1: 写失败测试**

```python
def test_llm_client_accepts_json_object_after_json_label() -> None:
    class _RawClient(LLMClient):
        def __init__(self) -> None: pass
        def _generate(self, *args, **kwargs) -> str:
            return 'JSON:\n{"intent": {"task_type": "data_extraction"}}'
    with pytest.raises(StructuredPlanningError) as caught:
        _RawClient().plan_sql_program(system_prompt="plan", user_query="request")
    assert caught.value.category == "schema_validation"
```

- [ ] **Step 2: 验证失败**

Run: `.venv\\Scripts\\python.exe -m pytest -q tests/test_program_planner.py::test_llm_client_accepts_json_object_after_json_label`

Expected: FAIL，现有代码会标记为 `invalid_json`。

- [ ] **Step 3: 实现最小归一化和参数补齐**

在 `_generate_program`、`infer_metadata_program` 的 Pydantic 校验前调用 `_normalize_json_object`；它从首个 `{` 使用 `json.JSONDecoder().raw_decode` 读取顶层 dict 并重新序列化。解析失败或顶层非对象时抛出 `invalid_json`。`metadata_lookup` payload 添加 `temperature=client.temperature`、`max_tokens=client.max_tokens`。

- [ ] **Step 4: 验证和提交**

Run: `.venv\\Scripts\\python.exe -m pytest -q tests/test_program_planner.py tests/test_metadata_lookup.py tests/test_metadata_inference_llm.py`

Expected: PASS。

Commit: `git add tools/llm_client.py tools/metadata_lookup.py tests/test_program_planner.py tests/test_metadata_lookup.py && git commit -m "fix: 规范候选推断 JSON 输出"`

### Task 2: 元数据候选推断优先且不重复调用

**Files:**

- Modify: `agent/program_generation.py`
- Modify: `tests/test_program_generation.py`

**Interfaces:** `generate(...)` 在候选成功时返回 `INFERRED_PROGRAM`；候选失败时仅调用一次语义计划器，最终失败不再调用 `_infer`。

- [ ] **Step 1: 写失败测试**

```python
def test_metadata_success_skips_semantic_planner() -> None:
    planner = _Planner(AssertionError("semantic planner must not run"))
    inference = _Inference(_inferred_success())
    result = _service(planner=planner, inference=inference).generate(
        "查询用户", request_id="request-1", system_time=_SYSTEM_TIME
    )
    assert result.mode is ProgramGenerationMode.INFERRED_PROGRAM
    assert inference.calls == 1
```

```python
def test_metadata_failure_falls_back_once_without_second_inference() -> None:
    planner = _Planner(_ready_outcome())
    inference = _Inference(_inferred_failure())
    result = _service(planner=planner, inference=inference).generate(
        "查询用户", request_id="request-1", system_time=_SYSTEM_TIME
    )
    assert result.sql is not None
    assert inference.calls == 1
    assert planner.calls == 1
```

- [ ] **Step 2: 验证失败**

Run: `.venv\\Scripts\\python.exe -m pytest -q tests/test_program_generation.py -k "metadata_success_skips_semantic_planner or metadata_failure_falls_back_once_without_second_inference"`

Expected: FAIL，当前实现先调用语义计划器，且失败路径会再次候选推断。

- [ ] **Step 3: 调整路由**

先执行 `metadata_result = self._infer(..., origin_diagnostics=(), failure_mode=ProgramGenerationMode.UNSUPPORTED)`。若其包含 SQL 则直接返回；否则最多调用一次 `self._planner.plan(...)`。语义计划失败时将 `metadata_result.diagnostics` 与 `outcome.diagnostics` 合并后直接 `_fallback`，禁止第二次 `_infer`。保留本体不可用、会话上下文和 `allow_legacy_compatibility` 行为。

- [ ] **Step 4: 验证和提交**

Run: `.venv\\Scripts\\python.exe -m pytest -q tests/test_program_generation.py tests/test_metadata_inference.py tests/test_program_planner.py`

Expected: PASS。

Commit: `git add agent/program_generation.py tests/test_program_generation.py && git commit -m "feat: 候选元数据推断优先生成"`

### Task 3: 完整验证、真实复测与项目记录

**Files:**

- Modify: `docs/project-journal/2026-09.md`

- [ ] **Step 1: 运行完整测试**

Run: `.venv\\Scripts\\python.exe -m pytest -q`

Expected: 所有测试通过；`.pytest_cache` 权限警告单独记录为环境限制。

- [ ] **Step 2: 重启后端并检查 `/ready`**

Expected: `database` 与 `ontology` 都为 `ok`。

- [ ] **Step 3: 仅用第 1 条真实需求调用对话生成接口**

Expected: 生成 SQL 或稳定诊断；绝不调用 SQL 执行接口。

- [ ] **Step 4: 记录并提交**

在 `docs/project-journal/2026-09.md` 记录“全量语义目录在大字段量本体中慢且不稳定；候选元数据优先、旧规划回退、严格 JSON Schema 校验；测试数量和真实会话状态”，不记录需求原文、模型原文或 SQL。

Commit: `git add docs/project-journal/2026-09.md && git commit -m "docs: 记录元数据优先生成实践"`
