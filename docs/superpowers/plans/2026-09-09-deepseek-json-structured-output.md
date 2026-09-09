# DeepSeek 结构化计划 JSON 输出实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 DeepSeek 为本体程序规划和元数据候选推断稳定返回可解析 JSON，使智能取数能够继续进入确定性校验与 SQL 编译。

**Architecture:** 在 `LLMClient` 的单一 HTTP 请求边界新增内部 `json_output` 标记，并仅由结构化调用启用 DeepSeek JSON Output。字段详情工具调用在两轮都传递该标记，保留现有的工具次数上限与 reasoning context 传递；文本 SQL、自然问答和上下文压缩不受影响。

**Tech Stack:** Python 3.13、FastAPI、httpx、Pydantic、pytest、DeepSeek Chat Completions API。

## Global Constraints

- 结构化规划与元数据推断请求必须包含 `response_format={"type":"json_object"}`。
- 普通文本生成不得携带 `response_format`。
- 不持久化模型原始响应、思考文本、请求正文或凭据。
- 保留 Pydantic、候选目录、绑定和确定性 SQL 编译校验。
- 不执行生成的 SQL。
- 每项已完成的改动必须单独提交 Git；不自动推送远端。

---

### Task 1: 为结构化 LLM 请求增加 JSON 输出开关

**Files:**
- Create: `tests/test_llm_client.py`
- Modify: `tools/llm_client.py:55-260`

**Interfaces:**
- Consumes: `LLMClient._generate(system_prompt, user_query)` 的现有文本生成能力。
- Produces: `LLMClient._generate(system_prompt, user_query, *, json_output: bool = False) -> str`。
- Produces: `LLMClient._generate_program(...)` 通过 `json_output=True` 请求 `DraftSqlProgramPlan`。

- [ ] **Step 1: 写入失败测试，定义 HTTP 请求体契约**

```python
def test_structured_generation_requests_deepseek_json_output(monkeypatch):
    payloads = []
    monkeypatch.setattr("httpx.post", _capturing_post(payloads, '{"intent": {}, "steps": []}'))
    client = _configured_client()

    client._generate("return json", "request", json_output=True)

    assert payloads[0]["response_format"] == {"type": "json_object"}


def test_text_generation_does_not_force_json_output(monkeypatch):
    payloads = []
    monkeypatch.setattr("httpx.post", _capturing_post(payloads, "plain reply"))
    client = _configured_client()

    client._generate("answer naturally", "request")

    assert "response_format" not in payloads[0]
```

- [ ] **Step 2: 运行失败测试，确认接口尚不存在**

Run: `pytest -q tests/test_llm_client.py`

Expected: `FAIL`，原因是 `_generate()` 不接受 `json_output` 关键字参数。

- [ ] **Step 3: 最小化实现 JSON 请求体与安全截断处理**

```python
def _generate(self, system_prompt: str, user_query: str, *, json_output: bool = False) -> str:
    payload = {
        "model": self.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query},
        ],
        "temperature": self.temperature,
        "max_tokens": self.max_tokens,
    }
    if json_output:
        payload["response_format"] = {"type": "json_object"}
    # 保持既有 HTTP 调用；当结构化响应 finish_reason 为 length 时抛出脱敏错误。
```

在 `_generate_program()` 中调用 `_generate(..., json_output=True)`；在 `infer_metadata_program()` 的无字段检索分支中调用 `_generate(..., json_output=True)`。保留原始异常到 `StructuredPlanningError` 的脱敏转换，不把模型正文拼入异常或日志。

- [ ] **Step 4: 运行测试，确认开关只影响结构化调用**

Run: `pytest -q tests/test_llm_client.py tests/test_program_planner.py tests/test_metadata_inference_llm.py`

Expected: `PASS`。

- [ ] **Step 5: 提交任务**

```bash
git add tools/llm_client.py tests/test_llm_client.py tests/test_program_planner.py tests/test_metadata_inference_llm.py
git commit -m "fix: 强制结构化规划使用 DeepSeek JSON 输出"
```

### Task 2: 让字段详情工具轮次也保持 JSON 输出契约

**Files:**
- Modify: `tools/metadata_lookup.py:29-84`
- Modify: `tools/llm_client.py:150-157`
- Modify: `tests/test_metadata_lookup.py:11-90`

**Interfaces:**
- Consumes: `generate_with_field_lookup(client, system_prompt, user_query, lookup)`。
- Produces: `generate_with_field_lookup(client, system_prompt, user_query, lookup, *, json_output: bool = False) -> str`。
- Produces: `infer_metadata_program(..., lookup_fields=...)` 以 `json_output=True` 调用字段检索流程。

