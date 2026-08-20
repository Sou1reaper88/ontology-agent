-- 验收基准：沉默且未订购来信免打扰用户清单（账期 202606）
-- 用户于 2026-08-18 提供，作为本体性能测试的结果一致性基准。
-- 本体生成的 SQL 不要求结构一致（可用 NOT EXISTS 等），但结果表数据必须一致。

DROP TABLE IF EXISTS temp_ab26bbd180664400ba72132ecd0c4fc0_01;
CREATE TABLE temp_ab26bbd180664400ba72132ecd0c4fc0_01 AS
SELECT
    a.USER_ID,
    a.PRODUCT_NO
FROM bddwd_hive_db.D_BBZX_DW_PRODUCT_M a
WHERE a.P_MON = '202606'
  AND a.USERSTATUS_ID = '1'
  AND a.PROD_CATALOG_ID = '1'
  AND (a.CALL_COUNTS = 0 OR a.CALL_COUNTS IS NULL)
  AND (a.GPRS_VOLUME = 0 OR a.GPRS_VOLUME IS NULL);

DROP TABLE IF EXISTS temp_ab26bbd180664400ba72132ecd0c4fc0_02;
CREATE TABLE temp_ab26bbd180664400ba72132ecd0c4fc0_02 AS
SELECT DISTINCT
    b.user_id
FROM bddwd_hive_db.D_CRM_INS_OFFER_D b
WHERE b.P_DAY = '20260630'
  AND b.offer_id = '610000149732'
  AND b.effective_date <= '2026-06-30 23:59:59'
  AND b.expire_date > '2026-06-01 00:00:00'
UNION
SELECT DISTINCT
    c.user_id
FROM bddwd_hive_db.D_CRM_INS_OFFER_H_D c
WHERE c.p_day = '20260630'
  AND c.offer_id = '610000149732'
  AND c.effective_date <= '2026-06-30 23:59:59'
  AND c.expire_date > '2026-06-01 00:00:00';

DROP TABLE IF EXISTS temp_ab26bbd180664400ba72132ecd0c4fc0_result_table;
CREATE TABLE temp_ab26bbd180664400ba72132ecd0c4fc0_result_table AS
SELECT
    t1.PRODUCT_NO AS user_number
FROM temp_ab26bbd180664400ba72132ecd0c4fc0_01 t1
LEFT ANTI JOIN temp_ab26bbd180664400ba72132ecd0c4fc0_02 t2
ON t1.USER_ID = t2.user_id;
