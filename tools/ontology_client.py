"""本体平台工具适配层。

定义 4 个本体工具的接口契约（Protocol）与两种实现：

1. MockOntologyClient —— 内置示例本体数据，用于无 DB 环境时的降级兜底。
2. DbOntologyClient  —— 从本地 MySQL `ontology` 库读取真实表结构
   （表 + 字段 + 注释）作为本体知识源，用 LLM 语义检索按问题匹配相关表。

检索策略：LLM 语义检索（DeepSeek）→ 失败时关键词匹配兜底 → 仍无结果则全选。
接入真实本体平台时实现 HttpOntologyClient 并替换 get_ontology_client() 即可。
"""

from __future__ import annotations

import copy
import json
import re
import time
from collections.abc import Callable
from typing import Any, Protocol

import pymysql

from config.settings import settings
from tools.llm_client import PLACEHOLDER_KEY, get_llm_client

# ---------------------------------------------------------------------------
# 示例本体数据（降级兜底用）
# ---------------------------------------------------------------------------

MOCK_ONTOLOGY_ID = "AITR00020260630246091"

MOCK_ONTOLOGY_DEFINITION: dict[str, Any] = {
    "ontology_id": MOCK_ONTOLOGY_ID,
    "object_classes": {
        "用户统一视图月表": {
            "table_name": "D_BBZX_DW_PRODUCT_M",
            "db_prefix": "bddwd_hive_db",
            "partition": "P_MON",
            "attributes": {
                "用户号码": {"field": "SUBS_NUMBER", "type": "STRING"},
                "地市编号": {"field": "CITY_ID", "type": "STRING"},
                "通话次数": {"field": "CALL_COUNTS", "type": "INT"},
                "GPRS流量": {"field": "GPRS_VOLUME", "type": "BIGINT"},
                "账期": {"field": "P_MON", "type": "STRING"},
            },
        }
    },
    "logical_definitions": {
        "沉默用户": "当月 CALL_COUNTS=0 或 NULL，且 GPRS_VOLUME=0 或 NULL"
    },
}

MOCK_ATTR_MAPPING: dict[str, dict[str, str]] = {
    "用户统一视图月表": {
        "用户号码": "SUBS_NUMBER",
        "地市编号": "CITY_ID",
        "通话次数": "CALL_COUNTS",
        "GPRS流量": "GPRS_VOLUME",
        "账期": "P_MON",
    }
}

MOCK_KNOWN_FIELDS: set[str] = {
    "SUBS_NUMBER",
    "CITY_ID",
    "CALL_COUNTS",
    "GPRS_VOLUME",
    "P_MON",
}


def _infer_db_prefix(table_name: str) -> str:
    """表名映射：D_→bddwd_hive_db，I_/A_→bddw_hive_db。"""
    upper = table_name.upper()
    for prefix, db in (("D_", "bddwd_hive_db"), ("I_", "bddw_hive_db"), ("A_", "bddw_hive_db")):
        if upper.startswith(prefix):
            return db
    return ""


# ---------------------------------------------------------------------------
# 无关问题判定（LLM 对无关问题也会硬选表，需独立于选表结果做相关性检查）
# ---------------------------------------------------------------------------

IRRELEVANT_MESSAGE = (
    "您好！我是本体取数助手。您的问题与取数业务无关，暂时无法生成 SQL。请描述具体的取数需求。"
)

# 取数意图/业务词：问题命中任一即视为取数相关（动词 + 业务词）
_QUERY_INTENT_WORDS = (
    "查询", "统计", "取数", "提取", "获取", "生成", "分析", "查看", "看看", "查一下",
    "多少", "几个", "有没有", "清单", "报表", "数据", "数量", "列表", "明细",
    "号码", "用户", "地市", "城市", "账期", "日期", "时间", "通话", "流量", "沉默",
    "投诉", "家庭", "决策者", "全球通", "集团", "订购", "套餐", "免打扰", "状态",
    "类型", "名称", "金额", "费用", "生效", "失效", "到期", "宽带", "账单", "年龄",
    "性别", "身份证", "5G", "发展", "办理", "安全管家",
)
# 月份账期模式（如 2026年6月 / 6月 / 3个月）
_QUERY_MONTH_RE = re.compile(r"(20\d{2}\s*年\s*\d{1,2}\s*个?\s*月|\d{1,2}\s*个?\s*月)")


