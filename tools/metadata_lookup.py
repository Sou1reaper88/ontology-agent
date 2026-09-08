"""A bounded read-only tool round, not a failed-plan repair loop."""

import json

import httpx

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


def generate_with_field_lookup(client, system_prompt: str, user_query: str, lookup) -> str:
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
        }
        response = httpx.post(
            f"{client.base_url.rstrip('/')}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {client.api_key}"},
            timeout=client.timeout,
        )
        response.raise_for_status()
        choice = response.json()["choices"][0]
        if choice.get("finish_reason") == "length":
            raise ValueError("模型达到服务端输出上限")
        message = choice["message"]
        calls = message.get("tool_calls") or []
        if not calls:
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("模型未返回正文")
            return content
        if turn or len(calls) > 4:
            raise ValueError("超出本轮元数据查询次数")
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
            arguments = json.loads(function["arguments"])
            if function["name"] != "lookup_field_details" or set(arguments) != {"field_refs"}:
                raise ValueError("不支持的元数据查询")
            refs = arguments["field_refs"]
            if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
                raise ValueError("字段引用必须是字符串数组")
            result = lookup(refs)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                }
            )
    raise ValueError("模型未返回最终计划")
