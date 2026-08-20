"""审计日志查询接口：GET /audit-logs（分页 + action/status 过滤）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth.jwt import get_current_user
from models import AuditLog, User
from models.base import get_db

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("")
def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    action: str | None = None,
    status: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """审计日志列表（倒序，按 action/status 可选过滤）。"""
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    if status:
        q = q.filter(AuditLog.status == status)
    total = q.count()
    logs = (
        q.order_by(AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # user_id → username 映射
    user_ids = {l.user_id for l in logs if l.user_id}
    username_map: dict[int, str] = {}
    if user_ids:
        for u in db.query(User).filter(User.id.in_(user_ids)).all():
            username_map[u.id] = u.username

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": l.id,
                "user_id": l.user_id,
                "username": username_map.get(l.user_id) if l.user_id else None,
                "action": l.action,
                "detail": l.detail,
                "status": l.status,
                "ip": l.ip,
                "duration_ms": l.duration_ms,
                "created_at": l.created_at.isoformat(),
            }
            for l in logs
        ],
    }
