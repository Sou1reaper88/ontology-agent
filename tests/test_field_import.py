"""字段描述批量导入功能测试：TSV 解析 + 版本化导入 + 表注释更新。"""

from __future__ import annotations

import pymysql
from fastapi.testclient import TestClient

from api.routes.ontology import _parse_tsv
from config.settings import settings
from tools.ontology_client import DbOntologyClient

TSV_SAMPLE = (
    "对象英文名称\t对象中文名称\t对象描述\t状态\t属性英文名\t属性中文名\t属性类型\t属性描述\t是否主键\t是否标题\n"
    "D_BBZX_GB_SCYHFX0535_RESULT_D\tFTTR服务包模式程序表\t\t启用\tOP_TIME\t日期\tstring\t记录用户订购服务的时间。\t\t是\n"
    "D_BBZX_GB_SCYHFX0535_RESULT_D\t\t\t\tUSER_ID\t用户ID\tstring\t记录了用户ID\t\t\n"
    "D_BBZX_GB_SCYHFX0535_RESULT_D\t\t\t\tP_DAY\t时间分区\tstring\t\t\t\n"
)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_parse_tsv() -> None:
    """TSV 解析：提取表名/字段名/描述/中文表名，跳过表头与空描述。"""
    rows = _parse_tsv(TSV_SAMPLE)
    assert len(rows) == 2  # P_DAY 空描述被跳过
    assert rows[0]["table_name"] == "d_bbzx_gb_scyhfx0535_result_d"
    assert rows[0]["field_name"] == "op_time"
    assert rows[0]["field_desc"] == "记录用户订购服务的时间。"
    assert rows[0]["table_cn"] == "FTTR服务包模式程序表"


def test_import_endpoint(client: TestClient, admin_token: str) -> None:
    """导入接口：版本化导入字段描述 + 顺带更新表注释。"""
    resp = client.post(
        "/ontology/import-field-meta",
        data={"text": TSV_SAMPLE},
        headers=_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["imported"] == 2
    assert "d_bbzx_gb_scyhfx0535_result_d" in data["tables"]
    assert data["table_comments_updated"] == 1

    # 验证字段描述已生效
    meta = DbOntologyClient()._load_field_meta()
    assert meta["D_BBZX_GB_SCYHFX0535_RESULT_D"]["OP_TIME"] == "记录用户订购服务的时间。"

    # 验证表注释已更新
    conn = pymysql.connect(
        host=settings.mysql.host,
        port=settings.mysql.port,
        user=settings.mysql.user,
        password=settings.mysql.password,
        database=settings.mysql.database,
        charset="utf8mb4",
    )
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT TABLE_COMMENT FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=%s AND TABLE_NAME='d_bbzx_gb_scyhfx0535_result_d'",
            (settings.mysql.database,),
        )
        assert cur.fetchone()[0] == "FTTR服务包模式程序表"
    finally:
        conn.close()


def test_import_versioning(client: TestClient, admin_token: str) -> None:
    """重复导入走版本化：旧描述失效，新描述生效，生效记录数恒为 1。"""
    tsv_old = (
        "对象英文名称\t对象中文名称\t对象描述\t状态\t属性英文名\t属性中文名\t属性类型\t属性描述\t是否主键\t是否标题\n"
        "D_BBZX_GB_SCYHFX0535_RESULT_D\tFTTR服务包模式程序表\t\t启用\tOP_TIME\t日期\tstring\t旧描述\t\t是\n"
    )
    client.post("/ontology/import-field-meta", data={"text": tsv_old}, headers=_headers(admin_token))

    tsv_new = tsv_old.replace("旧描述", "新描述")
    client.post("/ontology/import-field-meta", data={"text": tsv_new}, headers=_headers(admin_token))

    resp = client.get(
        "/ontology/field-meta",
        params={"table": "d_bbzx_gb_scyhfx0535_result_d"},
        headers=_headers(admin_token),
    )
    items = [r for r in resp.json() if r["field_name"] == "OP_TIME"]
    assert len(items) == 1, "应只有一条生效记录"
    assert items[0]["field_desc"] == "新描述"
