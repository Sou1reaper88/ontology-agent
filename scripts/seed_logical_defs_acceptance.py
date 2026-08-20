# -*- coding: utf-8 -*-
"""沉淀用户验收口径为逻辑定义（正常在网手机用户 + 来信免打扰订购用户）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql

from config.settings import settings

defs = [
    (
        "正常在网手机用户",
        "d_bbzx_dw_product_m",
        "浙江省正常在网手机用户：用户状态正常且产品分类为手机",
        "USERSTATUS_ID='1' AND PROD_CATALOG_ID='1'",
    ),
    (
        "来信免打扰订购用户",
        "d_crm_ins_offer_d",
        "已订购来信免打扰服务（策划编号610000149732）的用户：查 D_CRM_INS_OFFER_D 与 D_CRM_INS_OFFER_H_D 两表，p_day='20260630' 分区快照，有效订购条件 effective_date <= 账期月末 且 expire_date > 账期月初",
        "OFFER_ID='610000149732' AND P_DAY='20260630' AND EFFECTIVE_DATE<='2026-06-30 23:59:59' AND EXPIRE_DATE>'2026-06-01 00:00:00'",
    ),
]

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
    for name, table, desc, cond in defs:
        cur.execute(
            "INSERT INTO ontology_logical_defs (def_name, table_name, def_desc, def_condition) "
            "VALUES (%s, %s, %s, %s)",
            (name, table, desc, cond),
        )
    conn.commit()
    cur.execute("SELECT def_name FROM ontology_logical_defs")
    print("逻辑定义:", [r[0] for r in cur.fetchall()])
finally:
    conn.close()
