# -*- coding: utf-8 -*-
"""把「来信免打扰订购用户」逻辑定义改为自然语言业务口径版。

用户反馈：占位符应让 LLM 做语义理解，而非用户手写、系统替换。
定义用自然语言表达业务口径（账期语义由 LLM 结合需求解析），
保留可选的 {B:}/{C:} 场景标记由系统按需求场景筛选。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql

from config.settings import settings

DESC = (
    "已订购来信免打扰服务（策划编号610000149732）的用户：实时表 D_CRM_INS_OFFER_D 与历史表 "
    "D_CRM_INS_OFFER_H_D 按账期生失效日期联合判断；未订购=账期内不存在有效订购记录。"
)
COND = (
    "在账期开始至账期结束期间未订购策划编号610000149732的来信免打扰服务。"
    "查询 D_CRM_INS_OFFER_D 与 D_CRM_INS_OFFER_H_D 两张表，均使用最近一天分区（p_day 取最近分区快照）。"
    "有效订购记录判断：生效日期 effective_date 不晚于账期结束日 23:59:59，"
    "且失效日期 expire_date 晚于账期开始日 00:00:00（expire_date 为空视为持续有效）。"
    "历史表与实时表按 offer_inst_id 去重（历史表保留实时表不存在的记录）。"
)

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
    cur.execute(
        "UPDATE ontology_logical_defs SET def_desc=%s, def_condition=%s WHERE def_name=%s",
        (DESC, COND, "来信免打扰订购用户"),
    )
    conn.commit()
    cur.execute("SELECT def_name, def_condition FROM ontology_logical_defs")
    for r in cur.fetchall():
        print(r[0], "=>", (r[1] or "")[:80])
finally:
    conn.close()
