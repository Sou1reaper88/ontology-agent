"""OAG 检索器测试：DbOntologyClient 读 MySQL ontology 库表结构 + 语义检索 + 兜底。

使用独立的临时测试表（fixture 建表、测完清理），不依赖用户手工维护的真实表结构。
LLM 由 conftest 的 harness fixture 强制为无 Key（检索走关键词兜底）。
"""

from __future__ import annotations

import pytest
import pymysql

from config.settings import settings
from tools.ontology_client import DbOntologyClient

TEST_TABLE = "ZZ_TEST_RETRIEVAL"


@pytest.fixture
def test_table():
    """在 MySQL ontology 库建一张固定结构的测试表，测完清理。"""
    conn = pymysql.connect(
        host=settings.mysql.host,
        port=settings.mysql.port,
        user=settings.mysql.user,
        password=settings.mysql.password,
        charset="utf8mb4",
    )
    cur = conn.cursor()
    cur.execute(f"DROP TABLE IF EXISTS {settings.mysql.database}.{TEST_TABLE.lower()}")
    cur.execute(
        f"CREATE TABLE {settings.mysql.database}.{TEST_TABLE.lower()} ("
        "subs_number VARCHAR(255) COMMENT '用户号码', "
        "call_counts INT COMMENT '通话次数', "
        "gprs_volume BIGINT COMMENT 'GPRS流量', "
        "p_mon VARCHAR(255) COMMENT '账期(分区)'"
        ") COMMENT='沉默用户测试表'"
    )
    conn.commit()
    yield TEST_TABLE
    cur.execute(f"DROP TABLE IF EXISTS {settings.mysql.database}.{TEST_TABLE.lower()}")
    conn.commit()
    cur.close()
    conn.close()


def _find(tables: list[dict], name: str = TEST_TABLE) -> dict:
    for t in tables:
        if t["table_name"] == name:
            return t
    raise AssertionError(f"测试表 {name} 不存在")


def test_load_tables_reads_schema(test_table) -> None:
    """读 MySQL ontology 库：表名/字段名转大写，注释正确。"""
    c = DbOntologyClient()
    t = _find(c._load_tables())
    assert t["table_comment"] and "沉默用户" in t["table_comment"]
    fields = {col["name"] for col in t["columns"]}
    assert {"SUBS_NUMBER", "CALL_COUNTS", "GPRS_VOLUME", "P_MON"} <= fields
    comments = {col["name"]: col["comment"] for col in t["columns"]}
    assert comments["SUBS_NUMBER"] == "用户号码"
    assert "分区" in comments["P_MON"]


def test_get_ontology_definition_assembles_ttl(test_table, monkeypatch) -> None:
    """组装 ttl_def：db_prefix 推断、分区识别、逻辑口径、关系定义字段。"""
    c = DbOntologyClient()
    monkeypatch.setattr(c, "_llm_select_tables", lambda q, tables: [])  # LLM 失败→关键词兜底
    ttl = c.get_ontology_definition("查询沉默用户")
    assert TEST_TABLE in ttl["object_classes"]
    obj = ttl["object_classes"][TEST_TABLE]
    assert obj["db_prefix"] == ""  # zz_ 前缀无映射
    assert obj["partition"] == "P_MON"  # 注释含"分区"
    # 逻辑定义从 ontology_logical_defs 表读（含迁移的"沉默用户"口径）
    assert isinstance(ttl["logical_definitions"], dict)
    assert "relations" in ttl and isinstance(ttl["relations"], list)


def test_keyword_fallback_selects_table(test_table, monkeypatch) -> None:
    """关键词兜底：问题含"沉默"→ 匹配到含该口径的表。"""
    c = DbOntologyClient()
    tables = c._load_tables()
    assert TEST_TABLE in c._keyword_select_tables("查询6月沉默用户", tables)


def test_irrelevant_query_intercepted(test_table) -> None:
    """无关问题（天气/闲聊/算术）→ 直接返回 irrelevant，不进入选表。"""
    c = DbOntologyClient()
    for q in ("今天天气怎么样", "你是谁", "1加1等于几"):
        ttl = c.get_ontology_definition(q)
        assert ttl.get("irrelevant") is True, q
        assert not ttl["object_classes"]
        assert "无关" in ttl.get("message", "")

    # 取数相关问题不受影响
    ttl = c.get_ontology_definition("查询6月沉默用户")
    assert not ttl.get("irrelevant")
    assert TEST_TABLE in ttl["object_classes"]

    # 极简业务表达（无动词）也能识别为相关
    assert not c.get_ontology_definition("6月沉默用户").get("irrelevant")
    assert not c.get_ontology_definition("2026年6月的数据").get("irrelevant")


def test_keyword_fallback_matches_table_desc(test_table) -> None:
    """关键词兜底：问题命中表描述（独立于中文名/字段注释）也能召回表。"""
    c = DbOntologyClient()
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
            "INSERT INTO ontology_table_meta (table_name, table_desc) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE table_desc=VALUES(table_desc)",
            (TEST_TABLE.lower(), "包含国际漫游用户的通话与流量明细"),
        )
        conn.commit()
        tables = c._load_tables()
        assert TEST_TABLE in c._keyword_select_tables("查询国际漫游用户", tables)
    finally:
        from tools.ontology_client import clear_ontology_cache

        cur = conn.cursor()
        cur.execute("DELETE FROM ontology_table_meta WHERE table_name=%s", (TEST_TABLE.lower(),))
        conn.commit()
        conn.close()
        clear_ontology_cache()


