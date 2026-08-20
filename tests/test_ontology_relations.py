"""本体关系定义 + 逻辑定义 CRUD 接口测试（MySQL ontology 库）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tools.ontology_client import DbOntologyClient


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_relations_crud(client: TestClient, admin_token: str) -> None:
    """关系定义：创建 → 列表 → 删除。"""
    resp = client.post(
        "/ontology/relations",
        json={
            "source_table": "d_bbzx_dw_product_m",
            "source_field": "user_id",
            "target_table": "d_bbzx_gb_scyhfx0535_result_d",
            "target_field": "user_id",
            "relation_type": "一对多",
            "relation_label": "测试关系",
        },
        headers=_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    rid = resp.json()["id"]

    resp = client.get("/ontology/relations", headers=_headers(admin_token))
    assert resp.status_code == 200
    assert any(r["id"] == rid for r in resp.json())

    assert client.delete(f"/ontology/relations/{rid}", headers=_headers(admin_token)).status_code == 204


def test_logical_defs_crud(client: TestClient, admin_token: str) -> None:
    """逻辑定义：创建 → 列表 → 删除。"""
    resp = client.post(
        "/ontology/logical-defs",
        json={
            "def_name": "测试口径",
            "table_name": "d_bbzx_dw_product_m",
            "def_desc": "测试口径描述",
            "def_condition": "CALL_COUNTS=0",
        },
        headers=_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    did = resp.json()["id"]

    resp = client.get("/ontology/logical-defs", headers=_headers(admin_token))
    assert resp.status_code == 200
    assert any(r["id"] == did for r in resp.json())

    assert client.delete(f"/ontology/logical-defs/{did}", headers=_headers(admin_token)).status_code == 204


def test_retrieval_returns_relations_and_defs() -> None:
    """检索器组装 ttl_def 含关系定义与逻辑定义字段。"""
    c = DbOntologyClient()
    ttl = c.get_ontology_definition("查询沉默用户")
    assert "relations" in ttl and isinstance(ttl["relations"], list)
    assert isinstance(ttl["logical_definitions"], dict)
    assert "沉默用户" in ttl["logical_definitions"]  # 迁移的示例口径


def test_meta_tables_excluded_from_objects() -> None:
    """元数据表（关系/逻辑定义）不作为本体对象参与检索。"""
    c = DbOntologyClient()
    names = [t["table_name"] for t in c._load_tables()]
    assert "ONTOLOGY_RELATIONS" not in names
    assert "ONTOLOGY_LOGICAL_DEFS" not in names