- [ ] **Step 1: 写入失败测试，覆盖直接结束和工具后结束两种路径**

```python
def test_lookup_rounds_request_json_output_and_preserve_reasoning(monkeypatch):
    payloads = []
    monkeypatch.setattr("httpx.post", _two_turn_lookup_post(payloads))

    plan = _configured_client().infer_metadata_program(
        request="查询用户编号", candidates=_candidates(), lookup_fields=lambda refs: []
    )

    assert plan.requested_field_refs == ("UserId",)
    assert payloads[0]["response_format"] == {"type": "json_object"}
    assert payloads[1]["response_format"] == {"type": "json_object"}
    assert payloads[1]["messages"][2]["reasoning_content"] == "synthetic context"
```

- [ ] **Step 2: 运行失败测试，确认字段工具请求尚未传格式约束**

Run: `pytest -q tests/test_metadata_lookup.py::test_lookup_round_preserves_provider_context_and_omits_output_cap`

Expected: `FAIL`，原因是捕获的请求体没有 `response_format`。

- [ ] **Step 3: 最小化实现轮次透传**

```python
def generate_with_field_lookup(client, system_prompt, user_query, lookup, *, json_output=False):
    # 构造既有 model/messages/tools/tool_choice 请求体。
    if json_output:
        payload["response_format"] = {"type": "json_object"}
```

在 `LLMClient.infer_metadata_program()` 调用此函数时传入 `json_output=True`。不要改变工具名称、最多两轮限制、最大四个工具调用限制或 `reasoning_content` 的原样回传。

- [ ] **Step 4: 运行字段工具与元数据推断测试**

Run: `pytest -q tests/test_metadata_lookup.py tests/test_metadata_inference.py tests/test_metadata_inference_llm.py`

Expected: `PASS`。

- [ ] **Step 5: 提交任务**

```bash
git add tools/metadata_lookup.py tools/llm_client.py tests/test_metadata_lookup.py tests/test_metadata_inference_llm.py
git commit -m "fix: 约束元数据工具轮次的 JSON 输出"
```

### Task 3: 回归验证真实服务与记录项目难点

**Files:**
- Modify: `docs/project-journal/2026-09.md`

**Interfaces:**
- Consumes: 已启动的 `http://127.0.0.1:8001` 服务、发布版本 `1.0.1` 与评测集的七条真实需求。
- Produces: 一条可复查的本地评测记录和项目日志中的问题、根因、方案、结果。

- [ ] **Step 1: 在功能分支运行完整后端回归测试**

Run: `pytest -q`

Expected: 命令退出码为 `0`，并包含本计划新增的 JSON 输出契约测试；如果出现与本次改动无关的失败，记录后停止，不把它们混入本次修复。

- [ ] **Step 2: 将已验证分支合入本地主分支后重启服务**

Run: 在 `D:\Projects\ontology-agent` 完成本地合并，不推送远端；再以根目录 `start.bat` 重启前后端，随后访问 `GET http://127.0.0.1:8001/ready`。

Expected: 返回 `{"status":"ok", ..., "ontology":"ok"}`；活动本体版本仍为 `1.0.1`。

- [ ] **Step 3: 用真实聊天接口重测第 1 条需求**

Run: 创建一个没有历史消息的新会话，发送评测集第 1 条原文，设置 `system_time="2026-08-24"`，不选择额外提示词，不执行返回 SQL。

Expected: 对话 trace 不再出现 `invalid_structured_output` 或 `invalid_inferred_plan`；结果为可验证的结构化计划、明确的本体缺失诊断，或生成的 SQL 程序。

- [ ] **Step 4: 仅在第 1 条通过结构化输出后重测第 2 至第 7 条**

Run: 对每条需求创建独立空会话，沿用 `system_time="2026-08-24"`，保存每条的本体状态、结构比较结果和失败诊断。

Expected: 结果按“生成成功、缺少表字段、缺少关联口径、规划或校验失败”分类；不执行任何 SQL。

- [ ] **Step 5: 记录项目日志并提交任务**

在 `docs/project-journal/2026-09.md` 增加一则记录：结构化提示词本身不能保证 JSON、DeepSeek JSON Output 参数缺失造成规划中断、如何通过 API 契约测试与真实会话复测避免再次发生。不得记录 API Key、完整真实需求正文、模型原始输出或思考文本。

```bash
git add docs/project-journal/2026-09.md
git commit -m "docs: 记录结构化规划 JSON 输出修复"
```
