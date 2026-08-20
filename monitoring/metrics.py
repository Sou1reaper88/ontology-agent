"""Prometheus 指标埋点。

提供 /metrics 端点与通用指标（HTTP 请求量/耗时、LLM 调用耗时、取数执行耗时）。
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.requests import Request
from starlette.responses import Response

REQUEST_COUNT = Counter(
    "http_requests_total",
    "HTTP 请求总数",
    ["method", "path", "status"],
)
REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP 请求耗时（秒）",
    ["method", "path"],
)
LLM_CALL_DURATION = Histogram(
    "llm_call_duration_seconds",
    "商业 LLM 调用耗时（秒）",
)
QUERY_EXECUTION_DURATION = Histogram(
    "query_execution_duration_seconds",
    "取数执行耗时（秒）",
)


def metrics_endpoint(request: Request) -> Response:
    """Prometheus 抓取端点。"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
