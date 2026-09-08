"""认证接口测试（阶段 3）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

import api.routes.conversation as conversation_route


def _enable_legacy_compatibility(monkeypatch) -> None:
    original = conversation_route.run_agent

    def run_with_legacy(*args, **kwargs):
        return original(*args, **kwargs, allow_legacy_compatibility=True)

    monkeypatch.setattr(conversation_route, "run_agent", run_with_legacy)


def test_login_success(client: TestClient) -> None:
    """正确凭据登录成功，返回 JWT。"""
    resp = client.post(
        "/auth/login", json={"username": "admin", "password": "admin123"}
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]


def test_login_wrong_password(client: TestClient) -> None:
    """错误密码返回 401。"""
    resp = client.post(
        "/auth/login", json={"username": "admin", "password": "wrong"}
    )
    assert resp.status_code == 401


def test_login_unknown_user(client: TestClient) -> None:
    """未知用户返回 401。"""
    resp = client.post(
        "/auth/login", json={"username": "ghost", "password": "x"}
    )
    assert resp.status_code == 401


def test_query_requires_auth(client: TestClient) -> None:
    """对话接口未带 token 返回 401。"""
    resp = client.post("/conversations", json={})
    assert resp.status_code == 401


def test_query_with_token(client: TestClient, admin_token: str, monkeypatch) -> None:
    """带管理员 token 通过对话发消息生成 SQL（权限校验通过）。"""
    from tests.conftest import last_assistant_message, send_and_wait

    _enable_legacy_compatibility(monkeypatch)
    resp = client.post(
        "/conversations",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    cid = resp.json()["id"]
    send_and_wait(client, admin_token, cid, "查询6月沉默用户", system_time="2026-08-14")
    asst = last_assistant_message(client, admin_token, cid)
    assert asst["sql"] and "D_BBZX_DW_PRODUCT_M" in asst["sql"]
