"""Resolve model token capabilities without coupling callers to providers."""

from __future__ import annotations

from dataclasses import dataclass

from config.settings import LLMSettings


@dataclass(frozen=True)
class ModelTokenLimits:
    """Resolved context, input, and output limits for one model."""

    context_window_tokens: int
    max_input_tokens: int
    max_output_tokens: int


_SAFE_DEFAULTS = ModelTokenLimits(
    context_window_tokens=32_768,
    max_input_tokens=32_768,
    max_output_tokens=4_096,
)

_MODEL_DEFAULTS = {
    "deepseek-flash": ModelTokenLimits(
        context_window_tokens=1_000_000,
        max_input_tokens=1_000_000,
        max_output_tokens=393_216,
    ),
}


def resolve_model_token_limits(llm: LLMSettings) -> ModelTokenLimits:
    """Resolve explicit limits, legacy overrides, then model defaults."""

    defaults = _MODEL_DEFAULTS.get(llm.model.strip().lower(), _SAFE_DEFAULTS)
    context_window_tokens = llm.context_window_tokens or defaults.context_window_tokens
    max_input_tokens = (
        llm.max_input_tokens
        or llm.context_window_tokens
        or defaults.max_input_tokens
    )
    max_output_tokens = (
        llm.max_output_tokens or llm.max_tokens or defaults.max_output_tokens
    )
    return ModelTokenLimits(
        context_window_tokens=context_window_tokens,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
    )
