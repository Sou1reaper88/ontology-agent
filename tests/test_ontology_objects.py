"""对象定义（表定义）接口测试：列表 + 表注释/字段中文名维护（ALTER 物理表注释）。"""

from __future__ import annotations

import pymysql
import pytest

from config.settings import settings

TEST_TABLE = "ZZ_TEST_OBJECT"

# 物理表存在性检查用（PATCH 后读 information_schema 验证注释已生效）
def _read_comment(table: str, column: str | None = None) -> str:
    conn = pymysql.connect(
        host=settings.mysql.host,
        port=settings.mysql.port,
        user=settings.mysql.user,
        password=settings.mysql.password,
        charset="utf8mb4",
    )
    try:
        cur = conn.cursor()
        if column:
            cur.execute(
                "SELECT COLUMN_COMMENT FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s",
                (settings.mysql.database, table.lower(), column.lower()),
            )
        else:
            cur.execute(
                "SELECT TABLE_COMMENT FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
                (settings.mysql.database, table.lower()),
            )
        row = cur.fetchone()
        return row[0] if row else ""
    finally:
        conn.close()


@pytest.fixture
def test_table():
    """建一张对象定义测试表，测完清理。"""
    conn = pymysql.connect(
        host=settings.mysql.host,
        port=settings.mysql.port,
        user=settings.mysql.user,
        password=settings.mysql.password,
        charset="utf8mb4",
    )
    cur = conn.cursor()
    cur.execute(f"DROP TABLE IF EXISTS {settings.mysql.database}.{TEST_TABLE.lower()}")
    cur.execute(
        f"CREATE TABLE {settings.mysql.database}.{TEST_TABLE.lower()} ("
        "subs_number VARCHAR(255) COMMENT '用户号码', "
        "call_counts INT COMMENT '通话次数', "
        "p_mon VARCHAR(255) COMMENT '账期(分区)'"
        ") COMMENT='对象测试表'"
    )
    conn.commit()
    yield TEST_TABLE
    cur.execute(f"DROP TABLE IF EXISTS {settings.mysql.database}.{TEST_TABLE.lower()}")
    conn.commit()
    cur.close()
    conn.close()


def test_list_objects_returns_structure(test_table, client, admin_token) -> None:
    """GET /ontology/objects：表+注释+字段（含分区标记），排除元数据表。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    r = client.get("/ontology/objects", headers=headers)
    assert r.status_code == 200
    objs = r.json()
    names = {o["table_name"] for o in objs}
    assert TEST_TABLE in names
    assert "ONTOLOGY_RELATIONS" not in names  # 元数据表排除
    obj = next(o for o in objs if o["table_name"] == TEST_TABLE)
    assert obj["table_comment"] == "对象测试表"
    cols = {c["name"]: c for c in obj["columns"]}
    assert cols["SUBS_NUMBER"]["comment"] == "用户号码"
    assert cols["P_MON"]["is_partition"] is True
    assert cols["CALL_COUNTS"]["is_partition"] is False


def test_update_object_comment(test_table, client, admin_token) -> None:
    """PATCH 表注释：ALTER 后 information_schema 生效。"""
    headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
    r = client.patch(
        f"/ontology/objects/{TEST_TABLE}",
        json={"table_comment": "沉默用户对象表"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["table_comment"] == "沉默用户对象表"
    assert _read_comment(TEST_TABLE) == "沉默用户对象表"


def test_update_column_comment(test_table, client, admin_token) -> None:
    """PATCH 字段中文名：MODIFY COLUMN 后生效，类型保留。"""
    headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
    r = client.patch(
        f"/ontology/objects/{TEST_TABLE}/columns/SUBS_NUMBER",
        json={"column_comment": "用户唯一号码"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["column_comment"] == "用户唯一号码"
    assert _read_comment(TEST_TABLE, "subs_number") == "用户唯一号码"


def test_update_rejects_bad_identifier(client, admin_token) -> None:
    """非法表名/字段名返回 400。"""
    headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
    r = client.patch(
        "/ontology/objects/BAD;DROP",
        json={"table_comment": "x"},
        headers=headers,
    )
    assert r.status_code == 400


def test_update_column_not_found(test_table, client, admin_token) -> None:
    """字段不存在返回 404。"""
    headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
    r = client.patch(
        f"/ontology/objects/{TEST_TABLE}/columns/NO_SUCH_FIELD",
        json={"column_comment": "x"},
        headers=headers,
    )
    assert r.status_code == 404


def test_update_object_desc_and_list(test_table, client, admin_token) -> None:
    """PATCH 表描述（独立于中文名）+ GET objects 返回 table_desc。"""
    headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
    r = client.patch(
        f"/ontology/objects/{TEST_TABLE}/desc",
        json={"table_desc": "记录用户每月通话与流量使用，用于沉默识别"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["table_desc"] == "记录用户每月通话与流量使用，用于沉默识别"

    r2 = client.get("/ontology/objects", headers=headers)
    obj = next(o for o in r2.json() if o["table_name"] == TEST_TABLE)
    assert obj["table_desc"] == "记录用户每月通话与流量使用，用于沉默识别"
    # 中文名与描述相互独立
    assert obj["table_comment"] == "对象测试表"


def test_update_object_desc_idempotent(test_table, client, admin_token) -> None:
    """重复保存表描述幂等（upsert 不产生重复行）。"""
    headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
    for _ in range(2):
        r = client.patch(
            f"/ontology/objects/{TEST_TABLE}/desc",
            json={"table_desc": "幂等测试描述"},
            headers=headers,
        )
        assert r.status_code == 200
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
            "SELECT COUNT(*) FROM ontology_table_meta WHERE table_name=%s",
            (TEST_TABLE.lower(),),
        )
        assert cur.fetchone()[0] == 1
    finally:
        conn.close()
