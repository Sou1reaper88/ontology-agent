"""审计中间件：记录所有 HTTP 请求到 audit_logs。"""

from __future__ import annotations

import re
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from models import AuditLog
from models.base import SessionLocal
from monitoring.metrics import REQUEST_COUNT, REQUEST_DURATION


class AuditMiddleware(BaseHTTPMiddleware):
    """全链路审计 + Prometheus 指标：每个请求记录 方法/路径/状态/耗时/IP/UA。"""

    async def dispatch(self, request: Request, call_next):
        start = time.time()
        # 尝试从 request.state 读取认证依赖注入的用户（若已认证）
        user_id = getattr(request.state, "user_id", None)
        response = await call_next(request)
        elapsed = time.time() - start
        duration_ms = int(elapsed * 1000)
        # Prometheus 指标
        REQUEST_COUNT.labels(request.method, request.url.path, response.status_code).inc()
        REQUEST_DURATION.labels(request.method, request.url.path).observe(elapsed)
        db = SessionLocal()
        try:
            db.add(
                AuditLog(
                    user_id=user_id,
                    action="http_request",
                    detail={
                        "method": request.method,
                        "path": _safe_audit_path(request.url.path),
                        "query": _safe_audit_query(request.url.path, str(request.url.query)),
                        "status": response.status_code,
                    },
                    ip=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent"),
                    status="success" if response.status_code < 400 else "failed",
                    duration_ms=duration_ms,
                )
            )
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
        return response


def _safe_audit_path(path: str) -> str:
    """Keep import confirmation bearer tokens out of generic HTTP audit records."""
    return re.sub(
        r"(/ontology-packages/workspaces/[^/]+/imports/)[^/]+(/confirm)$",
        r"\1<redacted>\2",
        path,
    )


def _safe_audit_query(path: str, query: str) -> str | None:
    """Do not retain arbitrary query values for management requests."""
    if path.startswith("/ontology-packages"):
        return None
    return query or None
