"""审计日志写入 helper。

供各模块埋点调用：SQL 执行、权限拒绝、取数请求等。
（HTTP 请求层已由 AuditMiddleware 统一记录 http_request，此处补充业务级埋点。）
"""

from __future__ import annotations

from typing import Any

from models import AuditLog
from models.base import SessionLocal


def write_audit_log(
    user_id: int | None,
    action: str,
    detail: dict[str, Any] | None = None,
    status: str = "success",
    ip: str | None = None,
    user_agent: str | None = None,
    duration_ms: int | None = None,
) -> None:
    """同步写一条审计日志（失败静默，不影响主流程）。"""
    db = SessionLocal()
    try:
        db.add(
            AuditLog(
                user_id=user_id,
                action=action,
                detail=detail,
                ip=ip,
                user_agent=user_agent,
                status=status,
                duration_ms=duration_ms,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
