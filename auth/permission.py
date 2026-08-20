"""表级权限校验：解析 SQL 表名，查 table_permissions 校验角色（RBAC 表级）。

策略（设计文档 §5.2）：Agent 生成 SQL 后，提取涉及物理表名，
校验用户角色对全部表有 can_query 权限；任一表无权限 → 拒绝并记录。
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import TablePermission


def extract_table_names(sql: str) -> list[str]:
    """提取 SQL 中的物理表名（FROM/JOIN 后；忽略别名与库前缀）。"""
    tables: list[str] = []
    pattern = re.compile(
        r"(?:FROM|JOIN)\s+"
        r"(?:[A-Za-z_][A-Za-z0-9_]*\.)?"
        r"([A-Za-z_][A-Za-z0-9_]*)",
        re.IGNORECASE,
    )
    for m in pattern.finditer(sql):
        tables.append(m.group(1))
    return tables


def check_table_permissions(
    user: Any, sql: str, db: Session
) -> list[str]:
    """校验用户角色对 SQL 涉及表的 can_query 权限。

    返回被拒绝的表名列表（空 = 全部通过）。temp_ 前缀临时表视为内部逻辑表不校验。
    表名大小写不敏感（统一大写比较，Hive 表名约定大写）。
    """
    tables = extract_table_names(sql)
    if not tables:
        return []
    permitted = {
        tp.table_name.upper()
        for tp in db.query(TablePermission)
        .filter(
            TablePermission.role_id == user.role_id,
            TablePermission.can_query.is_(True),
        )
        .all()
    }
    return [
        t
        for t in tables
        if not t.upper().startswith("TEMP_") and t.upper() not in permitted
    ]


def require_table_permissions(user: Any, sql: str, db: Session) -> None:
    """权限不足时抛出 403（被拒表名写入 detail），并记录审计。"""
    denied = check_table_permissions(user, sql, db)
    if denied:
        from audit.utils import write_audit_log

        write_audit_log(
            user_id=getattr(user, "id", None),
            action="permission_denied",
            detail={"denied_tables": sorted(denied), "sql": sql},
            status="denied",
        )
        raise HTTPException(
            status_code=403,
            detail=f"无权访问的表: {sorted(denied)}",
        )