def _is_irrelevant_query(query: str) -> bool:
    """问题相关性判定：无取数意图词/业务词/月份账期 → 判为无关问题。"""
    q = query or ""
    if any(w in q for w in _QUERY_INTENT_WORDS):
        return False
    if _QUERY_MONTH_RE.search(q):
        return False
    return True


def _irrelevant_definition(ontology_id: str | None = None) -> dict[str, Any]:
    """无关问题的 TTL 返回结构（对象为空 + 提示文案）。"""
    return {
        "ontology_id": ontology_id or "db-ontology",
        "object_classes": {},
        "logical_definitions": {},
        "relations": [],
        "field_meta": {},
        "irrelevant": True,
        "message": IRRELEVANT_MESSAGE,
    }


def _validate_sql_syntax(sql: str) -> dict[str, Any]:
    """语法校验（与知识库无关，Mock/Db 共用）。"""
    errors: list[str] = []
    stripped = sql.strip()
    if not stripped:
        errors.append("SQL 为空")
    else:
        upper = stripped.upper()
        if not any(
            upper.startswith(kw)
            for kw in ("SELECT", "DROP", "CREATE", "INSERT", "WITH")
        ):
            errors.append("SQL 必须以 SELECT/DROP/CREATE 等合法关键字开头")
        if "FROM" not in upper and "CREATE TABLE" not in upper:
            errors.append("SQL 缺少 FROM 子句")
        if not stripped.endswith(";"):
            errors.append("SQL 必须以分号结束")
        if stripped.count("(") != stripped.count(")"):
            errors.append("SQL 括号不匹配")
    return {"valid": not errors, "errors": errors}


# ---------------------------------------------------------------------------
# 接口契约
# ---------------------------------------------------------------------------


