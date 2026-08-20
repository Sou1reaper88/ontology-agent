"""本体元数据表迁移：从 ontology 库迁移到 ontology_meta 库（对象表与状态表物理隔离）。

背景：SQL 窗口/数据查询与本体检索需要隔离——ontology 库只保留对象定义（业务）表，
本体元数据表（关系定义/逻辑定义/字段描述/表描述）统一放 ontology_meta 库，
避免检索器/查询把状态表当作对象。

安全：行数校验一致后才 DROP 源表；幂等（重复执行跳过已迁移表）。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql

from config.settings import settings

META_TABLES = [
    "ontology_relations",
    "ontology_logical_defs",
    "ontology_field_meta",
    "ontology_table_meta",
]


def main() -> None:
    src = settings.mysql.database
    dst = settings.mysql.meta_database
    conn = pymysql.connect(
        host=settings.mysql.host,
        port=settings.mysql.port,
        user=settings.mysql.user,
        password=settings.mysql.password,
        charset="utf8mb4",
    )
    try:
        cur = conn.cursor()
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{dst}` DEFAULT CHARACTER SET utf8mb4")
        for t in META_TABLES:
            cur.execute(f"SHOW TABLES IN `{src}` LIKE '{t}'")
            if not cur.fetchone():
                print(f"跳过（源表不存在）: {src}.{t}")
                continue
            cur.execute(f"CREATE TABLE IF NOT EXISTS `{dst}`.`{t}` LIKE `{src}`.`{t}`")
            cur.execute(f"INSERT IGNORE INTO `{dst}`.`{t}` SELECT * FROM `{src}`.`{t}`")
            cur.execute(f"SELECT COUNT(*) FROM `{src}`.`{t}`")
            src_n = cur.fetchone()[0]
            cur.execute(f"SELECT COUNT(*) FROM `{dst}`.`{t}`")
            dst_n = cur.fetchone()[0]
            print(f"{t}: 源 {src_n} 行 -> 目标 {dst_n} 行")
            if src_n != dst_n:
                raise SystemExit(f"{t} 迁移数量不一致，中止（不执行 DROP）")
        # 全部校验通过后才删除源表
        for t in META_TABLES:
            cur.execute(f"SHOW TABLES IN `{src}` LIKE '{t}'")
            if cur.fetchone():
                cur.execute(f"DROP TABLE `{src}`.`{t}`")
                print(f"已删除源表: {src}.{t}")
        conn.commit()
        print("迁移完成")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
