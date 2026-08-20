"""SQL 执行接口：在前端维护 MySQL 本体表结构库（ontology / ontology_meta 等）。

支持选择数据库（白名单：非系统库），仅连 MySQL（与业务 PG 库隔离），支持：
- SELECT / SHOW / DESC / DESCRIBE → 返回结果集（columns + rows）
- DDL（CREATE/ALTER/DROP/COMMENT）与 DML → 返回成功 + 影响行数

安全约束：数据库白名单校验、禁用 USE 切换、拒绝多语句。
"""

from __future__ import annotations

import re

import pymysql
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth.jwt import get_current_user
from config.settings import settings
from models import User
from tools.ontology_client import DbOntologyClient

router = APIRouter(prefix="/sql", tags=["sql"])

# 系统库：不展示、不允许选择/执行
_SYSTEM_DATABASES = {
    "information_schema",
    "mysql",
    "performance_schema",
    "sys",
}


class SqlRequest(BaseModel):
    sql: str
    database: str | None = None  # 目标库（默认 ontology）


def _list_databases_uncached() -> list[dict]:
    """列出 MySQL 所有非系统库。"""
    conn = pymysql.connect(
        host=settings.mysql.host,
        port=settings.mysql.port,
        user=settings.mysql.user,
        password=settings.mysql.password,
        charset="utf8mb4",
    )
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA ORDER BY SCHEMA_NAME"
        )
        return [
            {"name": n, "comment": ""}
            for (n,) in cur.fetchall()
            if n.lower() not in _SYSTEM_DATABASES
        ]
    finally:
        conn.close()


@router.get("/databases")
def list_databases(user: User = Depends(get_current_user)) -> list[dict]:
    """返回可查询的数据库列表（供数据查询页选择）。"""
    return _list_databases_uncached()


@router.get("/tables")
def list_tables(user: User = Depends(get_current_user)) -> list[dict]:
    """返回 MySQL ontology 库的本体表列表（表名 + 表注释），供表权限下拉选择。"""
    tables = DbOntologyClient()._load_tables()
    return [
        {"table_name": t["table_name"], "table_comment": t["table_comment"]}
        for t in tables
    ]


@router.get("/columns")
def list_columns(table: str, user: User = Depends(get_current_user)) -> list[dict]:
    """返回指定表的字段列表（字段名 + 中文注释），供关联字段下拉选择。"""
    tables = DbOntologyClient()._load_tables()
    for t in tables:
        if t["table_name"] == table.strip().upper():
            return [
                {"field": c["name"], "comment": c["comment"] or ""}
                for c in t["columns"]
            ]
    return []


def _reject_unsafe(sql: str) -> None:
    """安全约束：禁止 USE 切换库、禁止多语句。"""
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        raise HTTPException(status_code=400, detail="SQL 不能为空")
    if re.match(r"^\s*use\s+", sql, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="禁止切换数据库")
    # 多语句检测：非字符串字面量里的分号
    if stripped.count(";") > 0:
        raise HTTPException(status_code=400, detail="一次只能执行一条 SQL")


@router.post("/execute")
def execute_sql(
    payload: SqlRequest,
    user: User = Depends(get_current_user),
) -> dict:
    """执行 SQL（目标库白名单校验后执行）。"""
    _reject_unsafe(payload.sql)
    sql = payload.sql.strip().rstrip(";")

    database = (payload.database or settings.mysql.database).strip()
    available = {d["name"] for d in _list_databases_uncached()}
    if database not in available:
        raise HTTPException(
            status_code=400,
            detail=f"数据库 {database} 不在可查询列表中",
        )

    conn = pymysql.connect(
        host=settings.mysql.host,
        port=settings.mysql.port,
        user=settings.mysql.user,
        password=settings.mysql.password,
        database=database,
        charset="utf8mb4",
    )
    try:
        cur = conn.cursor()
        cur.execute(sql)
        if cur.description is not None:
            # 结果集查询
            columns = [d[0] for d in cur.description]
            rows = [list(r) for r in cur.fetchall()]
            return {"type": "result", "columns": columns, "rows": rows, "row_count": len(rows)}
        # DDL / DML
        conn.commit()
        return {"type": "ok", "affected": cur.rowcount, "message": "执行成功"}
    except pymysql.MySQLError as e:
        raise HTTPException(status_code=400, detail=f"SQL 执行失败：{e}")
    finally:
        cur.close()
        conn.close()
