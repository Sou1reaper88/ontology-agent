from __future__ import annotations

from agent.context_engineering import AssembledContext, ContextAssembler, ContextMessage


class _Summarizer:
    def __init__(self, result: str = "已确认口径：仅保留正常在网用户") -> None:
        self.result = result
        self.calls: list[tuple[str | None, tuple[int, ...], int]] = []

    def summarize_conversation(
        self,
        *,
        existing_summary: str | None,
        messages: tuple[ContextMessage, ...],
        target_tokens: int,
    ) -> str:
        self.calls.append(
            (existing_summary, tuple(item.message_id for item in messages), target_tokens)
        )
        return self.result


class _FailingSummarizer(_Summarizer):
    def summarize_conversation(self, **kwargs) -> str:
        super().summarize_conversation(**kwargs)
        raise RuntimeError("provider unavailable")


def _message(message_id: int, role: str, text: str) -> ContextMessage:
    return ContextMessage(
        message_id=message_id,
        role=role,
        content=text,
        sql=("SELECT customer_id FROM customer;" if role == "assistant" else None),
    )


def _assembler(summarizer, *, keep_recent_turns: int = 2) -> ContextAssembler:
    return ContextAssembler(
        context_window_tokens=1_000,
        max_input_tokens=1_000,
        max_output_tokens=100,
        static_prompt_reserve_tokens=100,
        trigger_ratio=0.8,
        target_ratio=0.6,
        keep_recent_turns=keep_recent_turns,
        summarizer=summarizer,
    )


def test_short_history_remains_verbatim_without_summarizer_call() -> None:
    summarizer = _Summarizer()
    messages = (
        _message(1, "user", "查询客户号码"),
        _message(2, "assistant", "已生成查询"),
    )

    result = _assembler(summarizer).assemble(
        messages,
        persistent_prompt="只使用已发布本体",
    )

    assert result.compressed is False
    assert result.compression_method == "none"
    assert result.messages == messages
    assert result.summary is None
    assert summarizer.calls == []
    assert "查询客户号码" in result.render()


def test_explicit_input_limit_caps_the_history_budget() -> None:
    assembler = ContextAssembler(
        context_window_tokens=1_000,
        max_input_tokens=500,
        max_output_tokens=100,
        static_prompt_reserve_tokens=100,
        trigger_ratio=0.8,
        target_ratio=0.6,
        keep_recent_turns=2,
        summarizer=None,
    )

    result = assembler.assemble(())

    assert result.trigger_tokens == 320
    assert result.target_tokens == 240


def test_long_history_compacts_only_prefix_and_keeps_recent_turns_verbatim() -> None:
    summarizer = _Summarizer()
    messages = tuple(
        _message(index, "user" if index % 2 else "assistant", "业务口径" * 20)
        for index in range(1, 11)
    )

    result = _assembler(summarizer).assemble(messages)

    assert result.compressed is True
    assert result.compression_method == "model"
    assert tuple(item.message_id for item in result.messages) == (7, 8, 9, 10)
    assert result.compacted_through_message_id == 6
    assert summarizer.calls[0][1] == (1, 2, 3, 4, 5, 6)
    assert result.summary == "已确认口径：仅保留正常在网用户"


def test_existing_summary_boundary_is_not_summarized_twice() -> None:
    summarizer = _Summarizer("合并后的摘要")
    messages = tuple(
        _message(index, "user" if index % 2 else "assistant", "新增业务约束" * 20)
        for index in range(1, 13)
    )

    result = _assembler(summarizer).assemble(
        messages,
        previous_summary="此前摘要",
        previous_summary_through_message_id=4,
    )

    assert summarizer.calls[0][0] == "此前摘要"
    assert summarizer.calls[0][1] == (5, 6, 7, 8)
    assert tuple(item.message_id for item in result.messages) == (9, 10, 11, 12)
    assert result.compacted_through_message_id == 8


def test_current_request_is_counted_before_deciding_to_compact_old_history() -> None:
    summarizer = _Summarizer()
    messages = tuple(
        _message(index, "user" if index % 2 else "assistant", "历史口径" * 8)
        for index in range(1, 9)
    )

    result = _assembler(summarizer, keep_recent_turns=1).assemble(
        messages,
        current_input="本轮新增的复杂取数要求" * 30,
    )

    assert result.compressed is True
    assert summarizer.calls[0][1] == (1, 2, 3, 4, 5, 6)


def test_summarizer_failure_uses_bounded_deterministic_fallback() -> None:
    summarizer = _FailingSummarizer()
    messages = tuple(
        _message(index, "user" if index % 2 else "assistant", "不可丢失的业务定义" * 8)
        for index in range(1, 11)
    )

    result = _assembler(summarizer).assemble(messages)

    assert result.compressed is True
    assert result.compression_method == "fallback"
    assert result.compacted_through_message_id == 6
    assert tuple(item.message_id for item in result.messages) == (7, 8, 9, 10)
    assert "历史上下文提取" in (result.summary or "")
    assert result.estimated_tokens <= result.target_tokens


def test_conversation_helper_persists_only_new_summary_state(monkeypatch) -> None:
    from types import SimpleNamespace

    import api.routes.conversation as route

    captured = {}
    assembled = AssembledContext(
        persistent_prompt="口径约束",
        summary="压缩后的摘要",
        messages=(_message(9, "user", "最近需求"),),
        compacted_through_message_id=8,
        estimated_tokens=120,
        trigger_tokens=640,
        target_tokens=480,
        compressed=True,
        compression_method="model",
    )

    class _Assembler:
        def assemble(self, messages, **kwargs):
            captured["ids"] = tuple(item.message_id for item in messages)
            captured.update(kwargs)
            return assembled

    monkeypatch.setattr(route, "get_context_assembler", lambda: _Assembler())
    conversation = SimpleNamespace(
        context="口径约束",
        context_summary="旧摘要",
        context_summary_through_message_id=4,
    )
    history = [
        SimpleNamespace(id=5, role="user", content="历史需求", sql=None),
        SimpleNamespace(id=6, role="assistant", content="历史回答", sql="SELECT 1;"),
    ]

    result = route._prepare_conversation_context(conversation, history)

    assert result is assembled
    assert captured == {
        "ids": (5, 6),
        "persistent_prompt": "口径约束",
        "current_input": None,
        "previous_summary": "旧摘要",
        "previous_summary_through_message_id": 4,
    }
    assert conversation.context_summary == "压缩后的摘要"
    assert conversation.context_summary_through_message_id == 8
