from __future__ import annotations

from typing import Any

from tools.llm_client import LLMClient


def _configured_client() -> LLMClient:
    client = LLMClient()
    client.api_key = "synthetic-key"
    client.base_url = "https://example.invalid"
    return client


def _capturing_post(payloads: list[dict[str, Any]], content: str):
    def post(_url: str, **kwargs: Any):
        payloads.append(kwargs["json"])

        class Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, Any]:
                return {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": content},
                        }
                    ]
                }

        return Response()

    return post


def test_structured_generation_requests_deepseek_json_output(monkeypatch) -> None:
    payloads: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "httpx.post",
        _capturing_post(payloads, '{"intent": {}, "steps": []}'),
    )

    _configured_client()._generate("return json", "request", json_output=True)

    assert payloads[0]["response_format"] == {"type": "json_object"}


def test_text_generation_does_not_force_json_output(monkeypatch) -> None:
    payloads: list[dict[str, Any]] = []
    monkeypatch.setattr("httpx.post", _capturing_post(payloads, "plain reply"))

    _configured_client()._generate("answer naturally", "request")

    assert "response_format" not in payloads[0]


def test_unconfigured_output_limit_is_not_sent_to_provider(monkeypatch) -> None:
    payloads: list[dict[str, Any]] = []
    client = _configured_client()
    client.max_tokens = None
    monkeypatch.setattr("httpx.post", _capturing_post(payloads, "plain reply"))

    client._generate("answer naturally", "request")

    assert "max_tokens" not in payloads[0]


def test_metadata_inference_uses_low_reasoning_effort() -> None:
    calls: list[tuple[bool, str | None]] = []

    class CapturingClient(LLMClient):
        def __init__(self) -> None:
            self.model = "deepseek-v4-flash"

        def _generate(
            self,
            system_prompt: str,
            user_query: str,
            *,
            json_output: bool = False,
            reasoning_effort: str | None = None,
        ) -> str:
            calls.append((json_output, reasoning_effort))
            return '{"selected_object_refs": ["Customer"], "requested_field_refs": ["CustomerMobile"]}'

    from tests.test_metadata_inference_llm import _candidates

    CapturingClient().infer_metadata_program(
        request="查询客户", candidates=_candidates()
    )

    assert calls == [(True, "low")]


def test_metadata_inference_omits_deepseek_option_for_other_providers() -> None:
    calls: list[str | None] = []

    class CapturingClient(LLMClient):
        def __init__(self) -> None:
            self.model = "other-model"

        def _generate(
            self,
            system_prompt: str,
            user_query: str,
            *,
            json_output: bool = False,
            reasoning_effort: str | None = None,
        ) -> str:
            calls.append(reasoning_effort)
            return '{"selected_object_refs": ["Customer"], "requested_field_refs": ["CustomerMobile"]}'

    from tests.test_metadata_inference_llm import _candidates

    CapturingClient().infer_metadata_program(
        request="查询客户", candidates=_candidates()
    )

    assert calls == [None]


def test_program_planning_enables_json_output() -> None:
    calls: list[bool] = []

    class CapturingClient(LLMClient):
        def __init__(self) -> None:
            pass

        def _generate(
            self,
            system_prompt: str,
            user_query: str,
            *,
            json_output: bool = False,
        ) -> str:
            calls.append(json_output)
            return '{"intent": {}, "steps": []}'

    try:
        CapturingClient().plan_sql_program(system_prompt="return json", user_query="request")
    except Exception:
        pass

    assert calls == [True]
