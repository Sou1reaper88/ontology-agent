"""A bounded read-only tool round, not a failed-plan repair loop."""

import json

import httpx


class MetadataLookupResponseError(ValueError):
    """A sanitized category for an invalid model tool-round response."""

    def __init__(self, reason: str) -> None:
        super().__init__("元数据查询工具响应无效")
        self.reason = reason


TOOL = {
    "type": "function",
    "function": {
        "name": "lookup_field_details",
        "description": "读取索引内字段的完整描述和类型；支持批量查询输出字段、关联键与取值口径。",
        "parameters": {
            "type": "object",
            "properties": {
                "field_refs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 64,
                }
            },
            "required": ["field_refs"],
            "additionalProperties": False,
        },
    },
}


def generate_with_field_lookup(
    client,
    system_prompt: str,
    user_query: str,
    lookup,
    *,
    json_output: bool = False,
) -> str:
    if not client.api_key or client.api_key == "your-api-key-here":
        raise ValueError("模型凭据未配置")
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_query},
    ]
    # At most one metadata lookup round, followed by one final plan response.
    for turn in range(2):
        payload = {
            "model": client.model,
            "messages": messages,
            "tools": [TOOL],
            "tool_choice": "auto" if turn == 0 else "none",
            "temperature": client.temperature,
        }
        if client.max_tokens is not None:
            payload["max_tokens"] = client.max_tokens
        if json_output:
            payload["response_format"] = {"type": "json_object"}
        response = httpx.post(
            f"{client.base_url.rstrip('/')}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {client.api_key}"},
            timeout=client.timeout,
        )
        response.raise_for_status()
        choice = response.json()["choices"][0]
        if choice.get("finish_reason") == "length":
            raise MetadataLookupResponseError("output_truncated")
        message = choice["message"]
        calls = message.get("tool_calls") or []
        if not calls:
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise MetadataLookupResponseError("empty_response")
            return content
        if turn or len(calls) > 4:
            raise MetadataLookupResponseError("call_limit")
        # DeepSeek requires the returned reasoning context for tool continuations.
        messages.append(
            {
                k: v
                for k, v in message.items()
                if k in {"role", "content", "tool_calls", "reasoning_content"}
            }
        )
        for call in calls:
            function = call["function"]
            try:
                arguments = json.loads(function["arguments"])
            except (KeyError, TypeError, ValueError) as error:
                raise MetadataLookupResponseError("arguments_invalid") from error
            if function["name"] != "lookup_field_details" or set(arguments) != {"field_refs"}:
                raise MetadataLookupResponseError("contract_invalid")
            refs = arguments["field_refs"]
            if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
                raise MetadataLookupResponseError("arguments_invalid")
            result = lookup(refs)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                }
            )
    raise MetadataLookupResponseError("final_plan_missing")
