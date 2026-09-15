# DeepSeek Flash Token Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让官方模型名 `deepseek-flash` 在未显式配置 Token 上限时使用 1M 上下文和 384K 最大输出。

**Architecture:** 直接替换现有静态模型能力档案键，并同步部署配置和测试。保留未知模型的安全回退与显式配置优先级，不增加别名层。

**Tech Stack:** Python 3.13、Pydantic、pytest、Kubernetes YAML

## Global Constraints

- 只支持官方当前名称 `deepseek-flash`，不保留 `deepseek-v4-flash` 兼容项。
- 上下文长度为 1,000,000 Token，最大输出为 393,216 Token。
- 不修改上下文压缩算法、评测中心或本地 `.env`。

---

### Task 1: 更新 DeepSeek Flash 能力档案

**Files:**
- Modify: `tests/test_model_capabilities.py`
- Modify: `agent/model_capabilities.py`
- Modify: `deploy/k8s/configmap.yaml`
- Modify: `tests/test_metadata_lookup.py`
- Modify: `tests/test_metadata_inference_llm.py`
- Modify: `tests/test_llm_client.py`

**Interfaces:**
- Consumes: `resolve_model_token_limits(llm: LLMSettings) -> ModelTokenLimits`
- Produces: `deepseek-flash` 的官方默认 Token 能力档案

- [ ] **Step 1: 写入失败测试**

将模型默认值测试输入从 `deepseek-v4-flash` 改为 `deepseek-flash`，并增加旧名称回退断言：

```python
def test_deepseek_flash_uses_documented_defaults():
    limits = resolve_model_token_limits(LLMSettings(model="deepseek-flash"))
    assert limits.context_window_tokens == 1_000_000
    assert limits.max_input_tokens == 1_000_000
    assert limits.max_output_tokens == 393_216


def test_retired_deepseek_name_uses_safe_defaults():
    limits = resolve_model_token_limits(LLMSettings(model="deepseek-v4-flash"))
    assert limits.context_window_tokens == 32_768
    assert limits.max_input_tokens == 32_768
    assert limits.max_output_tokens == 4_096
```

- [ ] **Step 2: 验证测试因缺少新档案而失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_model_capabilities.py -q`

Expected: `deepseek-flash` 实际得到 32,768 / 4,096，测试失败。

- [ ] **Step 3: 完成最小实现**

将 `agent/model_capabilities.py` 的专用档案键改为 `deepseek-flash`，并将部署配置及其他测试夹具中的模型名同步替换为 `deepseek-flash`。

- [ ] **Step 4: 验证相关测试**

Run: `.venv/Scripts/python.exe -m pytest tests/test_model_capabilities.py tests/test_context_engineering.py tests/test_llm_client.py tests/test_metadata_lookup.py tests/test_metadata_inference_llm.py -q`

Expected: 全部通过。

- [ ] **Step 5: 验证运行配置解析结果**

Run: `.venv/Scripts/python.exe -c "from config.settings import settings; from agent.model_capabilities import resolve_model_token_limits; print(settings.llm.model, resolve_model_token_limits(settings.llm))"`

Expected: 模型为 `deepseek-flash`，三个能力值依次为 1,000,000、1,000,000、393,216。

- [ ] **Step 6: 提交并推送**

只暂存本任务涉及的文件，提交信息为 `fix: update DeepSeek Flash token profile`，随后推送当前分支。
