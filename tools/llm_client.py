"""商业 LLM API 客户端（OpenAI 兼容接口）。

LLM 仅参与「生成 SQL」（接收需求 + 表结构），不接触结果数据；
SQL 执行与结果存储在本地，数据不流出。
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from config.settings import settings
from monitoring.metrics import LLM_CALL_DURATION

PLACEHOLDER_KEY = "your-api-key-here"


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
