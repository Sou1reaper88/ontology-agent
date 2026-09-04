"""测试共享 fixtures（harness）。

统一提供：
- LLM mock（强制 Agent 走确定性模板，不调真实 LLM）
- client（TestClient）
- admin_token（管理员 JWT）
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import agent.orchestrator as orch
import agent.conversation_agent as conversation_agent
import tools.ontology_client as ont_client
from api.main import app
from auth.jwt import create_access_token
from models import User
from models.base import SessionLocal
from tools.ontology_client import MockOntologyClient


class _NoKeyClient:
    """无 API Key 的 LLM 客户端替身：迫使 build_sql 走确定性模板。"""

    api_key = ""

    def generate_sql(self, *args, **kwargs):
        raise AssertionError("测试不应调用真实 LLM")


@pytest.fixture(autouse=True)
def _force_mock_sql(monkeypatch):
    """强制 Agent 走确定性模板 + 固定 mock 本体（不读真实 MySQL、不调真实 LLM）。

    保证编排/接口测试快速稳定、不依赖用户手工维护的表结构。
    """
    monkeypatch.setattr(orch, "get_llm_client", lambda: _NoKeyClient())
    monkeypatch.setattr(conversation_agent, "get_llm_client", lambda: _NoKeyClient())
    monkeypatch.setattr(ont_client, "get_llm_client", lambda: _NoKeyClient())
    # 编排流程使用固定 mock 本体（5 字段示例表），与真实 MySQL 表结构解耦
    monkeypatch.setattr(orch, "get_ontology_client", lambda: MockOntologyClient())
    monkeypatch.setattr(ont_client, "get_ontology_client", lambda: MockOntologyClient())


@pytest.fixture(autouse=True)
def _clear_ontology_cache():
    """每个测试前清空元数据 TTL 缓存，避免真实 DB 测试读到脏缓存。"""
    ont_client.clear_ontology_cache()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def admin_token() -> str:
    """返回 admin 用户的 JWT（需先运行 scripts.seed）。"""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "admin").first()
        assert user is not None, "admin 用户不存在，请先运行 scripts.seed"
    finally:
        db.close()
    return create_access_token(user.id, user.username, user.role_id)


# ---------------------------------------------------------------------------
# 异步消息（202 + 轮询）共享辅助
# ---------------------------------------------------------------------------


def wait_message_done(client: TestClient, token: str, msg_id: int, timeout: float = 15.0) -> dict:
    """轮询消息生成状态直到 success/failed，返回状态数据。"""
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(
            f"/conversations/messages/{msg_id}/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        if data["status"] in ("success", "failed"):
            return data
        time.sleep(0.05)
    raise AssertionError(f"消息 {msg_id} 生成超时")


def send_and_wait(client: TestClient, token: str, cid: int, content: str, **kw) -> tuple[dict, int]:
    """异步发消息（202）并等待生成完成，返回 (状态数据, msg_id)。"""
    resp = client.post(
        f"/conversations/{cid}/messages",
        json={"content": content, **kw},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202, resp.text
    msg_id = resp.json()["message_id"]
    data = wait_message_done(client, token, msg_id)
    assert data["status"] == "success", data.get("error")
    return data, msg_id


def last_assistant_message(client: TestClient, token: str, cid: int) -> dict:
    """对话详情中最后一条 assistant 消息（含 sql/query_id/trace）。"""
    resp = client.get(f"/conversations/{cid}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    msgs = resp.json()["messages"]
    asst = [m for m in msgs if m["role"] == "assistant"]
    assert asst, "无 assistant 消息"
    return asst[-1]
