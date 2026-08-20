"""一次性导入：D_BBZX_GB_SCYHFX0535_RESULT_D 字段描述灌入 ontology_field_meta。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql

from config.settings import settings

DATA = """对象英文名称	对象中文名称	对象描述	状态	属性英文名	属性中文名	属性类型	属性描述	是否主键	是否标题
D_BBZX_GB_SCYHFX0535_RESULT_D	FTTR服务包模式程序表		启用	OP_TIME	日期	string	记录用户订购服务的时间。		是
D_BBZX_GB_SCYHFX0535_RESULT_D				USER_ID	用户ID	string	记录了用户ID		
D_BBZX_GB_SCYHFX0535_RESULT_D				kd_product_no	宽带账号	string	记录用户的宽带账号。		
D_BBZX_GB_SCYHFX0535_RESULT_D				create_date_kdjg	宽带竣工时间	string	记录用户宽带竣工的时间。		
D_BBZX_GB_SCYHFX0535_RESULT_D				city_id	地市ID	string	记录用户地市ID		
D_BBZX_GB_SCYHFX0535_RESULT_D				city_name	地市	string	描述用户所在的地市的名称。		
D_BBZX_GB_SCYHFX0535_RESULT_D				county_id	区县ID	string	记录用户区县ID		
D_BBZX_GB_SCYHFX0535_RESULT_D				COUNTY_NAME	区县	string	描述用户所在的区县的名称。		
D_BBZX_GB_SCYHFX0535_RESULT_D				create_date_dg	策划订购时间	string	记录用户订购服务的时间。		
D_BBZX_GB_SCYHFX0535_RESULT_D				effective_date	策划生效时间	string	记录用户策划生效时间		
D_BBZX_GB_SCYHFX0535_RESULT_D				EXPIRE_DATE	策划失效时间	string	记录用户订购服务的失效时间。		
D_BBZX_GB_SCYHFX0535_RESULT_D				create_date_td	策划退订时间	string	记录用户策划退订时间		
D_BBZX_GB_SCYHFX0535_RESULT_D				offer_id	策划ID	string	记录用户的策划ID。		
D_BBZX_GB_SCYHFX0535_RESULT_D				offer_name	策划名称	string	描述用户的策划名称。		
D_BBZX_GB_SCYHFX0535_RESULT_D				BANDWIDTH	宽带速率	string	记录用户的宽带速率。		
D_BBZX_GB_SCYHFX0535_RESULT_D				KDZT_NAME	宽带状态	string	记录用户宽带状态		
D_BBZX_GB_SCYHFX0535_RESULT_D				is_cphy	是否产品合约（省公司）	string	标识用户是否选择了产品合约服务。		
D_BBZX_GB_SCYHFX0535_RESULT_D				is_cphy_ds	是否产品合约（地市）	string	记录用户是否产品合约（地市）		
D_BBZX_GB_SCYHFX0535_RESULT_D				is_qhy	是否轻合约	string	标识用户是否选择了轻合约服务。		
D_BBZX_GB_SCYHFX0535_RESULT_D				is_hx	是否惠享	string	标识用户是否选择了惠享服务。		
D_BBZX_GB_SCYHFX0535_RESULT_D				is_qjx	是否全家享	string	标识用户是否选择了全家享服务。		
D_BBZX_GB_SCYHFX0535_RESULT_D				is_chlx	是否CH拉新合约	string	记录用户是否CH拉新合约		
D_BBZX_GB_SCYHFX0535_RESULT_D				is_fyf	是否普通分月付	string	标识用户是否选择了普通分月付的服务方式。		
D_BBZX_GB_SCYHFX0535_RESULT_D				is_chhf	是否CH话费合约	string	记录用户是否CH话费合约		
D_BBZX_GB_SCYHFX0535_RESULT_D				is_clsd	是否办理存量升档优惠	string	记录用户是否办理存量升档优惠		
D_BBZX_GB_SCYHFX0535_RESULT_D				is_jtslrw_zc	是否集团三类人物政策	string	记录用户是否集团三类人物政策		
D_BBZX_GB_SCYHFX0535_RESULT_D				is_jttg_zc	是否集团团购政策	string	记录用户是否集团团购政策		
D_BBZX_GB_SCYHFX0535_RESULT_D				CHANNEL_NAME	受理渠道名称	string	描述用户订购服务的受理渠道名称。		
D_BBZX_GB_SCYHFX0535_RESULT_D				org_id	受理渠道编号	string	记录用户订购服务的受理渠道编号。		
D_BBZX_GB_SCYHFX0535_RESULT_D				channel_type	渠道类型	string	描述用户订购服务的渠道类型。		
D_BBZX_GB_SCYHFX0535_RESULT_D				gmlx	光猫类型	string	描述用户的光猫类型。		
D_BBZX_GB_SCYHFX0535_RESULT_D				is_dsgjz	是否低速率高价值客群	string	标识用户是否为低速率高价值客群。		
D_BBZX_GB_SCYHFX0535_RESULT_D				is_zc	是否质差客群	string	标识用户是否为质差客群。		
D_BBZX_GB_SCYHFX0535_RESULT_D				is_jtslrw	是否集团三类人物客群	string	表示客户群体是否属于集团的三类人物客群，用于区分和分类不同的客户群体。		
D_BBZX_GB_SCYHFX0535_RESULT_D				is_qzxq	是否千兆小区场景	string	标识用户所在的千兆小区场景。		
D_BBZX_GB_SCYHFX0535_RESULT_D				is_yjsp	是否沿街商铺场景	string	标识用户所在的沿街商铺场景。		
D_BBZX_GB_SCYHFX0535_RESULT_D				is_kdlx	是否拉新宽带	string	标识用户是否需要拉新宽带服务。		
D_BBZX_GB_SCYHFX0535_RESULT_D				KD_USER_ID	宽带user_id	string	记录了宽带user_id 		
D_BBZX_GB_SCYHFX0535_RESULT_D				HZ_BILL_ID	户主手机号码	string	记录了户主手机号码		
D_BBZX_GB_SCYHFX0535_RESULT_D				USERSTATUS_ID	户主手机号码状态	string	记录了户主手机号码状态		
D_BBZX_GB_SCYHFX0535_RESULT_D				HZ_USER_ID	户主user_id	string	记录了户主user_id		
D_BBZX_GB_SCYHFX0535_RESULT_D				HZ_CREATE_DATE	户主开户时间	string	记录了户主开户时间		
D_BBZX_GB_SCYHFX0535_RESULT_D				FTTR_STATUS	FTTR状态	string	记录了FTTR状态		
D_BBZX_GB_SCYHFX0535_RESULT_D				IS_SD	是否办理升档合约	string	记录了是否办理升档合约		
D_BBZX_GB_SCYHFX0535_RESULT_D				ZHUGM_HY	主光猫30天内是否活跃	string	记录了主光猫30天内是否活跃		
D_BBZX_GB_SCYHFX0535_RESULT_D				ZIGM_HY	子光猫30天内是否活跃	string	记录了子光猫30天内是否活跃		
D_BBZX_GB_SCYHFX0535_RESULT_D				OFFER_NAME_TC	宽带套餐	string	记录了宽带套餐		
D_BBZX_GB_SCYHFX0535_RESULT_D				PLAN_NAME_TC	宽带成员	string	记录了宽带成员		
D_BBZX_GB_SCYHFX0535_RESULT_D				ARPU_0	订购FTTR当月折后收入	string	记录了订购FTTR当月折后收入		
D_BBZX_GB_SCYHFX0535_RESULT_D				ARPU_1	订购FTTR次月折后收入	string	记录了订购FTTR次月折后收入		
D_BBZX_GB_SCYHFX0535_RESULT_D				ARPU_2	订购FTTR次次月折后收入	string	记录了订购FTTR次次月折后收入		
D_BBZX_GB_SCYHFX0535_RESULT_D				ARPU_3	订购FTTR次次次月折后收入	string	记录了订购FTTR次次次月折后收入		
D_BBZX_GB_SCYHFX0535_RESULT_D				ARPU_AVG	订购FTTR前平均折后收入	string	记录了订购FTTR前平均折后收入		
D_BBZX_GB_SCYHFX0535_RESULT_D				IS_YHG	是否优惠购	string	记录了是否优惠购		
D_BBZX_GB_SCYHFX0535_RESULT_D				IS_GKLX	是否高客拉新合约	string	记录了是否高客拉新合约		
D_BBZX_GB_SCYHFX0535_RESULT_D				IS_CLYH	是否存量赢回合约	string	记录了是否存量赢回合约		
D_BBZX_GB_SCYHFX0535_RESULT_D				IS_CLYH_YHG	是否存量迎回优惠购	string	记录了是否存量迎回优惠购		
D_BBZX_GB_SCYHFX0535_RESULT_D				IS_ZJFW	是否智家服务合约	string	记录了是否智家服务合约		
D_BBZX_GB_SCYHFX0535_RESULT_D				P_DAY	时间分区	string			
D_BBZX_GB_SCYHFX0535_RESULT_D				P_CITY	地市分区	string"""


def main() -> None:
    rows: list[tuple[str, str, str]] = []
    for line in DATA.strip().split("\n"):
        cols = line.split("\t")
        if len(cols) < 8:
            continue
        table_name = cols[0].strip().lower()
        if table_name == "对象英文名称":
            continue  # 跳过表头行
        field_name = cols[4].strip().lower()
        field_desc = cols[7].strip()
        if not table_name or not field_name or not field_desc:
            continue  # 跳过空描述行（P_DAY/P_CITY）
        rows.append((table_name, field_name, field_desc))

    conn = pymysql.connect(
        host=settings.mysql.host,
        port=settings.mysql.port,
        user=settings.mysql.user,
        password=settings.mysql.password,
        database=settings.mysql.database,
        charset="utf8mb4",
    )
    try:
        cur = conn.cursor()
        tables = {r[0] for r in rows}
        for t in tables:
            cur.execute("DELETE FROM ontology_field_meta WHERE table_name=%s", (t,))
        cur.executemany(
            "INSERT INTO ontology_field_meta (table_name, field_name, field_desc, status) "
            "VALUES (%s, %s, %s, '启用')",
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    print(f"已灌入 {len(rows)} 条字段描述（表 {sorted(set(r[0] for r in rows))}）")


if __name__ == "__main__":
    main()
