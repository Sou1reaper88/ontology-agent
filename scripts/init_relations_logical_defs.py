"""初始化本体关系定义表 + 逻辑定义表（MySQL ontology 库），并迁移示例数据。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql

from config.settings import settings


def main() -> None:
    conn = pymysql.connect(
        host=settings.mysql.host,
        port=settings.mysql.port,
        user=settings.mysql.user,
        password=settings.mysql.password,
        database=settings.mysql.database,
        charset="utf8mb4",
    )
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ontology_relations (
            id INT AUTO_INCREMENT PRIMARY KEY,
            source_table VARCHAR(255) COMMENT '源表',
            source_field VARCHAR(255) COMMENT '源关联字段',
            target_table VARCHAR(255) COMMENT '目标表',
            target_field VARCHAR(255) COMMENT '目标关联字段',
            relation_type VARCHAR(32) COMMENT '关系类型',
            relation_label VARCHAR(255) COMMENT '关系描述'
        ) COMMENT='本体关系定义（表间JOIN关联）'
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ontology_logical_defs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            def_name VARCHAR(128) COMMENT '口径名',
            table_name VARCHAR(255) COMMENT '适用表',
            def_desc TEXT COMMENT '口径描述',
            def_condition TEXT COMMENT '精确条件片段(可选)'
        ) COMMENT='本体逻辑定义（业务口径）'
        """
    )

    # 迁移示例：沉默用户口径
    cur.execute("SELECT COUNT(*) FROM ontology_logical_defs WHERE def_name=%s", ("沉默用户",))
    if cur.fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO ontology_logical_defs (def_name, table_name, def_desc, def_condition) "
            "VALUES (%s, %s, %s, %s)",
            (
                "沉默用户",
                "d_bbzx_dw_product_m",
                "当月无通话次数且无GPRS流量",
                "CALL_COUNTS=0 OR CALL_COUNTS IS NULL AND GPRS_VOLUME=0 OR GPRS_VOLUME IS NULL",
            ),
        )

    conn.commit()
    cur.close()
    conn.close()
    print("已建 ontology_relations + ontology_logical_defs 表，并迁移沉默用户口径示例")


if __name__ == "__main__":
    main()
