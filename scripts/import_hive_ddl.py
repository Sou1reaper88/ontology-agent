"""Hive DDL → PostgreSQL `ontology` schema 建表工具。

用法：
    python scripts/import_hive_ddl.py <ddl文件.sql>

把 Hive 风格的建表语句（字段内联 `COMMENT '描述'`）转换成 PostgreSQL 建表，
建到 `ontology` schema，字段注释自动转为 `COMMENT ON COLUMN`。

支持字段类型自动映射：STRING→TEXT、VARCHAR(n)→VARCHAR(n)、INT→INTEGER、
BIGINT→BIGINT、DECIMAL(p,s)→NUMERIC(p,s)、DOUBLE→DOUBLE PRECISION、DATE→DATE。
"""

from __future__ import annotations

import os
import re
import sys

# 让脚本从项目根目录运行也能 import 项目模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from models.base import engine

_SCHEMA = "ontology"

_TYPE_MAP = {
    "STRING": "TEXT",
    "INT": "INTEGER",
    "INTEGER": "INTEGER",
    "BIGINT": "BIGINT",
    "DOUBLE": "DOUBLE PRECISION",
    "DATE": "DATE",
}


def _map_type(hive_type: str) -> str:
    t = hive_type.strip().upper()
    if t.startswith("VARCHAR"):
        return t.replace("VARCHAR", "VARCHAR")  # PG 支持 varchar(n)
    if t.startswith("DECIMAL") or t.startswith("NUMERIC"):
        return t.replace("DECIMAL", "NUMERIC")
    return _TYPE_MAP.get(t.split("(")[0], "TEXT")


def parse_hive_ddl(ddl: str) -> tuple[str, list[tuple[str, str, str]]]:
    """解析 Hive DDL，返回 (表名, [(字段名, 类型, 注释), ...])。"""
    m = re.search(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        ddl,
        re.IGNORECASE,
    )
    if not m:
        raise ValueError("未找到 CREATE TABLE 语句")
    table = m.group(1).lower()

    # 截取括号内的字段定义段（到 CREATE TABLE 结束的 ");" 为止，
    # 不能用括号计数——字段类型 VARCHAR(255) 自身含括号）
    start = m.end()
    end_marker = ddl.find(");", start)
    body = ddl[start:end_marker] if end_marker != -1 else ddl[start:]

    # 按字段行解析：字段名 类型 [COMMENT '描述']
    fields: list[tuple[str, str, str]] = []
    for line in body.split("\n"):
        fm = re.match(
            r"\s*([A-Za-z_][A-Za-z0-9_]*)\s+([A-Za-z0-9_(),]+)"
            r"(?:\s+COMMENT\s+'([^']*)')?\s*,?\s*$",
            line,
            re.IGNORECASE,
        )
        if fm:
            fields.append((fm.group(1).lower(), _map_type(fm.group(2)), fm.group(3) or ""))
    if not fields:
        raise ValueError("未解析到任何字段")
    return table, fields


def build_pg_ddl(table: str, fields: list[tuple[str, str, str]]) -> list[str]:
    """生成 PG 建表语句列表（CREATE TABLE + 若干 COMMENT ON COLUMN）。"""
    col_defs = ",\n    ".join(f"{name} {typ}" for name, typ, _ in fields)
    statements = [
        f"DROP TABLE IF EXISTS {_SCHEMA}.{table};",
        f"CREATE TABLE {_SCHEMA}.{table} (\n    {col_defs}\n);",
    ]
    for name, _typ, comment in fields:
        if comment:
            escaped = comment.replace("'", "''")
            statements.append(
                f"COMMENT ON COLUMN {_SCHEMA}.{table}.{name} IS '{escaped}';"
            )
    return statements


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as f:
        ddl = f.read()
    table, fields = parse_hive_ddl(ddl)
    statements = build_pg_ddl(table, fields)
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
    print(f"已建表 ontology.{table}（{len(fields)} 个字段，{sum(1 for s in statements if s.startswith('COMMENT'))} 个字段注释）")


if __name__ == "__main__":
    main()
