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


SEARCH_TOOL = {
    "type": "function", "function": {
        "name": "search_metadata",
        "description": "搜索同一已发布本体中的表名、表描述、字段名和字段描述，补找输出字段来源或关联表；返回的引用可用于计划及字段详情查询。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 500}},
            "required": ["query"], "additionalProperties": False},
    },
}

VALIDATE_TOOL = {
    "type": "function", "function": {
        "name": "validate_sql_program",
        "description": "静态检查Hive脚本的表字段、分区、临时表DDL、依赖及CTE限制；不执行SQL，不证明业务口径正确。",
        "parameters": {"type": "object", "properties": {
            "sql": {"type": "string", "minLength": 1, "maxLength": 200000},
            "allow_cte": {"type": "boolean", "description": "用户禁止CTE时必须为false"}},
            "required": ["sql", "allow_cte"], "additionalProperties": False},
    },
}


def generate_with_field_lookup(
    client,
    system_prompt: str,
    user_query: str,
    lookup,
    *,
    json_output: bool = False,
    reasoning_effort: str | None = None,
    validate_sql=None,
    on_tool=None,
) -> str:
    if not client.api_key or client.api_key == "your-api-key-here":
        raise ValueError("模型凭据未配置")
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_query},
    ]
    search = getattr(lookup, "search", None)
    tool_rounds = 3 if callable(search) else 1
    # Sequential discovery is allowed; failed final plans are not retried.
    for turn in range(tool_rounds + 1):
        payload = {
            "model": client.model,
            "messages": messages,
            "tools": ([TOOL, SEARCH_TOOL] if callable(search) else [TOOL]) + ([VALIDATE_TOOL] if callable(validate_sql) else []),
            "tool_choice": "auto" if turn < tool_rounds else "none",
            "temperature": client.temperature,
        }
        if client.max_tokens is not None:
            payload["max_tokens"] = client.max_tokens
        if reasoning_effort is not None:
            payload["reasoning_effort"] = reasoning_effort
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
        if turn >= tool_rounds or len(calls) > 4:
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
            if not isinstance(arguments, dict):
                raise MetadataLookupResponseError("arguments_invalid")
            if function["name"] == "validate_sql_program" and callable(validate_sql):
                if (set(arguments) != {"sql", "allow_cte"} or not isinstance(arguments["sql"], str)
                        or not 0 < len(arguments["sql"]) <= 200000 or not isinstance(arguments["allow_cte"], bool)):
                    raise MetadataLookupResponseError("arguments_invalid")
                result = validate_sql(**arguments)
            elif function["name"] == "search_metadata" and callable(search):
                if set(arguments) != {"query"}:
                    raise MetadataLookupResponseError("contract_invalid")
                try:
                    result = search(arguments["query"])
                except ValueError as error:
                    raise MetadataLookupResponseError("arguments_invalid") from error
            elif function["name"] == "lookup_field_details" and set(arguments) == {"field_refs"}:
                refs = arguments["field_refs"]
                if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
                    raise MetadataLookupResponseError("arguments_invalid")
                result = lookup(refs)
            else:
                raise MetadataLookupResponseError("contract_invalid")
            if on_tool:
                on_tool({"tool": function["name"],
                         "valid": result.get("valid") if isinstance(result, dict) else None})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                }
            )
    raise MetadataLookupResponseError("final_plan_missing")
