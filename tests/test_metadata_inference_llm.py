from __future__ import annotations

import json

import pytest

from ontology_core.inference_models import (
    CandidateContext,
    CandidateField,
    CandidateObject,
    InferredProgramDraft,
)
from tools.llm_client import LLMClient, StructuredPlanningError


def _candidates() -> CandidateContext:
    return CandidateContext(
        package_id="evaluation",
        package_version="1.0.0",
        package_sha256="a" * 64,
        objects=(
            CandidateObject(
                ref="Customer",
                label="客户",
                description="客户主数据",
                data_source_ref="Hive",
                physical_namespace="dm",
                physical_name="CUSTOMER_D",
                fields=(
                    CandidateField(
                        ref="CustomerMobile",
                        object_ref="Customer",
                        label="手机号码",
                        description="客户手机号码",
                        datatype_uri="http://www.w3.org/2001/XMLSchema#string",
                        physical_name="MOBILE_NO",
                        retrieval_score=100,
                        matched_terms=("手机号码",),
                    ),
                ),
                retrieval_score=120,
                matched_terms=("客户",),
            ),
        ),
    )


class _RawClient(LLMClient):
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, str, bool]] = []

    def _generate(
        self,
        system_prompt: str,
        user_query: str,
        *,
        json_output: bool = False,
    ) -> str:
        self.calls.append((system_prompt, user_query, json_output))
        return self.response


def _valid_response() -> str:
    return InferredProgramDraft(
        selected_object_refs=("Customer",),
        requested_field_refs=("CustomerMobile",),
    ).model_dump_json()


def test_inference_request_contains_bounded_candidates_context_and_schema() -> None:
    client = _RawClient(_valid_response())

    draft = client.infer_metadata_program(
        request="查询客户手机号码",
        candidates=_candidates(),
        conversation_context="用户已确认客户指个人客户",
    )

    assert draft.selected_object_refs == ("Customer",)
    system_prompt, user_query, json_output = client.calls[0]
    assert "禁止输出 SQL" in system_prompt
    assert "禁止输出目标表名" in system_prompt
    assert "只能引用候选目录" in system_prompt
    assert "time_expression" in system_prompt
    assert "分区字段不得写入 filters" in system_prompt
    payload = json.loads(user_query)
    assert payload["request"] == "查询客户手机号码"
    assert payload["conversation_context"] == "用户已确认客户指个人客户"
    assert payload["candidates"]["objects"][0]["physical_name"] == "CUSTOMER_D"
    assert "properties" in payload["schema"]
    assert json_output is True


def test_inference_request_omits_absent_conversation_context() -> None:
    client = _RawClient(_valid_response())

    client.infer_metadata_program(request="查询客户手机号码", candidates=_candidates())

    payload = json.loads(client.calls[0][1])
    assert "conversation_context" not in payload
    assert client.calls[0][2] is True


def test_inference_rejects_model_sql_field_without_exposing_output() -> None:
    client = _RawClient(
        json.dumps(
            {
                "selected_object_refs": ["Customer"],
                "requested_field_refs": ["CustomerMobile"],
                "sql": "select secret_value from hidden_table",
            }
        )
    )

    with pytest.raises(StructuredPlanningError) as caught:
        client.infer_metadata_program(
            request="查询客户手机号码",
            candidates=_candidates(),
        )

    assert "secret_value" not in str(caught.value)


def test_inference_sanitizes_provider_failure() -> None:
    class _FailingClient(_RawClient):
        def _generate(self, system_prompt: str, user_query: str) -> str:
            raise RuntimeError("provider-secret")

    with pytest.raises(StructuredPlanningError) as caught:
        _FailingClient("").infer_metadata_program(
            request="查询客户手机号码",
            candidates=_candidates(),
        )

    assert "provider-secret" not in str(caught.value)

