"""审计中间件：记录所有 HTTP 请求到 audit_logs。"""

from __future__ import annotations

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
        REQUEST_COUNT.labels(
            request.method, request.url.path, response.status_code
        ).inc()
        REQUEST_DURATION.labels(request.method, request.url.path).observe(elapsed)
        db = SessionLocal()
        try:
            db.add(
                AuditLog(
                    user_id=user_id,
                    action="http_request",
                    detail={
                        "method": request.method,
                        "path": request.url.path,
                        "query": str(request.url.query) or None,
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
