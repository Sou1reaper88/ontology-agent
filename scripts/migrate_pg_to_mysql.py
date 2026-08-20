"""把 PG ontology schema 的表结构迁移到本地 MySQL ontology 库（一次性脚本）。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql

from tools.ontology_client import DbOntologyClient

MYSQL_HOST = "127.0.0.1"
MYSQL_USER = "root"
MYSQL_PASSWORD = "root"
MYSQL_DB = "ontology"

_TYPE_MAP = {
    "text": "TEXT",
    "integer": "INT",
    "bigint": "BIGINT",
    "varchar": "VARCHAR(255)",
    "character varying": "VARCHAR(255)",
}


def esc(s: str) -> str:
    return (s or "").replace("'", "''")


def main() -> None:
    tables = DbOntologyClient()._load_tables()
    print("PG 现有表:", [t["table_name"] for t in tables])

    conn = pymysql.connect(host=MYSQL_HOST, user=MYSQL_USER, password=MYSQL_PASSWORD, charset="utf8mb4")
    cur = conn.cursor()
    cur.execute(f"CREATE DATABASE IF NOT EXISTS {MYSQL_DB} CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci")
    cur.execute(f"USE {MYSQL_DB}")

    for t in tables:
        tname = t["table_name"].lower()
        col_defs = []
        for c in t["columns"]:
            typ = _TYPE_MAP.get(c["type"].lower(), "VARCHAR(255)")
            col_defs.append(
                f"`{c['name'].lower()}` {typ} COMMENT '{esc(c['comment'])}'"
            )
        sql = (
            f"CREATE TABLE IF NOT EXISTS `{tname}` "
            f"({', '.join(col_defs)}) COMMENT='{esc(t['table_comment'])}'"
        )
        cur.execute(sql)
        print(f"迁移表: {tname} ({len(col_defs)} 字段)")
    conn.commit()
    cur.close()
    conn.close()
    print("迁移完成")


if __name__ == "__main__":
    main()
