from __future__ import annotations

from agent.model_capabilities import resolve_model_token_limits
from config.settings import LLMSettings


def test_deepseek_flash_uses_model_defaults_when_limits_are_unset() -> None:
    limits = resolve_model_token_limits(
        LLMSettings(
            model="deepseek-flash",
            max_input_tokens=None,
            max_output_tokens=None,
            context_window_tokens=None,
            max_tokens=None,
        )
    )

    assert limits.context_window_tokens == 1_000_000
    assert limits.max_input_tokens == 1_000_000
    assert limits.max_output_tokens == 393_216


def test_explicit_new_limits_override_model_defaults() -> None:
    limits = resolve_model_token_limits(
        LLMSettings(
            model="deepseek-flash",
            max_input_tokens=120_000,
            max_output_tokens=8_000,
            context_window_tokens=None,
            max_tokens=None,
        )
    )

    assert limits.max_input_tokens == 120_000
    assert limits.max_output_tokens == 8_000


def test_legacy_limits_remain_compatible() -> None:
    limits = resolve_model_token_limits(
        LLMSettings(
            model="deepseek-flash",
            max_input_tokens=None,
            max_output_tokens=None,
            context_window_tokens=64_000,
            max_tokens=4_096,
        )
    )

    assert limits.context_window_tokens == 64_000
    assert limits.max_input_tokens == 64_000
    assert limits.max_output_tokens == 4_096


def test_unknown_model_uses_safe_defaults() -> None:
    limits = resolve_model_token_limits(
        LLMSettings(
            model="private-model",
            max_input_tokens=None,
            max_output_tokens=None,
            context_window_tokens=None,
            max_tokens=None,
        )
    )

    assert limits.context_window_tokens == 32_768
    assert limits.max_input_tokens == 32_768
    assert limits.max_output_tokens == 4_096


def test_retired_deepseek_v4_flash_name_uses_safe_defaults() -> None:
    limits = resolve_model_token_limits(
        LLMSettings(
            model="deepseek-v4-flash",
            max_input_tokens=None,
            max_output_tokens=None,
            context_window_tokens=None,
            max_tokens=None,
        )
    )

    assert limits.context_window_tokens == 32_768
    assert limits.max_input_tokens == 32_768
    assert limits.max_output_tokens == 4_096
