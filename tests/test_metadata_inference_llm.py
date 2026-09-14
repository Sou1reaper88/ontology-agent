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
from tools.metadata_lookup import MetadataLookupResponseError
from tests.ontology_core.test_relation_evidence import _catalog
from ontology_core.relation_evidence import build_relation_evidence_graph


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
        self.model = "deepseek-v4-flash"
        self.calls: list[tuple[str, str, bool, str | None]] = []
    def _generate(
        self,
        system_prompt: str,
        user_query: str,
        *,
        json_output: bool = False,
        reasoning_effort: str | None = None,
    ) -> str:
        self.calls.append((system_prompt, user_query, json_output, reasoning_effort))
        return self.response


def test_schema_failure_preserves_safe_locations_not_input_values():
    client = _RawClient('{"selected_object_refs":["Customer"],"requested_field_refs":["CustomerMobile"],"filters":[{"field_ref":"CustomerMobile","operator":"SECRET_SENTINEL","confidence":"medium","evidence":["synthetic"]}]}')
    with pytest.raises(StructuredPlanningError) as captured:
        client.infer_metadata_program(request="查询客户", candidates=_candidates())
    assert captured.value.category == "schema_validation"
    assert captured.value.details[0]["location"] == "filters.0.operator"
    assert "SECRET_SENTINEL" not in json.dumps(captured.value.details)


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
    system_prompt, user_query, json_output, reasoning_effort = client.calls[0]
    assert "禁止输出 SQL" in system_prompt
    assert "禁止输出目标表名" in system_prompt
    assert "只能引用候选目录" in system_prompt
    assert "time_expression" in system_prompt
    assert "分区字段不得写入 filters" in system_prompt
    assert "自然时间表达" in system_prompt
    assert "group_by_field_refs" in system_prompt
    assert "aggregations" in system_prompt
    payload = json.loads(user_query)
    assert payload["request"] == "查询客户手机号码"
    assert payload["conversation_context"] == "用户已确认客户指个人客户"
    assert payload["candidates"]["objects"][0]["physical_name"] == "CUSTOMER_D"
    assert "properties" in payload["schema"]
    assert json_output is True
    assert reasoning_effort == "low"


def test_inference_request_omits_absent_conversation_context() -> None:
    client = _RawClient(_valid_response())

    client.infer_metadata_program(request="查询客户手机号码", candidates=_candidates())

    payload = json.loads(client.calls[0][1])
    assert "conversation_context" not in payload
    assert client.calls[0][2] is True


def test_inference_sends_confirmed_relationship_evidence_to_model() -> None:
    candidates, catalog = _catalog(confirmed=True)
    graph = build_relation_evidence_graph(candidates, catalog)
    client = _RawClient(_valid_response())
    client.infer_metadata_program(
        request="查询客户",
        candidates=candidates,
        relation_evidence=graph,
    )
    payload = json.loads(client.calls[0][1])
    assert payload["relation_evidence"] == graph.model_dump(mode="json")
    assert "关系图允许为空" in client.calls[0][0]


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


def test_inference_classifies_invalid_lookup_response_without_exposing_it(
    monkeypatch,
) -> None:
    def invalid_lookup_response(*args, **kwargs):
        raise ValueError("tool-response-secret")

    monkeypatch.setattr(
        "tools.metadata_lookup.generate_with_field_lookup",
        invalid_lookup_response,
    )

    with pytest.raises(StructuredPlanningError) as caught:
        _RawClient("").infer_metadata_program(
            request="查询客户手机号码",
            candidates=_candidates(),
            lookup_fields=lambda refs: [],
        )

    assert caught.value.category == "tool_response_invalid"
    assert "tool-response-secret" not in str(caught.value)


def test_inference_preserves_safe_lookup_response_category(monkeypatch) -> None:
    def empty_lookup_response(*args, **kwargs):
        raise MetadataLookupResponseError("empty_response")

    monkeypatch.setattr(
        "tools.metadata_lookup.generate_with_field_lookup",
        empty_lookup_response,
    )

    with pytest.raises(StructuredPlanningError) as caught:
        _RawClient("").infer_metadata_program(
            request="查询客户手机号码",
            candidates=_candidates(),
            lookup_fields=lambda refs: [],
        )

    assert caught.value.category == "tool_response_empty_response"
