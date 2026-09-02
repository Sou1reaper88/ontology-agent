"""商业 LLM API 客户端（OpenAI 兼容接口）。

LLM 仅参与「生成 SQL」（接收需求 + 表结构），不接触结果数据；
SQL 执行与结果存储在本地，数据不流出。
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import ValidationError

from agent.context_engineering import ContextMessage
from config.settings import settings
from monitoring.metrics import LLM_CALL_DURATION
from ontology_core.program_models import (
    DraftSqlProgramPlan,
    ProgramDiagnostic,
)

PLACEHOLDER_KEY = "your-api-key-here"


class StructuredPlanningError(RuntimeError):
    """Safe error raised when the provider does not return the required contract."""


class LLMClient:
    """调用商业 LLM 生成 SQL（支持通义/智谱/DeepSeek 等 OpenAI 兼容服务）。"""

    def __init__(self) -> None:
        self.base_url = settings.llm.base_url
        self.api_key = settings.llm.api_key
        self.model = settings.llm.model
        self.temperature = settings.llm.temperature
        self.max_tokens = settings.llm.max_tokens
        self.timeout = settings.llm.timeout_seconds

    def generate_sql(self, system_prompt: str, user_query: str) -> str:
        """调用 /v1/chat/completions 生成 SQL，返回文本内容。"""
        start = time.time()
        try:
            return self._generate(system_prompt, user_query)
        finally:
            LLM_CALL_DURATION.observe(time.time() - start)

    def plan_sql_program(
        self,
        *,
        system_prompt: str,
        user_query: str,
    ) -> DraftSqlProgramPlan:
        """Request and validate one SQL-free semantic program draft."""
        return self._generate_program(system_prompt, user_query)

    def repair_sql_program(
        self,
        *,
        original_query: str,
        draft: DraftSqlProgramPlan,
        diagnostics: Sequence[ProgramDiagnostic],
        conversation_context: str | None = None,
    ) -> DraftSqlProgramPlan:
        """Repair one draft using only stable diagnostics and no generated SQL."""
        system_prompt = (
            "你只能修复结构化取数程序草案。"
            "仅输出一个符合 JSON Schema 的 JSON 对象；"
            "禁止输出 SQL，禁止输出目标表名或任意物理标识符；"
            "不得改变无关的业务意图。"
        )
        repair_request = json.dumps(
            {
                "original_request": original_query,
                "draft": draft.model_dump(mode="json"),
                "diagnostics": [item.model_dump(mode="json") for item in diagnostics],
                "conversation_context": conversation_context,
                "schema": DraftSqlProgramPlan.model_json_schema(),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return self._generate_program(system_prompt, repair_request)

    def summarize_conversation(
        self,
        *,
        existing_summary: str | None,
        messages: tuple[ContextMessage, ...],
        target_tokens: int,
    ) -> str:
        """Compress old turns into business-state memory without changing raw storage."""

        system_prompt = (
            "你是取数智能体的上下文压缩器。只总结已经发生的对话，不推测新口径。"
            "优先保留当前目标、用户确认的业务口径、对象与字段、表关系与关联键、"
            "账期和分区规则、用户纠正、最新有效 SQL、未决问题。旧 SQL 只保留关键差异。"
            f"摘要尽量控制在 {target_tokens} tokens 内，直接输出摘要正文。"
        )
        request = json.dumps(
            {
                "existing_summary": existing_summary,
                "messages": [
                    {
                        "id": item.message_id,
                        "role": item.role,
                        "content": item.content,
                        "sql": item.sql,
                    }
                    for item in messages
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        start = time.time()
        try:
            return self._generate(system_prompt, request)
        finally:
            LLM_CALL_DURATION.observe(time.time() - start)

    def _generate_program(
        self,
        system_prompt: str,
        user_query: str,
    ) -> DraftSqlProgramPlan:
        start = time.time()
        try:
            try:
                raw = self._generate(system_prompt, user_query)
            except Exception as error:
                raise StructuredPlanningError("结构化规划服务不可用") from error
        finally:
            LLM_CALL_DURATION.observe(time.time() - start)
        text = self._unwrap_json_fence(raw)
        try:
            return DraftSqlProgramPlan.model_validate_json(text)
        except (ValidationError, ValueError, TypeError) as error:
            raise StructuredPlanningError("结构化计划格式无效") from error

    @staticmethod
    def _unwrap_json_fence(raw: str) -> str:
        text = raw.strip()
        if not text.startswith("```"):
            return text
        lines = text.splitlines()
        if len(lines) < 3 or lines[-1].strip() != "```":
            raise StructuredPlanningError("结构化计划格式无效")
        return "\n".join(lines[1:-1]).strip()

    def _generate(self, system_prompt: str, user_query: str) -> str:
        if not self.api_key or self.api_key == PLACEHOLDER_KEY:
            raise RuntimeError(
                "LLM API Key 未配置，请在 .env 设置 LLM__API_KEY"
            )
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        resp = httpx.post(
            url, json=payload, headers=headers, timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """返回 LLM 客户端单例。"""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
