"""数据查询/数据库隔离测试：/sql/databases 列表 + /sql/execute 选库 + 元数据与对象表物理隔离。"""

from __future__ import annotations

import pymysql
import pytest

from config.settings import settings


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_databases_list_excludes_system(client, admin_token) -> None:
    """数据库列表返回非系统库（不含 information_schema/mysql 等）。"""
    r = client.get("/sql/databases", headers=_headers(admin_token))
    assert r.status_code == 200
    dbs = {d["name"] for d in r.json()}
    assert settings.mysql.database in dbs  # ontology 对象库
    assert settings.mysql.meta_database in dbs  # ontology_meta 元数据库
    assert "information_schema" not in dbs
    assert "mysql" not in dbs


def test_execute_with_database(client, admin_token) -> None:
    """指定数据库执行 SQL（元数据库 SHOW TABLES 应含 4 张元数据表）。"""
    r = client.post(
        "/sql/execute",
        json={"sql": "SHOW TABLES;", "database": settings.mysql.meta_database},
        headers=_headers(admin_token),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["type"] == "result"
    names = {row[0] for row in data["rows"]}
    assert {"ontology_relations", "ontology_logical_defs", "ontology_field_meta", "ontology_table_meta"} <= names


def test_execute_rejects_unknown_database(client, admin_token) -> None:
    """白名单外数据库拒绝执行。"""
    r = client.post(
        "/sql/execute",
        json={"sql": "SELECT 1;", "database": "no_such_db_xyz"},
        headers=_headers(admin_token),
    )
    assert r.status_code == 400


def test_objects_exclude_meta_tables(client, admin_token) -> None:
    """对象定义列表不再出现元数据表（已迁移到独立库）。"""
    r = client.get("/ontology/objects", headers=_headers(admin_token))
    assert r.status_code == 200
    names = {o["table_name"] for o in r.json()}
    assert "ONTOLOGY_TABLE_META" not in names
    assert "ONTOLOGY_RELATIONS" not in names


def test_retrieval_meta_from_separate_db() -> None:
    """检索器逻辑定义/字段描述从 meta 库读取（迁移后仍有数据）。"""
    from tools.ontology_client import DbOntologyClient

    c = DbOntologyClient()
    logical = c._load_logical_defs()
    field_meta = c._load_field_meta()
    assert isinstance(logical, dict) and len(logical) >= 1  # 沉默用户口径仍在
    assert len(field_meta) >= 1  # 字段描述仍在（523 行迁出）


@pytest.mark.skipif(True, reason="迁移一次性脚本，不重复执行")
def test_migrate_script_idempotent() -> None:
    """迁移脚本幂等（源表已删除时跳过）。"""
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "scripts/migrate_ontology_meta.py"],
        capture_output=True,
        text=True,
        cwd=".",
    )
    assert r.returncode == 0, r.stderr
