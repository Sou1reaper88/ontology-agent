# -*- coding: utf-8 -*-
"""把「来信免打扰订购用户」逻辑定义升级为模板版（占位符 + 场景开关，账期自适应）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql

from config.settings import settings

DESC = (
    "已订购来信免打扰服务（策划编号610000149732）的用户：查 D_CRM_INS_OFFER_D 与 D_CRM_INS_OFFER_H_D 两表，"
    "使用同一天分区快照 {月末分区}；场景B（时间段内全部/未订购排除）按生失效日期过滤，"
    "场景C（时间段内新增）按 create_date 过滤。占位符由系统按账期自动填充。"
)
COND = (
    "{OFFER_ID='610000149732' AND P_DAY='{月末分区}'}"
    "{B: AND EFFECTIVE_DATE<='{结束}' AND EXPIRE_DATE>'{开始}'}"
    "{C: AND CREATE_DATE>='{开始}' AND CREATE_DATE<='{结束}'}"
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
        print(r[0], "=>", (r[1] or "")[:90])
finally:
    conn.close()
