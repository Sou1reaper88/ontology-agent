"""审计日志接口 + 埋点 helper 测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from audit.utils import write_audit_log
from models import AuditLog
from models.base import SessionLocal


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_audit_logs_endpoint(client: TestClient, admin_token: str) -> None:
    """审计日志接口：分页 + 过滤可用。"""
    resp = client.get("/audit-logs", headers=_headers(admin_token))
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data and "total" in data and "page" in data

    # action 过滤
    resp = client.get("/audit-logs", params={"action": "http_request"}, headers=_headers(admin_token))
    assert resp.status_code == 200
    assert all(i["action"] == "http_request" for i in resp.json()["items"])


def test_write_audit_log_helper() -> None:
    """write_audit_log 写入后可在 audit_logs 查到。"""
    write_audit_log(
        user_id=None,
        action="test_action",
        detail={"key": "value"},
        status="success",
    )
    db = SessionLocal()
    try:
        log = (
            db.query(AuditLog)
            .filter(AuditLog.action == "test_action")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert log is not None
        assert log.status == "success"
        assert log.detail == {"key": "value"}
    finally:
        db.close()