def test_attr_mapping_chinese_to_field(test_table) -> None:
    """字段注释(中文名) → 物理字段名映射。"""
    c = DbOntologyClient()
    am = c.get_attr_mapping("db-ontology", [TEST_TABLE])
    assert am[TEST_TABLE]["用户号码"] == "SUBS_NUMBER"
    assert am[TEST_TABLE]["通话次数"] == "CALL_COUNTS"


def test_semantics_uses_dynamic_fields(test_table) -> None:
    """语义校验字段集从 MySQL ontology 库动态加载。"""
    c = DbOntologyClient()
    ok = c.validate_sql_semantics(
        "SELECT SUBS_NUMBER, CALL_COUNTS FROM zz_test_retrieval WHERE P_MON='202606';"
    )
    assert ok["valid"] is True
    bad = c.validate_sql_semantics(
        "SELECT NOT_EXIST_FIELD FROM zz_test_retrieval;"
    )
    assert bad["valid"] is False


def test_semantics_allows_table_aliases(test_table) -> None:
    """语义校验：表别名（p.PRODUCT_NO / 单字母别名）不应误判为未知字段。"""
    c = DbOntologyClient()
    ok = c.validate_sql_semantics(
        "SELECT p.SUBS_NUMBER, p.CALL_COUNTS FROM zz_test_retrieval p WHERE p.P_MON='202606';"
    )
    assert ok["valid"] is True, ok.get("errors")
    ok2 = c.validate_sql_semantics(
        "SELECT DISTINCT p.PRODUCT_NO FROM zz_test_retrieval p "
        "LEFT JOIN zz_test_retrieval o ON o.SUBS_NUMBER = p.SUBS_NUMBER;"
    )
    assert ok2["valid"] is True, ok2.get("errors")


def test_semantics_allows_temp_tables(test_table) -> None:
    """语义校验：过程表（temp_ 前缀 + CREATE/DROP TABLE 引用）不应误判为未知字段。"""
    c = DbOntologyClient()
    sql = (
        "DROP TABLE IF EXISTS bddwd_hive_db.temp_AITR000123_1;\n"
        "CREATE TABLE bddwd_hive_db.temp_AITR000123_1 AS "
        "SELECT SUBS_NUMBER, CALL_COUNTS FROM zz_test_retrieval WHERE P_MON='202606';\n"
        "DROP TABLE IF EXISTS bddwd_hive_db.temp_AITR000123_result_table;\n"
        "CREATE TABLE bddwd_hive_db.temp_AITR000123_result_table AS "
        "SELECT SUBS_NUMBER FROM bddwd_hive_db.temp_AITR000123_1 WHERE CALL_COUNTS=0;"
    )
    r = c.validate_sql_semantics(sql)
    assert r["valid"] is True, r.get("errors")


def test_fallback_to_mock_when_schema_empty(monkeypatch) -> None:
    """schema 无表时降级到内置 Mock 定义。"""
    c = DbOntologyClient()
    monkeypatch.setattr(c, "_load_tables", lambda: [])
    ttl = c.get_ontology_definition("查询沉默用户")
    assert "用户统一视图月表" in ttl["object_classes"]


def test_llm_select_parses_json(test_table, monkeypatch) -> None:
    """LLM 检索返回 JSON 时正确解析表名。"""
    c = DbOntologyClient()
    tables = c._load_tables()

    class _FakeLLM:
        api_key = "x"

        def generate_sql(self, *a, **k):
            return f'{{"tables": ["{TEST_TABLE}"]}}'

    monkeypatch.setattr("tools.ontology_client.get_llm_client", lambda: _FakeLLM())
    assert c._llm_select_tables("查询沉默用户", tables) == [TEST_TABLE]


def test_table_selection_receives_assembled_conversation_context(monkeypatch) -> None:
    c = DbOntologyClient()
    table = {
        "table_name": TEST_TABLE,
        "table_comment": "客户表",
        "table_desc": "客户基础信息",
        "columns": [],
    }
    captured = {}

    def fake_select(query, tables, conversation_context=None):
        captured["context"] = conversation_context
        return [TEST_TABLE]

    monkeypatch.setattr(c, "_load_tables", lambda: [table])
    monkeypatch.setattr(c, "_llm_select_tables", fake_select)

    result = c.get_ontology_definition(
        "查询客户",
        additional_context="用户已确认仅查询浙江客户",
    )

    assert captured["context"] == "用户已确认仅查询浙江客户"
    assert TEST_TABLE in result["object_classes"]


def test_semantics_allows_hive_functions_and_date_literals(test_table) -> None:
    """语义校验：Hive 日期函数（TO_DATE 等）与日期格式串不应误判为未知字段。"""
    c = DbOntologyClient()
    sql = (
        "SELECT p.SUBS_NUMBER FROM zz_test_retrieval p "
        "WHERE TO_DATE(p.EFFECTIVE_DATE, 'YYYY-MM-DD HH24:MI:SS') <= TO_DATE('2026-06-30 23:59:59', 'YYYY-MM-DD HH24:MI:SS') "
        "AND NVL(p.CALL_COUNTS, 0) = 0;"
    )
    r = c.validate_sql_semantics(sql)
    # 字符串字面量已被剥离（YYYY/MM/DD/HH24/MI/SS/TO_DATE 均不应报未知）
    errs = r.get("errors") or []
    assert r["valid"] is True or not any(
        x in "".join(errs) for x in ("TO_DATE", "YYYY", "HH24", "MI", "SS", "MM", "DD")
    ), errs
    # 编造字段仍应拦截
    bad = c.validate_sql_semantics("SELECT OFFER_PLAN_ID FROM zz_test_retrieval;")
    assert bad["valid"] is False
    assert "OFFER_PLAN_ID" in "".join(bad.get("errors") or [])