class OntologyClient(Protocol):
    """本体平台 4 个工具的接口契约。"""

    def get_ontology_definition(
        self,
        user_query: str,
        additional_context: str | None = None,
        ontology_id: str | None = None,
    ) -> dict[str, Any]:
        """获取 TTL 本体表定义及逻辑定义。"""
        ...

    def get_attr_mapping(
        self,
        ontology_name: str,
        object_names: list[str],
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """获取「中文属性名 → 物理字段名」映射及主键。"""
        ...

    def validate_sql(self, sql: str, dialect: str = "hive") -> dict[str, Any]:
        """语法校验，返回 {"valid": bool, "errors": list}。"""
        ...

    def validate_sql_semantics(
        self, sql: str, ttl_content: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """语义校验（外部表仅验表名），返回 {"valid": bool, "errors": list}。"""
        ...


# ---------------------------------------------------------------------------
# Mock 实现（降级兜底）
# ---------------------------------------------------------------------------


def _extract_sql_identifiers(sql: str) -> set[str]:
    """提取 SQL 中的标识符：去掉「别名.」前缀（p.PRODUCT_NO→PRODUCT_NO）、
    剥掉字符串字面量（'YYYY-MM-DD HH24:MI:SS' 日期格式串/常量）、
    过滤单字母别名（o/p/h/m 等），避免误判为未知字段。"""
    sql_upper = sql.upper()
    sql_upper = re.sub(r"'[^']*'", "", sql_upper)  # 剥字符串字面量
    sql_norm = re.sub(r"\b[A-Z_][A-Z0-9_]*\s*\.\s*", "", sql_upper)
    ids = set(re.findall(r"\b[A-Z_][A-Z0-9_]*\b", sql_norm))
    # 过滤短别名（1-2 字母纯标识符如 o/p/od/oh 是表别名；真实字段为 snake_case 含下划线或 ≥3 字母）
    return {x for x in ids if len(x) > 2 or "_" in x}


def _extract_table_refs(sql: str) -> set[str]:
    """提取 SQL 中的表名引用（FROM/JOIN/INTO/UPDATE/CREATE TABLE/DROP TABLE 后的标识符），
    供语义校验识别临时表/库前缀表名。"""
    refs: set[str] = set()
    sql_upper = sql.upper()
    for m in re.finditer(
        r"\b(?:FROM|JOIN|INTO|UPDATE|DROP\s+TABLE|CREATE\s+TABLE|ALTER\s+TABLE)\s+"
        r"([A-Z_][A-Z0-9_.]*)",
        sql_upper,
    ):
        refs.add(m.group(1).split(".")[-1])
    return refs


class MockOntologyClient:
    """内置示例本体数据的 Mock 实现，用于本地开发走通流程。"""

    def get_ontology_definition(
        self,
        user_query: str,
        additional_context: str | None = None,
        ontology_id: str | None = None,
    ) -> dict[str, Any]:
        return dict(MOCK_ONTOLOGY_DEFINITION)

    def get_attr_mapping(
        self,
        ontology_name: str,
        object_names: list[str],
        user_id: str | None = None,
    ) -> dict[str, Any]:
        mapping: dict[str, Any] = {"ontology_name": ontology_name}
        for obj in object_names:
            mapping[obj] = dict(MOCK_ATTR_MAPPING.get(obj, {}))
        mapping["primary_keys"] = {"用户统一视图月表": "SUBS_NUMBER"}
        return mapping

    def validate_sql(self, sql: str, dialect: str = "hive") -> dict[str, Any]:
        return _validate_sql_syntax(sql)

    def validate_sql_semantics(
        self, sql: str, ttl_content: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        errors: list[str] = []
        identifiers = _extract_sql_identifiers(sql)
        keywords = {
            "SELECT", "FROM", "WHERE", "AS", "AND", "OR", "NOT", "NULL",
            "JOIN", "ON", "LEFT", "INNER", "GROUP", "BY", "ORDER", "DROP",
            "TABLE", "IF", "EXISTS", "CREATE", "INSERT", "INTO", "VALUES",
            "CASE", "WHEN", "THEN", "ELSE", "END", "CAST", "STRING", "INT",
            "BIGINT", "COUNT", "SUM", "DISTINCT", "LIMIT", "TRUE", "FALSE",
            "USING", "BETWEEN", "IN", "LIKE", "IS",
            # Hive 常用函数（避免函数名被误判为未知字段）
            "TO_DATE", "DATE_FORMAT", "DATE_ADD", "DATE_SUB", "DATEDIFF",
            "UNIX_TIMESTAMP", "FROM_UNIXTIME", "NVL", "COALESCE", "IFNULL",
            "SUBSTR", "SUBSTRING", "CONCAT", "ROW_NUMBER", "RANK", "OVER",
            "PARTITION", "UNION", "ALL", "HAVING", "DESC", "ASC", "TRUNCATE",
        }
        known_tables = {
            str(obj["table_name"])
            for obj in MOCK_ONTOLOGY_DEFINITION["object_classes"].values()
        }
        known_tables |= _extract_table_refs(sql)
        known_dbs = {"BDDWD_HIVE_DB", "BDDW_HIVE_DB"}
        unknown = identifiers - MOCK_KNOWN_FIELDS - keywords - known_tables - known_dbs
        # 临时表（提示词规范 temp_ 前缀）放行
        unknown = {x for x in unknown if not x.startswith("TEMP_")}
        if unknown:
            errors.append(f"未知字段（不在本体映射中）: {sorted(unknown)}")
        return {"valid": not errors, "errors": errors}


# ---------------------------------------------------------------------------
# Db 实现：从 MySQL ontology 库读取真实表结构作为本体知识源
# ---------------------------------------------------------------------------

# 本体元数据表（关系定义/逻辑定义/字段元数据），不作为本体对象参与检索
_META_TABLES = {"ONTOLOGY_RELATIONS", "ONTOLOGY_LOGICAL_DEFS", "ONTOLOGY_FIELD_META"}

# ---------------------------------------------------------------------------
# 元数据 TTL 缓存（表结构/元数据变更频率极低，避免每次请求多次查 information_schema）
# ---------------------------------------------------------------------------

_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_TTL: dict[str, float] = {
    "tables": 300.0,  # 表结构极少变更，缓存 5 分钟
    "logical_defs": 60.0,
    "relations": 60.0,
    "field_meta": 60.0,  # 后台可编辑，缓存 1 分钟
}


def _cached(key: str, loader: Callable[[], Any]) -> Any:
    """带 TTL 的模块级缓存：命中返回深拷贝，未命中调 loader 后缓存。"""
    now = time.time()
    hit = _CACHE.get(key)
    if hit is not None and now - hit[0] < _CACHE_TTL.get(key, 60.0):
        return copy.deepcopy(hit[1])
    value = loader()
    _CACHE[key] = (now, value)
    return copy.deepcopy(value)


def clear_ontology_cache() -> None:
    """清空元数据 TTL 缓存（表结构/元数据变更后调用；测试隔离用）。"""
    _CACHE.clear()


class DbOntologyClient:
    """从本地 MySQL `ontology` 库读取真实表结构（表+字段+注释）作为本体知识源。

    用户（或取数人员）在 MySQL ontology 库下建表并维护注释：
    - 表注释：中文表描述 + 业务口径
    - 字段注释：字段中文名（含"分区"字样标记分区字段）
    检索器据此做 LLM 语义匹配，把问题映射到正确的表与口径。
    """

    def _load_tables(self) -> list[dict[str, Any]]:
        """读 MySQL ontology 库下所有表 + 字段 + 注释（TTL 缓存 300s）。"""
        return _cached("tables", self._load_tables_uncached)

    def _load_tables_uncached(self) -> list[dict[str, Any]]:
        """读 MySQL ontology 库下所有表 + 字段 + 注释（表/字段名统一转大写）。"""
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
            cur.execute(
                "SELECT TABLE_NAME, TABLE_COMMENT FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE'",
                (settings.mysql.database,),
            )
            table_rows = cur.fetchall()
            cur.execute(
                "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, COLUMN_COMMENT "
                "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s "
                "ORDER BY TABLE_NAME, ORDINAL_POSITION",
                (settings.mysql.database,),
            )
            col_rows = cur.fetchall()
            # 表描述（独立存储，与表中文名分离；表不存在时容错为空）
            try:
                cur.execute(f"SELECT table_name, table_desc FROM {settings.mysql.meta_database}.ontology_table_meta")
                desc_rows = cur.fetchall()
            except pymysql.err.ProgrammingError:
                desc_rows = []
        finally:
            conn.close()

        desc_map = {r[0].lower(): r[1] for r in desc_rows}
        tables: dict[str, dict[str, Any]] = {}
        for tname, tcomment in table_rows:
            key = tname.upper()
            if key in _META_TABLES:
                continue  # 排除本体元数据表（关系/逻辑定义），不作为对象
            tables[key] = {
                "table_name": key,
                "table_comment": tcomment or "",
                "table_desc": desc_map.get(tname.lower(), ""),
                "columns": [],
            }
        for tname, cname, ctype, ccomment in col_rows:
            key = tname.upper()
            if key in tables:
                tables[key]["columns"].append(
                    {"name": cname.upper(), "type": ctype, "comment": ccomment or ""}
                )
        return list(tables.values())

    def _llm_select_tables(
        self,
        user_query: str,
        tables: list[dict[str, Any]],
        conversation_context: str | None = None,
    ) -> list[str]:
        """LLM 语义检索：从候选表中选出与问题最相关的表名。失败返回 []。"""
        llm = get_llm_client()
        if not llm.api_key or llm.api_key == PLACEHOLDER_KEY:
            return []
        candidates = []
        for t in tables:
            cols = ", ".join(
                f"{c['name']}({c['comment'] or ''})" for c in t["columns"]
            )
            desc = " / ".join(x for x in (t["table_comment"], t.get("table_desc")) if x)
            candidates.append(f"{t['table_name']} | {desc} | 字段: {cols}")
        prompt = (
            "你是本体表结构检索助手。根据用户问题，从候选表中选择最相关的表（可多选，最多 3 个）。\n"
            "候选表（表名 | 表描述 | 字段）：\n" + "\n".join(candidates) + "\n\n"
            f"用户问题：{user_query}\n"
            '只输出 JSON，格式 {"tables": ["表名1", "表名2"]}，表名必须与候选表完全一致。'
            "若用户问题与候选表业务完全无关（如闲聊、天气、算术），返回 {\"tables\": []}。"
        )
        if conversation_context:
            prompt += f"\n本轮共享会话上下文：\n{conversation_context}"
        try:
            raw = llm.generate_sql(prompt, user_query)
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                data = json.loads(m.group(0))
                names = data.get("tables", [])
                return [str(n).upper() for n in names]
        except Exception:
            return []
        # 兜底：从原始返回中提取候选表名
        up = raw.upper()
        return [t["table_name"] for t in tables if t["table_name"] in up]

    def _keyword_select_tables(
        self, user_query: str, tables: list[dict[str, Any]]
    ) -> list[str]:
        """关键词兜底：问题与表注释/字段注释的中文关键词匹配。"""
        keywords = [
            "沉默", "投诉", "家庭", "决策者", "全球通", "集团", "订购", "免打扰",
            "用户", "通话", "流量", "宽带", "账单", "5G",
        ]
        result = []
        for t in tables:
            text = " ".join(
                [t["table_comment"] or ""]
                + [t.get("table_desc") or ""]
                + [c["comment"] or "" for c in t["columns"]]
            )
            if any(kw in text for kw in keywords if kw in user_query):
                result.append(t["table_name"])
        return result

    def _load_logical_defs(self) -> dict[str, str]:
        """读逻辑定义表，返回 {口径名: 描述(含条件)}（TTL 缓存 60s）。"""
        return _cached("logical_defs", self._load_logical_defs_uncached)

    def _load_logical_defs_uncached(self) -> dict[str, str]:
        """读逻辑定义表，返回 {口径名: 描述(含条件)}。"""
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
                "SELECT def_name, table_name, def_desc, def_condition "
                "FROM ontology_logical_defs"
            )
            rows = cur.fetchall()
        finally:
            conn.close()
        result: dict[str, str] = {}
        for name, table, desc, cond in rows:
            text = desc or ""
            if cond:
                text += f"（条件：{cond}）"
            result[name] = text
        return result

    def _load_relations(self) -> list[dict[str, str]]:
        """读关系定义表，返回表间 JOIN 关联列表（TTL 缓存 60s）。"""
        return _cached("relations", self._load_relations_uncached)

    def _load_relations_uncached(self) -> list[dict[str, str]]:
        """读关系定义表，返回表间 JOIN 关联列表。"""
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
                "SELECT source_table, source_field, target_table, target_field, "
                "relation_type, relation_label FROM ontology_relations"
            )
            rows = cur.fetchall()
        finally:
            conn.close()
        return [
            {
                "source_table": s.upper(),
                "source_field": sf.upper(),
                "target_table": t.upper(),
                "target_field": tf.upper(),
                "relation_type": rt or "",
                "relation_label": rl or "",
            }
            for s, sf, t, tf, rt, rl in rows
        ]

    def _load_field_meta(self) -> dict[str, dict[str, str]]:
        """读字段元数据表（仅当前生效 status=1），返回 {表名: {字段名: 描述}}（TTL 缓存 60s）。"""
        return _cached("field_meta", self._load_field_meta_uncached)

    def _load_field_meta_uncached(self) -> dict[str, dict[str, str]]:
        """读字段元数据表（仅当前生效 status=1），返回 {表名: {字段名: 描述}}。"""
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
                "SELECT table_name, field_name, field_desc FROM ontology_field_meta "
                "WHERE status=1"
            )
            rows = cur.fetchall()
        finally:
            conn.close()
        result: dict[str, dict[str, str]] = {}
        for tname, fname, desc in rows:
            result.setdefault(tname.upper(), {})[fname.upper()] = desc or ""
        return result

    def get_ontology_definition(
        self,
        user_query: str,
        additional_context: str | None = None,
        ontology_id: str | None = None,
    ) -> dict[str, Any]:
        """按问题检索相关表，组装 TTL 定义（对象 + 逻辑定义 + 关系定义 + 字段描述）。"""
        tables = self._load_tables()
        if not tables:
            return dict(MOCK_ONTOLOGY_DEFINITION)

        # 无关问题拦截：问题无任何取数意图/业务词 → 直接返回友好提示（不硬选表）
        if _is_irrelevant_query(user_query):
            return _irrelevant_definition(ontology_id)

        if additional_context:
            selected_names = self._llm_select_tables(
                user_query,
                tables,
                additional_context,
            )
        else:
            selected_names = self._llm_select_tables(user_query, tables)
        if not selected_names:
            selected_names = self._keyword_select_tables(user_query, tables)
        selected = [t for t in tables if t["table_name"] in selected_names]
        if not selected:
            selected = tables  # 取数相关但选表失败时全选兜底

        object_classes: dict[str, Any] = {}
        for t in selected:
            attributes = {
                c["comment"]: {"field": c["name"], "type": c["type"]}
                for c in t["columns"]
                if c["comment"]
            }
            partition = next(
                (c["name"] for c in t["columns"] if "分区" in (c["comment"] or "")),
                None,
            )
            object_classes[t["table_name"]] = {
                "table_name": t["table_name"],
                "db_prefix": _infer_db_prefix(t["table_name"]),
                "partition": partition,
                "attributes": attributes,
            }

        return {
            "ontology_id": ontology_id or "db-ontology",
            "object_classes": object_classes,
            "logical_definitions": self._load_logical_defs(),
            "relations": self._load_relations(),
            "field_meta": self._load_field_meta(),
        }

    def get_attr_mapping(
        self,
        ontology_name: str,
        object_names: list[str],
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """从 ontology schema 读「字段注释(中文名) → 物理字段名」映射。"""
        tables = self._load_tables()
        mapping: dict[str, Any] = {"ontology_name": ontology_name, "primary_keys": {}}
        for t in tables:
            if t["table_name"] in object_names:
                mapping[t["table_name"]] = {
                    c["comment"]: c["name"]
                    for c in t["columns"]
                    if c["comment"]
                }
        return mapping

    def validate_sql(self, sql: str, dialect: str = "hive") -> dict[str, Any]:
        return _validate_sql_syntax(sql)

    def validate_sql_semantics(
        self, sql: str, ttl_content: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """语义校验：字段集与表名集从 ontology schema 动态加载。"""
        errors: list[str] = []
        tables = self._load_tables()
        if not tables:
            return MockOntologyClient().validate_sql_semantics(sql, ttl_content)

        known_fields: set[str] = set()
        known_tables: set[str] = set()
        for t in tables:
            known_tables.add(t["table_name"])
            for c in t["columns"]:
                known_fields.add(c["name"])
        known_tables |= _extract_table_refs(sql)

        identifiers = _extract_sql_identifiers(sql)
        keywords = {
            "SELECT", "FROM", "WHERE", "AS", "AND", "OR", "NOT", "NULL",
            "JOIN", "ON", "LEFT", "INNER", "GROUP", "BY", "ORDER", "DROP",
            "TABLE", "IF", "EXISTS", "CREATE", "INSERT", "INTO", "VALUES",
            "CASE", "WHEN", "THEN", "ELSE", "END", "CAST", "STRING", "INT",
            "BIGINT", "COUNT", "SUM", "DISTINCT", "LIMIT", "TRUE", "FALSE",
            "USING", "BETWEEN", "IN", "LIKE", "IS",
            # Hive 常用函数（避免函数名被误判为未知字段）
            "TO_DATE", "DATE_FORMAT", "DATE_ADD", "DATE_SUB", "DATEDIFF",
            "UNIX_TIMESTAMP", "FROM_UNIXTIME", "NVL", "COALESCE", "IFNULL",
            "SUBSTR", "SUBSTRING", "CONCAT", "ROW_NUMBER", "RANK", "OVER",
            "PARTITION", "UNION", "ALL", "HAVING", "DESC", "ASC", "TRUNCATE",
        }
        known_dbs = {"BDDWD_HIVE_DB", "BDDW_HIVE_DB"}
        unknown = identifiers - known_fields - keywords - known_tables - known_dbs
        # 临时表（提示词规范 temp_ 前缀）放行
        unknown = {x for x in unknown if not x.startswith("TEMP_")}
        if unknown:
            errors.append(f"未知字段（不在本体映射中）: {sorted(unknown)}")
        return {"valid": not errors, "errors": errors}


# ---------------------------------------------------------------------------
# 客户端单例
# ---------------------------------------------------------------------------

_client: OntologyClient | None = None


def get_ontology_client() -> OntologyClient:
    """返回本体平台客户端单例（当前为 DbOntologyClient，读 ontology schema）。"""
    global _client
    if _client is None:
        _client = DbOntologyClient()
    return _client
