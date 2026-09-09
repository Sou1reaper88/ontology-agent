import json
from types import SimpleNamespace

import pytest

from ontology_core.inference_models import CandidateContext, CandidateField, CandidateObject
from ontology_core.metadata_lookup import FieldDetailLookup
from tools.llm_client import LLMClient
from tools.metadata_lookup import generate_with_field_lookup


def test_lookup_rounds_request_json_output_and_preserve_provider_context(monkeypatch):
    field = CandidateField(
        ref="UserId",
        object_ref="User",
        label="用户编号",
        physical_name="USER_ID",
        datatype_uri="string",
        description="关联标识",
    )
    candidates = CandidateContext(
        package_id="test",
        package_version="1",
        package_sha256="a" * 64,
        objects=(
            CandidateObject(
                ref="User",
                label="用户",
                physical_name="USER_D",
                data_source_ref="Hive",
                fields=(field,),
            ),
        ),
    )
    responses = [
        {
            "role": "assistant",
            "content": None,
            "reasoning_content": "synthetic context",
            "tool_calls": [
                {
                    "id": "call1",
                    "type": "function",
                    "function": {
                        "name": "lookup_field_details",
                        "arguments": json.dumps({"field_refs": ["UserId"]}),
                    },
                }
            ],
        },
        {
            "role": "assistant",
            "content": json.dumps(
                {"selected_object_refs": ["User"], "requested_field_refs": ["UserId"]}
            ),
        },
    ]
    payloads = []

    def post(url, **kwargs):
        payloads.append(json.loads(json.dumps(kwargs["json"])))
        msg = responses.pop(0)

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"finish_reason": "stop", "message": msg}]}

        return Response()

    monkeypatch.setattr("httpx.post", post)
    client = LLMClient()
    client.api_key = "synthetic-key"
    client.base_url = "https://example.invalid"
    seen = []

    def lookup(refs):
        seen.append(refs)
        return [field.model_dump(mode="json")]

    plan = client.infer_metadata_program(
        request="查询用户编号", candidates=candidates, lookup_fields=lookup
    )
    assert plan.requested_field_refs == ("UserId",)
    assert seen == [["UserId"]]
    assert len(payloads) == 2
    assert all("max_tokens" not in p for p in payloads)
    assert payloads[0]["response_format"] == {"type": "json_object"}
    assert payloads[1]["response_format"] == {"type": "json_object"}
    assert payloads[1]["messages"][2]["reasoning_content"] == "synthetic context"
    assert payloads[1]["messages"][3]["role"] == "tool"
    assert payloads[1]["tool_choice"] == "none"


def test_lookup_rejects_outside_refs_and_enriches_only_loaded_fields():
    field = CandidateField(
        ref="Key",
        object_ref="User",
        label="编号",
        physical_name="ID",
        datatype_uri="string",
        description="键的完整描述",
    )
    lite = field.model_copy(update={"description": None, "details_loaded": False})
    context = CandidateContext(
        package_id="test",
        package_version="1",
        package_sha256="a" * 64,
        objects=(
            CandidateObject(
                ref="User",
                label="用户",
                physical_name="USER_D",
                data_source_ref="Hive",
                fields=(lite,),
            ),
        ),
    )
    accessed = []

    def get_field(ref):
        accessed.append(ref)
        return field

    lookup = FieldDetailLookup(SimpleNamespace(field=get_field), context)
    with pytest.raises(ValueError):
        lookup(["Outside"])
    with pytest.raises(ValueError):
        lookup([])
    with pytest.raises(ValueError):
        lookup(["Key"] * 65)
    assert accessed == []
    assert lookup(["Key"])[0]["description"] == "键的完整描述"
    assert lookup.enriched().objects[0].fields[0].description == "键的完整描述"
    assert context.objects[0].fields[0].description is None


@pytest.mark.parametrize("mode", ["direct", "repeat", "unknown", "length"])
def test_tool_exchange_is_bounded_and_does_not_retry_bad_output(monkeypatch, mode):
    calls = []
    tool = {
        "id": "c1",
        "type": "function",
        "function": {
            "name": "wrong" if mode == "unknown" else "lookup_field_details",
            "arguments": '{"field_refs":["Key"]}',
        },
    }

    def post(url, **kwargs):
        calls.append(kwargs["json"])

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "choices": [
                        {
                            "finish_reason": "length" if mode == "length" else "stop",
                            "message": {"role": "assistant", "content": "bad JSON"}
                            if mode == "direct"
                            else {"role": "assistant", "tool_calls": [tool], "content": None},
                        }
                    ]
                }

        return Response()

    monkeypatch.setattr("httpx.post", post)
    client = SimpleNamespace(
        api_key="test", base_url="https://example.invalid", model="test", timeout=1
    )
    if mode == "direct":
        assert generate_with_field_lookup(client, "system", "user", lambda refs: []) == "bad JSON"
    else:
        with pytest.raises(ValueError):
            generate_with_field_lookup(client, "system", "user", lambda refs: [])
    assert len(calls) == (2 if mode == "repeat" else 1)
