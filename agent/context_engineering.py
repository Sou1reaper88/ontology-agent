"""Token-budgeted conversation context assembly with low-frequency compaction."""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContextMessage:
    """One immutable raw conversation message used for prompt assembly."""

    message_id: int
    role: str
    content: str
    sql: str | None = None


class ContextSummarizer(Protocol):
    def summarize_conversation(
        self,
        *,
        existing_summary: str | None,
        messages: tuple[ContextMessage, ...],
        target_tokens: int,
    ) -> str: ...


def estimate_tokens(text: str) -> int:
    """Estimate tokens without coupling the provider-neutral client to one tokenizer.

    CJK characters are conservatively counted one-for-one. ASCII text is estimated
    at four characters per token, which is suitable for prompts and SQL budgeting.
    """

    if not text:
        return 0
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return non_ascii_chars + math.ceil(ascii_chars / 4)


@dataclass(frozen=True)
class AssembledContext:
    persistent_prompt: str | None
    summary: str | None
    messages: tuple[ContextMessage, ...]
    compacted_through_message_id: int | None
    estimated_tokens: int
    trigger_tokens: int
    target_tokens: int
    compressed: bool
    compression_method: Literal["none", "model", "fallback"]

    def render(self) -> str:
        """Render one stable context block shared by every model call in a turn."""

        parts: list[str] = []
        if self.persistent_prompt:
            parts.append(f"本轮会话提示词：\n{self.persistent_prompt.strip()}")
        if self.summary:
            parts.append(f"较早对话摘要：\n{self.summary.strip()}")
        if self.messages:
            lines = ["未压缩的历史对话："]
            for item in self.messages:
                role = "用户" if item.role == "user" else "助手"
                lines.append(f"{role}：{item.content}")
                if item.sql:
                    lines.append(f"助手已生成 SQL：{item.sql}")
            parts.append("\n".join(lines))
        return "\n\n".join(parts)


class ContextAssembler:
    """Assemble raw history until its effective token budget is nearly full."""

    def __init__(
        self,
        *,
        context_window_tokens: int,
        max_output_tokens: int,
        static_prompt_reserve_tokens: int,
        trigger_ratio: float,
        target_ratio: float,
        keep_recent_turns: int,
        summarizer: ContextSummarizer | None,
    ) -> None:
        history_budget = (
            context_window_tokens - max_output_tokens - static_prompt_reserve_tokens
        )
        if history_budget <= 0:
            raise ValueError("上下文窗口必须大于输出与静态提示预留之和")
        if not 0 < target_ratio < trigger_ratio < 1:
            raise ValueError("上下文压缩比例必须满足 0 < target < trigger < 1")
        if keep_recent_turns < 1:
            raise ValueError("至少保留一轮原始对话")
        self._history_budget = history_budget
        self._trigger_tokens = max(1, int(history_budget * trigger_ratio))
        self._target_tokens = max(1, int(history_budget * target_ratio))
        self._keep_recent_messages = keep_recent_turns * 2
        self._summarizer = summarizer

    def assemble(
        self,
        messages: Sequence[ContextMessage],
        *,
        persistent_prompt: str | None = None,
        previous_summary: str | None = None,
        previous_summary_through_message_id: int | None = None,
    ) -> AssembledContext:
        active = tuple(
            item
            for item in messages
            if previous_summary_through_message_id is None
            or item.message_id > previous_summary_through_message_id
        )
        current = self._result(
            persistent_prompt=persistent_prompt,
            summary=previous_summary,
            messages=active,
            boundary=previous_summary_through_message_id,
            compressed=False,
            method="none",
        )
        if current.estimated_tokens < self._trigger_tokens:
            return current

        split_at = max(0, len(active) - self._keep_recent_messages)
        prefix = active[:split_at]
        recent = active[split_at:]
        if not prefix:
            return current

        available_summary_tokens = max(
            32,
            self._target_tokens
            - estimate_tokens(
                self._render_parts(
                    persistent_prompt=persistent_prompt,
                    summary=None,
                    messages=recent,
                )
            )
            - estimate_tokens("\n\n较早对话摘要：\n"),
        )
        method: Literal["model", "fallback"] = "model"
        try:
            if self._summarizer is None:
                raise RuntimeError("summarizer unavailable")
            summary = self._summarizer.summarize_conversation(
                existing_summary=previous_summary,
                messages=prefix,
                target_tokens=available_summary_tokens,
            ).strip()
            if not summary:
                raise ValueError("empty summary")
        except Exception:
            logger.warning("上下文模型压缩失败，使用确定性提取回退", exc_info=True)
            method = "fallback"
            summary = self._fallback_summary(previous_summary, prefix)

        summary = self._truncate_to_tokens(summary, available_summary_tokens)
        return self._result(
            persistent_prompt=persistent_prompt,
            summary=summary,
            messages=recent,
            boundary=prefix[-1].message_id,
            compressed=True,
            method=method,
        )

    def _result(
        self,
        *,
        persistent_prompt: str | None,
        summary: str | None,
        messages: tuple[ContextMessage, ...],
        boundary: int | None,
        compressed: bool,
        method: Literal["none", "model", "fallback"],
    ) -> AssembledContext:
        rendered = self._render_parts(
            persistent_prompt=persistent_prompt,
            summary=summary,
            messages=messages,
        )
        return AssembledContext(
            persistent_prompt=persistent_prompt,
            summary=summary,
            messages=messages,
            compacted_through_message_id=boundary,
            estimated_tokens=estimate_tokens(rendered),
            trigger_tokens=self._trigger_tokens,
            target_tokens=self._target_tokens,
            compressed=compressed,
            compression_method=method,
        )

    @staticmethod
    def _render_parts(
        *,
        persistent_prompt: str | None,
        summary: str | None,
        messages: tuple[ContextMessage, ...],
    ) -> str:
        return AssembledContext(
            persistent_prompt=persistent_prompt,
            summary=summary,
            messages=messages,
            compacted_through_message_id=None,
            estimated_tokens=0,
            trigger_tokens=0,
            target_tokens=0,
            compressed=False,
            compression_method="none",
        ).render()

    @classmethod
    def _fallback_summary(
        cls,
        previous_summary: str | None,
        messages: tuple[ContextMessage, ...],
    ) -> str:
        lines = ["历史上下文提取（模型摘要不可用）："]
        if previous_summary:
            lines.append(f"已有摘要：{previous_summary}")
        for item in messages:
            role = "用户" if item.role == "user" else "助手"
            content = item.content.strip().replace("\n", " ")
            lines.append(f"{role}#{item.message_id}：{content[:240]}")
            if item.sql:
                lines.append(f"SQL#{item.message_id}：{item.sql.strip()[:400]}")
        return "\n".join(lines)

    @staticmethod
    def _truncate_to_tokens(text: str, limit: int) -> str:
        if estimate_tokens(text) <= limit:
            return text
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if estimate_tokens(text[:mid]) <= limit:
                low = mid
            else:
                high = mid - 1
        return text[:low].rstrip()
