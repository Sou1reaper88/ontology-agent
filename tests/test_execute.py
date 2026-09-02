"""执行接口测试（阶段 4 + 对话移植）：直传 SQL 执行 / 对话建记录 → 执行 → 状态 → 结果。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

_MOCK_SQL = (
    "SELECT SUBS_NUMBER, CITY_ID, P_MON "
    "FROM bddwd_hive_db.D_BBZX_DW_PRODUCT_M "
    "WHERE P_MON='202607' "
    "AND (CALL_COUNTS=0 OR CALL_COUNTS IS NULL) "
    "AND (GPRS_VOLUME=0 OR GPRS_VOLUME IS NULL);"
)


def _do_execute_sql(client: TestClient, token: str, sql: str = _MOCK_SQL) -> int:
    """直传 SQL 执行（对话内编辑后执行路径），返回 query_id。"""
    resp = client.post(
        "/execute",
        json={"sql": sql},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["query_id"] is not None
    assert data["status"] == "success"
    return data["query_id"]


def _create_pending_via_conversation(client: TestClient, token: str, monkeypatch) -> int:
    """通过对话接口创建一条未执行的取数记录，返回 query_id。"""
    import api.routes.conversation as conv_route
    from tests.conftest import last_assistant_message, send_and_wait

    monkeypatch.setattr(
        conv_route,
        "run_agent",
        lambda query, **kwargs: {
            "success": True,
            "sql": _MOCK_SQL,
            "markdown": "已生成只读查询。",
            "trace": [],
        },
    )

    resp = client.post("/conversations", json={}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 201, resp.text
    cid = resp.json()["id"]
    send_and_wait(client, token, cid, "查询6月沉默用户", system_time="2026-08-14")
    asst = last_assistant_message(client, token, cid)
    assert asst["query_id"] is not None
    return asst["query_id"]


def test_execute_flow_direct_sql(client: TestClient, admin_token: str) -> None:
    """端到端：直传 SQL 执行 → 状态 → 拉取结果。"""
    qid = _do_execute_sql(client, admin_token)

    resp = client.get(
        f"/execute/{qid}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert resp.json()["row_count"] == 3

    resp = client.get(
        f"/execute/result/{qid}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["row_count"] == 3
    assert "SUBS_NUMBER" in data["columns"]
    assert len(data["rows"]) == 3


def test_execute_requires_auth(client: TestClient) -> None:
    """未认证提交执行 → 401。"""
    resp = client.post("/execute", json={"query_id": 1})
    assert resp.status_code == 401


def test_execute_unknown_record(client: TestClient, admin_token: str) -> None:
    """不存在的记录 → 404（归属校验）。"""
    resp = client.post(
        "/execute",
        json={"query_id": 999999},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404


def test_execute_requires_query_id_or_sql(client: TestClient, admin_token: str) -> None:
    """既无 query_id 也无 sql → 400。"""
    resp = client.post(
        "/execute",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 400


def test_execute_rejects_program_id_even_with_read_only_sql(
    client: TestClient,
    admin_token: str,
) -> None:
    resp = client.post(
        "/execute",
        json={"program_id": "a1b2c3d4e5f6", "sql": "SELECT 1;"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert resp.status_code == 400
    assert "仅生成" in resp.json()["detail"]


@pytest.mark.parametrize(
    "sql",
    (
        "SELECT 1; SELECT 2;",
        "DROP TABLE dm.customer;",
        "INSERT INTO dm.customer SELECT 1;",
        "CREATE TABLE dm.result AS SELECT 1;",
    ),
)
def test_execute_rejects_program_or_mutating_sql(
    client: TestClient,
    admin_token: str,
    sql: str,
) -> None:
    resp = client.post(
        "/execute",
        json={"sql": sql},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert resp.status_code == 400
    assert "单条只读查询" in resp.json()["detail"]


def test_result_before_execute(client: TestClient, admin_token: str, monkeypatch) -> None:
    """未执行的记录拉取结果 → 400（对话创建记录默认不执行）。"""
    qid = _create_pending_via_conversation(client, admin_token, monkeypatch)
    resp = client.get(
        f"/execute/result/{qid}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 400
