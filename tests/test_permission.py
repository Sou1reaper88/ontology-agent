"""表级权限校验测试（阶段 3）。"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from auth.permission import extract_table_names, require_table_permissions
from models import Role, TablePermission, User
from models.base import SessionLocal


def test_extract_table_names() -> None:
    """提取 SQL 中的物理表名（FROM/JOIN、schema 前缀、临时表）。"""
    sql = (
        "SELECT a.x FROM bddwd_hive_db.D_BBZX_DW_PRODUCT_M a "
        "JOIN temp_01 t ON a.x = t.x"
    )
    assert extract_table_names(sql) == ["D_BBZX_DW_PRODUCT_M", "temp_01"]


def test_require_table_permissions_denied() -> None:
    """角色无表权限 → 抛 403。"""
    db = SessionLocal()
    try:
        role = Role(name="测试无权限角色_deny", description="")
        db.add(role)
        db.flush()
        user = User(
            username="noperm_test", display_name="无权限", role_id=role.id
        )
        db.add(user)
        db.flush()
        sql = "SELECT 1 FROM bddwd_hive_db.D_BBZX_DW_PRODUCT_M WHERE 1=1;"
        with pytest.raises(HTTPException) as exc:
            require_table_permissions(user, sql, db)
        assert exc.value.status_code == 403
        assert "D_BBZX_DW_PRODUCT_M" in exc.value.detail
        db.rollback()
    finally:
        db.close()


def test_require_table_permissions_ok() -> None:
    """角色有表权限 → 不抛异常。"""
    db = SessionLocal()
    try:
        role = Role(name="测试有权限角色_ok", description="")
        db.add(role)
        db.flush()
        db.add(
            TablePermission(
                role_id=role.id,
                table_name="D_BBZX_DW_PRODUCT_M",
                can_query=True,
            )
        )
        user = User(
            username="perm_ok_test", display_name="有权限", role_id=role.id
        )
        db.add(user)
        db.flush()
        sql = "SELECT 1 FROM bddwd_hive_db.D_BBZX_DW_PRODUCT_M WHERE 1=1;"
        assert require_table_permissions(user, sql, db) is None
        db.rollback()
    finally:
        db.close()


def test_require_table_permissions_temp_skipped() -> None:
    """temp_ 临时表不参与权限校验。"""
    db = SessionLocal()
    try:
        role = Role(name="测试临时表角色_skip", description="")
        db.add(role)
        db.flush()
        user = User(
            username="temp_skip_test", display_name="临时表", role_id=role.id
        )
        db.add(user)
        db.flush()
        sql = "SELECT 1 FROM temp_01 WHERE 1=1;"
        assert require_table_permissions(user, sql, db) is None
        db.rollback()
    finally:
        db.close()
