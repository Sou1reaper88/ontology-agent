"""对话接口单元测试：创建/列表/详情/发消息（多轮）/上下文传递/权限隔离/删除。

依赖 conftest：LLM mock（走确定性模板）、client、admin_token、send_and_wait。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import api.routes.conversation as conv_route
from tests.conftest import last_assistant_message, send_and_wait


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_conv(client: TestClient, token: str, **kw) -> dict:
    resp = client.post("/conversations", json={"title": "测试对话", **kw}, headers=_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_conversation(client: TestClient, admin_token: str) -> None:
    data = _create_conv(client, admin_token, context="用户范围为浙江省")
    assert data["id"] > 0
    assert data["context"] == "用户范围为浙江省"


def test_send_message_generates_sql(client: TestClient, admin_token: str) -> None:
    conv = _create_conv(client, admin_token)
    _, msg_id = send_and_wait(
        client,
        admin_token,
        conv["id"],
        "查询6月沉默用户",
        system_time="2026-08-14",
    )
    # 建表程序落库到 assistant 消息，但不创建可执行 query_history。
    asst = last_assistant_message(client, admin_token, conv["id"])
    assert asst["id"] == msg_id
    assert asst["sql"] and "D_BBZX_DW_PRODUCT_M" in asst["sql"]
    assert asst["query_id"] is None
    assert asst["program"]["mode"] == "wrapped_legacy"
    assert asst["program"]["platform"] == "hive"
    assert asst["program"]["steps"][0]["target_table"].startswith("temp_oa_")
    assert "DROP TABLE" not in asst["content"]
    # 链路 trace 已采集（含检索/映射/生成/校验步骤）
    assert asst["trace"] and any(s["node"] == "program_generation" for s in asst["trace"])


def test_conversation_persists_and_returns_shadow_payload(
    client: TestClient,
    admin_token: str,
    monkeypatch,
) -> None:
    shadow = {
        "status": "generated",
        "ontology_sql": 'SELECT "metric" FROM "semantic"."records";',
        "summary": "本体 SQL 与现有 SQL 存在差异",
        "diff": {
            "changed": True,
            "legacy_tables": ["legacy.table"],
            "ontology_tables": ["semantic.records"],
        },
        "evidence": {
            "concepts": ["Record"],
            "properties": ["Metric"],
            "rules": [],
            "data_sources": ["Warehouse"],
            "mappings": ["RecordTable", "MetricField"],
        },
        "package": {"package_id": "example.shadow", "version": "1.0.0", "sha256": "a" * 12},
        "temporal_decision": {
            "partition_field": "p_mon",
            "grain": "month",
            "policy_source": "ontology",
            "system_time": "2026-08-24",
            "user_time": None,
            "source": "ontology_default",
            "default_strategy": "previous_complete_month",
            "resolved_start": "202607",
            "resolved_end": "202607",
            "safety_status": "bounded",
            "explanation": "用户未指定账期，按本体策略取上一个完整自然月",
        },
    }

    def fake_run_agent(query, **kwargs):
        step = {
            "node": "ontology_shadow",
            "label": "本体规划与编译",
            "status": "success",
            "duration_ms": 1,
            "summary": shadow["summary"],
            "payload": shadow,
        }
        kwargs["on_step"](step)
        return {
            "success": True,
            "sql": "SELECT 1;",
            "markdown": "ok",
            "trace": [step],
            "ontology_shadow": shadow,
        }

    monkeypatch.setattr(conv_route, "run_agent", fake_run_agent)
    conv = _create_conv(client, admin_token)

    status, _ = send_and_wait(client, admin_token, conv["id"], "查询记录指标")
    message = last_assistant_message(client, admin_token, conv["id"])

    assert status["ontology_shadow"] == shadow
    assert message["ontology_shadow"] == shadow
    assert message["sql"] == "SELECT 1;"
    assert message["query_id"] is not None


def test_send_message_status_steps_progress(client: TestClient, admin_token: str) -> None:
    """异步发消息返回 202 generating；轮询状态逐步返回步骤。"""
    conv = _create_conv(client, admin_token)
    resp = client.post(
        f"/conversations/{conv['id']}/messages",
        json={"content": "查询6月沉默用户", "system_time": "2026-08-14"},
        headers=_headers(admin_token),
    )
    assert resp.status_code == 202
    assert resp.json()["status"] == "generating"
    msg_id = resp.json()["message_id"]
    data = None
    import time

    deadline = time.time() + 15
    while time.time() < deadline:
        r = client.get(
            f"/conversations/messages/{msg_id}/status",
            headers=_headers(admin_token),
        )
        assert r.status_code == 200
        data = r.json()
        if data["status"] == "success":
            break
        time.sleep(0.05)
    assert data is not None and data["status"] == "success"
    nodes = [s["node"] for s in data["steps"]]
    # 关键链路步骤齐全且有序
    for key in ("get_ttl_definition", "build_sql", "validate_syntax", "validate_semantics"):
        assert key in nodes, f"trace 缺少步骤 {key}: {nodes}"
    assert nodes.index("get_ttl_definition") < nodes.index("build_sql")


def test_multi_turn_accumulates(client: TestClient, admin_token: str) -> None:
    conv = _create_conv(client, admin_token)
    for content in ["查询6月沉默用户", "把沉默时间改成3个月"]:
        send_and_wait(client, admin_token, conv["id"], content, system_time="2026-08-14")
    detail = client.get(f"/conversations/{conv['id']}", headers=_headers(admin_token))
    assert detail.status_code == 200
    msgs = detail.json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]


def test_irrelevant_question_returns_hint(
    client: TestClient, admin_token: str, monkeypatch
) -> None:
    """无关问题 → 消息返回友好提示，不生成 SQL。"""
    import agent.orchestrator as orch
    from tools.ontology_client import IRRELEVANT_MESSAGE

    class _FakeClient:
        def get_ontology_definition(self, *a, **k):
            return {
                "object_classes": {},
                "logical_definitions": {},
                "relations": [],
                "field_meta": {},
                "irrelevant": True,
                "message": IRRELEVANT_MESSAGE,
            }

        def get_attr_mapping(self, *a, **k):
            return {}

    monkeypatch.setattr(orch, "get_ontology_client", lambda: _FakeClient())
    conv = _create_conv(client, admin_token)
    _, msg_id = send_and_wait(client, admin_token, conv["id"], "今天天气怎么样")
    asst = last_assistant_message(client, admin_token, conv["id"])
    assert asst["id"] == msg_id
    assert "与取数业务无关" in asst["content"]
    assert asst["sql"] is None
    assert asst["query_id"] is None


def test_history_and_context_passed_to_agent(
    client: TestClient, admin_token: str, monkeypatch
) -> None:
    """验证发消息时：历史消息 + 对话上下文被传给 run_agent（后台线程执行）。"""
    captured: dict = {}

    def fake_run_agent(query, **kwargs):
        captured["query"] = query
        captured.update(kwargs)
        return {"success": True, "sql": "SELECT 1;", "markdown": "ok"}

    monkeypatch.setattr(conv_route, "run_agent", fake_run_agent)

    conv = _create_conv(client, admin_token, context="浙江省正常在网用户")
    # 第一轮
    send_and_wait(client, admin_token, conv["id"], "查询6月沉默用户")
    # 第二轮（此时 fake_run_agent 的 captured 已被后台线程写入）
    _, second_msg_id = send_and_wait(client, admin_token, conv["id"], "改成3个月")
    assert captured["query"] == "改成3个月"
    assert captured["conversation_context"] == "浙江省正常在网用户"
    assert len(captured["history"]) == 2  # user + assistant
    assert captured["history"][0]["role"] == "user"
    assert captured["request_id"] == f"conversation:{conv['id']}:message:{second_msg_id}"


def test_program_metadata_survives_message_reload_without_query_action(
    client: TestClient,
    admin_token: str,
    monkeypatch,
) -> None:
    payload = {
        "program_id": "a1b2c3d4e5f6",
        "platform": "hive",
        "generation_mode": "program",
        "program_steps": [
            {
                "step_id": "result",
                "target_table": "temp_oa_a1b2c3d4e5f6_result_table",
                "drop_sql": "DROP TABLE IF EXISTS temp_oa_a1b2c3d4e5f6_result_table;",
                "create_sql": "CREATE TABLE temp_oa_a1b2c3d4e5f6_result_table AS SELECT 1;",
            }
        ],
        "diagnostics": [],
        "package": {"package_id": "example.program", "version": "1.0.0", "sha256": "a" * 64},
        "temporal_evidence": [],
    }
    step = {
        "node": "program_generation",
        "label": "本体程序规划与编译",
        "status": "success",
        "duration_ms": 1,
        "summary": "已生成 1 个物化步骤",
        "payload": payload,
    }

    def fake_run_agent(query, **kwargs):
        kwargs["on_step"](step)
        return {
            "success": True,
            "sql": (
                "DROP TABLE IF EXISTS temp_oa_a1b2c3d4e5f6_result_table;\n"
                "CREATE TABLE temp_oa_a1b2c3d4e5f6_result_table AS SELECT 1;"
            ),
            "markdown": "已生成 1 个物化步骤。",
            "trace": [step],
            **payload,
        }

    monkeypatch.setattr(conv_route, "run_agent", fake_run_agent)
    conv = _create_conv(client, admin_token)
    send_and_wait(client, admin_token, conv["id"], "生成结果表")

    first = last_assistant_message(client, admin_token, conv["id"])
    reloaded = client.get(
        f"/conversations/{conv['id']}",
        headers=_headers(admin_token),
    ).json()["messages"][-1]

    assert first["query_id"] is None
    assert first["program"] == reloaded["program"]
    assert reloaded["program"]["program_id"] == "a1b2c3d4e5f6"
    assert reloaded["program"]["steps"][0]["step_id"] == "result"


def test_context_update(client: TestClient, admin_token: str) -> None:
    conv = _create_conv(client, admin_token)
    resp = client.patch(
        f"/conversations/{conv['id']}",
        json={"context": "账期统一为2026年6月", "title": "新标题"},
        headers=_headers(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["context"] == "账期统一为2026年6月"
    assert resp.json()["title"] == "新标题"


def test_delete_conversation(client: TestClient, admin_token: str) -> None:
    conv = _create_conv(client, admin_token)
    assert (
        client.delete(f"/conversations/{conv['id']}", headers=_headers(admin_token)).status_code
        == 204
    )
    assert (
        client.get(f"/conversations/{conv['id']}", headers=_headers(admin_token)).status_code == 404
    )


def test_conversation_requires_auth(client: TestClient) -> None:
    assert client.get("/conversations").status_code == 401
    assert client.post("/conversations", json={}).status_code == 401


def test_other_user_cannot_access(client: TestClient, admin_token: str) -> None:
    """数据隔离：非属主访问对话应 404（不泄露存在性）。"""
    conv = _create_conv(client, admin_token)
    # 创建真实存在的第二个用户，用其 token 访问 admin 的对话
    from auth.jwt import create_access_token, hash_password
    from models import User
    from models.base import SessionLocal

    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        u2 = User(
            username=f"conv_other_{conv['id']}",
            display_name="越权测试用户",
            role_id=admin.role_id,
            password_hash=hash_password("x"),
        )
        db.add(u2)
        db.commit()
        other_token = create_access_token(u2.id, u2.username, u2.role_id)
    finally:
        db.close()

    resp = client.get(f"/conversations/{conv['id']}", headers=_headers(other_token))
    assert resp.status_code == 404
    resp = client.post(
        f"/conversations/{conv['id']}/messages",
        json={"content": "越权提问"},
        headers=_headers(other_token),
    )
    assert resp.status_code == 404
