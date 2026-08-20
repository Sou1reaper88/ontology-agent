"""字段元数据（描述）版本化测试：更新不覆盖，旧记录失效新记录生效。"""

from __future__ import annotations

import pymysql
from fastapi.testclient import TestClient

from config.settings import settings
from tools.ontology_client import DbOntologyClient

TEST_TABLE = "d_bbzx_dw_product_m"
TEST_FIELD = "test_field_meta_zzz"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _cleanup(field_name: str = TEST_FIELD) -> None:
    conn = pymysql.connect(
        host=settings.mysql.host,
        port=settings.mysql.port,
        user=settings.mysql.user,
        password=settings.mysql.password,
        database=settings.mysql.meta_database,
        charset="utf8mb4",
    )
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM ontology_field_meta WHERE table_name=%s AND field_name=%s",
            (TEST_TABLE, field_name),
        )
        conn.commit()
    finally:
        conn.close()


def test_field_meta_versioning(client: TestClient, admin_token: str) -> None:
    """版本化：两次保存后，旧记录失效、新记录生效，GET 只返回生效描述。"""
    _cleanup()
    try:
        # 第一次保存
        r1 = client.post(
            "/ontology/field-meta",
            json={"table_name": TEST_TABLE, "field_name": TEST_FIELD, "field_desc": "旧描述"},
            headers=_headers(admin_token),
        )
        assert r1.status_code == 201

        # 第二次保存（应失效旧的、生效新的）
        r2 = client.post(
            "/ontology/field-meta",
            json={"table_name": TEST_TABLE, "field_name": TEST_FIELD, "field_desc": "新描述"},
            headers=_headers(admin_token),
        )
        assert r2.status_code == 201

        # GET 只返回生效记录
        resp = client.get("/ontology/field-meta", params={"table": TEST_TABLE}, headers=_headers(admin_token))
        items = [r for r in resp.json() if r["field_name"] == TEST_FIELD.upper()]
        assert len(items) == 1, "应只有一条生效记录"
        assert items[0]["field_desc"] == "新描述"
    finally:
        _cleanup()


def test_retrieval_reads_active_field_meta(client: TestClient, admin_token: str) -> None:
    """检索器只读生效（status='启用'）的字段描述。"""
    _cleanup()
    try:
        client.post(
            "/ontology/field-meta",
            json={"table_name": TEST_TABLE, "field_name": TEST_FIELD, "field_desc": "生效描述"},
            headers=_headers(admin_token),
        )
        meta = DbOntologyClient()._load_field_meta()
        assert meta.get(TEST_TABLE.upper(), {}).get(TEST_FIELD.upper()) == "生效描述"
    finally:
        _cleanup()


def test_meta_table_excluded_from_objects() -> None:
    """字段元数据表不作为本体对象参与检索。"""
    c = DbOntologyClient()
    names = [t["table_name"] for t in c._load_tables()]
    assert "ONTOLOGY_FIELD_META" not in names
