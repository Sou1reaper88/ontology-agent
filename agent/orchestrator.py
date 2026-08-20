"""LangGraph Agent 编排：本体驱动 HiveSQL 编译 8 步流程。

节点 1-6 线性执行；节点 7 审计校验（7a 语法 / 7b 语义 + fix 受限修复 + retry 循环）；
节点 8 格式化输出。对齐框架文档的执行流程与修复权限。
"""

from __future__ import annotations

import calendar
import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from tools.llm_client import PLACEHOLDER_KEY, get_llm_client
from tools.ontology_client import IRRELEVANT_MESSAGE, get_ontology_client

logger = logging.getLogger(__name__)


class AgentState(TypedDict, total=False):
    """贯穿全流程的状态对象。"""

    user_query: str
    additional_context: str | None
    ontology_id: str | None
    system_time: str | None
    history: list[dict[str, str]]
    conversation_context: str | None
    ttl_def: dict[str, Any]
    attr_map: dict[str, Any]
    field_map: dict[str, str]
    external_tables: list[str]
    p_day: str
    p_mon: str
    derived_rules: dict[str, Any] | None  # 口径推导结果（逻辑定义未命中时 LLM 推导）
    sql: str
    sql_valid: bool
    retry_count: int
    errors: list[str]
    trace: list[dict[str, Any]]
    irrelevant: bool
    output: dict[str, Any]


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

_DB_PREFIX_RULES = [
    ("D_", "bddwd_hive_db"),
    ("I_", "bddw_hive_db"),
    ("A_", "bddw_hive_db"),
]


def _db_prefix(table: str) -> str:
    """表名映射：D_→bddwd_hive_db，I_/A_→bddw_hive_db。"""
    for prefix, db in _DB_PREFIX_RULES:
        if table.startswith(prefix):
            return db
    return ""


# ---------------------------------------------------------------------------
# 字段级上下文裁剪（P0 优化：198 字段大表避免全量注入 prompt，稀释注意力）
# ---------------------------------------------------------------------------

# 裁剪触发业务词：问题命中任一 → 启动裁剪
_FIELD_KEYWORDS = (
    "号码", "用户", "地市", "城市", "账期", "日期", "时间", "通话", "流量", "沉默",
    "投诉", "家庭", "决策者", "全球通", "集团", "订购", "套餐", "免打扰", "状态",
    "类型", "名称", "金额", "费用", "生效", "失效", "到期", "宽带", "账单", "年龄",
    "性别", "身份证", "5G", "发展", "办理", "安全管家",
)
# 触发词命中时额外保留的字段子集（业务口径依赖的字段，如"沉默"需通话/流量字段）
_TRIGGER_EXTRA: dict[str, tuple[str, ...]] = {
    "沉默": ("通话", "流量", "GPRS", "呼叫"),
    "免打扰": ("免打扰", "短信", "来信"),
}
_KEEP_MIN_FIELDS = 15  # 裁剪保底字段数，保证 SELECT 输出字段可选


def _filter_field_map(
    user_query: str,
    field_map: dict[str, str],
    partitions: set[str] | None = None,
) -> dict[str, str]:
    """按问题关键词裁剪「中文属性→物理字段」映射。

    规则：
    - 问题未命中任何业务词 → 全量返回（保守不裁，避免误伤）；
    - 命中 → 保留：分区字段 + 中文名含命中词的字段 + 触发词关联字段；
    - 仍不足 keep_min 时按原序补足，保证输出字段可选性。
    """
    if not field_map:
        return field_map
    partitions = partitions or set()
    hit = [kw for kw in _FIELD_KEYWORDS if kw in user_query]
    if not hit:
        return field_map
    extra = [w for t in hit for w in _TRIGGER_EXTRA.get(t, ())]
    kept: dict[str, str] = {}
    for cn, en in field_map.items():
        if en in partitions or any(kw in cn for kw in hit) or any(w in cn for w in extra):
            kept[cn] = en
    for cn, en in field_map.items():  # 保底补足
        if len(kept) >= _KEEP_MIN_FIELDS:
            break
        if cn not in kept:
            kept[cn] = en
    return kept


# ---------------------------------------------------------------------------
# 节点 1：获取 TTL 定义
# ---------------------------------------------------------------------------


def node_get_ttl_definition(state: AgentState) -> dict[str, Any]:
    client = get_ontology_client()
    ttl = client.get_ontology_definition(
        state["user_query"],
        state.get("additional_context"),
        state.get("ontology_id"),
    )
    # 无关问题：检索器返回 irrelevant 标记 → 短路到失败输出（友好提示）
    if ttl.get("irrelevant"):
        msg = ttl.get("message") or IRRELEVANT_MESSAGE
        return {
            "ttl_def": ttl,
            "irrelevant": True,
            "errors": [msg],
            "sql_valid": False,
        }
    return {"ttl_def": ttl}


def route_after_ttl(state: AgentState) -> str:
    """无关问题直接短路到失败输出，不进入后续取数流程。"""
    return "format_failure" if state.get("irrelevant") else "parse_external_tables"


# ---------------------------------------------------------------------------
# 节点 2：解析用户外部表（无工具调用）
# ---------------------------------------------------------------------------


def node_parse_external_tables(state: AgentState) -> dict[str, Any]:
    tables = re.findall(r"(?:表名|外部表)[:：]\s*([A-Za-z_][A-Za-z0-9_]*)", state["user_query"])
    return {"external_tables": tables}


# ---------------------------------------------------------------------------
# 节点 3：获取属性映射
# ---------------------------------------------------------------------------


def node_get_attr_mapping(state: AgentState) -> dict[str, Any]:
    client = get_ontology_client()
    ttl = state.get("ttl_def", {})
    object_names = list(ttl.get("object_classes", {}).keys())
    mapping = client.get_attr_mapping(
        ontology_name=str(ttl.get("ontology_id", "")),
        object_names=object_names,
    )
    return {"attr_map": mapping}


# ---------------------------------------------------------------------------
# 节点 4：属性名→物理字段名转换（关键步骤）
# ---------------------------------------------------------------------------


def node_transform_fields(state: AgentState) -> dict[str, Any]:
    field_map: dict[str, str] = {}
    for obj, attrs in (state.get("attr_map") or {}).items():
        if isinstance(attrs, dict):
            for cn, en in attrs.items():
                if isinstance(en, str):
                    field_map[cn] = en
    return {"field_map": field_map}


# ---------------------------------------------------------------------------
# 节点 5：日期推算
# ---------------------------------------------------------------------------


def node_calc_dates(state: AgentState) -> dict[str, Any]:
    raw = state.get("system_time") or datetime.now().strftime("%Y-%m-%d")
    try:
        base = datetime.strptime(str(raw)[:10], "%Y-%m-%d")
    except ValueError:
        base = datetime.now()
    p_day = (base - timedelta(days=2)).strftime("%Y%m%d")
    p_mon = (base.replace(day=1) - timedelta(days=1)).strftime("%Y%m")
    return {"p_day": p_day, "p_mon": p_mon}


# ---------------------------------------------------------------------------
# 节点 6：口径推导（逻辑定义未命中时，LLM 结合字段描述推导业务口径）
# ---------------------------------------------------------------------------


def _build_rules_prompt(state: AgentState) -> str:
    """口径推导 prompt：需求 + 选中表关键字段（中文注释+描述）+ 已有逻辑定义。

    字段裁剪：优先注入有描述/注释含业务词的字段（上限 80），避免长 prompt 稀释 LLM 注意力。
    """
    query = state.get("user_query", "")
    ttl = state.get("ttl_def", {})
    objs = ttl.get("object_classes", {})
    field_meta = ttl.get("field_meta", {})
    biz_words = (
        "通话", "流量", "费用", "金额", "次数", "时长", "状态", "标识", "类型",
        "订购", "套餐", "生效", "失效", "日期", "账期", "号码", "编码", "名称",
        "GPRS", "5G", "4G", "免费", "漫游", "投诉", "家庭", "集团", "宽带",
    )
    items: list[tuple[str, str, str, str]] = []
    for tname, obj in objs.items():
        attrs = obj.get("attributes", {})
        for comment, a in attrs.items():
            f = a.get("field") if isinstance(a, dict) else None
            if not f:
                continue
            desc = ((field_meta.get(tname) or {}).get(f) or "").strip()
            items.append((tname, f, str(comment), desc))

    def _score(item: tuple[str, str, str, str]) -> int:
        _t, _f, comment, desc = item
        return (2 if desc else 0) + (1 if any(w in comment for w in biz_words) else 0)

    items.sort(key=_score, reverse=True)
    items = items[:80]
    items.sort(key=lambda x: (x[0], x[1]))  # 裁剪后按表恢复稳定顺序
    lines = [
        f"{t}.{f}（{comment}{'；描述：' + d if d else ''}）"
        for t, f, comment, d in items
    ]
    if not lines:
        lines.append("（无候选字段）")
    logdefs = _render_logical_defs(ttl, state)
    return (
        "你是电信业务取数口径分析助手。根据用户取数需求与候选表字段信息，推导业务口径"
        "（过滤条件/统计口径），明确到物理字段与取值条件。\n"
        "候选表为电信用户业务宽表，包含通话/流量/费用/订购等业务字段；"
        "只要需求涉及上述业务领域，就必须推导口径（含 rule_condition），不得返回空。\n"
        "候选表字段（表.字段-中文注释-描述）：\n" + "\n".join(lines) + "\n\n"
        f"已有逻辑定义（若需求已覆盖可直接复用，未覆盖则推导新口径）：{logdefs}\n\n"
        f"用户需求：{query}\n"
        "要求：\n"
        "- 字段必须来自上述候选表字段，禁止编造\n"
        "- 若需求有明确业务口径（如沉默、免打扰、投诉、5G、宽带等），必须给出过滤条件\n"
        "- 需求中已被「已有逻辑定义」覆盖的口径直接复用，不要重复推导；若需求还存在逻辑定义未覆盖的"
        "业务口径（如免打扰、投诉、用户范围、订购关系等），必须推导这些口径\n"
        "- 若需求命中已有逻辑定义，必须把定义中的**全部条件**并入 rule_condition，不得遗漏"
        "（如命中「正常在网手机用户」则 rule_condition 必须同时含 USERSTATUS_ID 与 PROD_CATALOG_ID）\n"
        "- 若需求中所有业务口径均已被已有逻辑定义覆盖，才返回空 JSON\n"
        '- 只输出 JSON，格式 {"business_rules": "自然语言口径说明", "rule_fields": ["物理字段(大写)"], "rule_condition": "可直接拼入 WHERE 的 SQL 条件片段，字段大写，不含分区/账期条件"}\n'
        '- 若需求与候选表字段完全无关或无法推导，返回 {"business_rules": "", "rule_fields": [], "rule_condition": ""}'
    )


def _parse_rules(raw: str) -> dict[str, Any] | None:
    """解析口径推导 JSON，容错：非 JSON / 空口径 → None。"""
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except Exception:
        return None
    br = (data.get("business_rules") or "").strip()
    cond = (data.get("rule_condition") or "").strip()
    fields = [
        str(f).strip().upper()
        for f in (data.get("rule_fields") or [])
        if str(f).strip()
    ]
    if not br and not cond:
        return None
    return {"business_rules": br, "rule_fields": fields, "rule_condition": cond}


def node_derive_rules(state: AgentState) -> dict[str, Any]:
    """推导业务口径：命中已有逻辑定义时跳过（省时），否则 LLM 结合字段描述推导。

    推导结果（derived_rules）注入 SQL 生成 prompt、展示在推理逻辑、供回退模板使用。
    """
    query = state.get("user_query", "")
    ttl = state.get("ttl_def", {})
    logdefs = ttl.get("logical_definitions", {})
    # 注意：命中逻辑定义不短路——需求可能同时含已覆盖口径（沉默）+ 未覆盖口径（免打扰等），
    # 由 LLM 在推导时判断：全部被覆盖才返回空，否则推导未覆盖部分。
    llm = get_llm_client()
    if not llm.api_key or llm.api_key == PLACEHOLDER_KEY:
        return {"derived_rules": None}
    prompt = _build_rules_prompt(state)
    rules = None
    for attempt in range(2):
        try:
            raw = llm.generate_sql(prompt, query)
        except Exception as exc:
            logger.warning("口径推导调用异常(第%d次): %s", attempt + 1, exc)
            raw = ""
        rules = _parse_rules(raw)
        if rules is not None:
            break
        logger.warning("口径推导空结果(第%d次)，重试", attempt + 1)
    return {"derived_rules": rules}


# ---------------------------------------------------------------------------
# 节点 7：构建 SQL（LLM 优先，无 Key 时 Mock 模板兜底）
# ---------------------------------------------------------------------------


def _build_system_prompt(state: AgentState) -> str:
    ttl = state.get("ttl_def", {})
    field_map = state.get("field_map", {})

    # 字段级上下文裁剪：198 字段大表避免全量注入（问题未命中业务词时保守全量）
    partitions = {
        str(obj.get("partition"))
        for obj in ttl.get("object_classes", {}).values()
        if obj.get("partition")
    }
    filtered_map = _filter_field_map(state.get("user_query", ""), field_map, partitions)
    keep_fields = set(filtered_map.values())

    # 组装关系定义文本（表间 JOIN 关联）
    relations_text = ""
    relations = ttl.get("relations") or []
    if relations:
        relations_text = "关系定义（表间JOIN关联，生成多表SQL时按此关联）：\n"
        for r in relations:
            line = (
                f"{r['source_table']}.{r['source_field']} = "
                f"{r['target_table']}.{r['target_field']}"
            )
            if r.get("relation_label"):
                line += f"（{r['relation_label']}）"
            relations_text += line + "\n"

    # 组装字段描述文本（仅选中表 + 裁剪后保留的字段）
    field_meta_text = ""
    field_meta = ttl.get("field_meta") or {}
    selected_tables = set(ttl.get("object_classes", {}).keys())
    lines = []
    for table, fields in field_meta.items():
        if table in selected_tables:
            for fname, desc in fields.items():
                if desc and fname in keep_fields:
                    lines.append(f"{table}.{fname}: {desc}")
    if lines:
        field_meta_text = "字段描述（帮助理解字段业务含义）：\n" + "\n".join(lines) + "\n"

    # 动态生成示例（基于裁剪后保留的真实字段，避免硬编码过时字段）
    example_text = ""
    obj_classes = ttl.get("object_classes", {})
    if obj_classes and filtered_map:
        t = next(iter(obj_classes.values()))
        tbl = t.get("table_name", "")
        db_prefix = t.get("db_prefix", "bddwd_hive_db")
        partition = t.get("partition")
        fields = list(filtered_map.values())[:2]
        if partition and partition not in fields:
            fields.append(partition)
        if fields:
            where = f"WHERE {partition}='202607'" if partition else ""
            example_text = (
                "\n示例结构（字段来自当前本体映射，实际生成请按问题需要选取字段）：\n"
                f"SELECT {', '.join(fields)}\n"
                f"FROM {db_prefix}.{tbl}\n"
                f"{where};\n"
            )

    # 口径推导（逻辑定义未命中时 LLM 推导，注入供 SQL 生成严格遵守）
    derived_rules_text = ""
    derived = state.get("derived_rules")
    if derived and derived.get("business_rules"):
        derived_rules_text = (
            f"口径推导（本次需求由模型推导，必须严格遵守）：{derived['business_rules']}\n"
            f"口径涉及字段：{derived.get('rule_fields') or []}\n"
        )

    prompt = (
        "你是本体驱动的 HiveSQL 编译器。严格遵循以下技术规范：\n"
        "1. 零幻觉：仅使用下方映射中的物理字段名，缺失字段用 CAST(NULL AS STRING) AS 别名 占位。\n"
        "2. 禁用 CTE：中间逻辑用 DROP TABLE IF EXISTS ... CREATE TABLE ... AS SELECT 物理临时表。\n"
        "3. 表名映射：D_ 前缀→bddwd_hive_db，I_/A_ 前缀→bddw_hive_db。\n"
        "4. 分区裁剪：含分区字段的表必须加分区过滤。\n"
        "5. 命名规范：临时表 temp_{{ontology_id}}_序号，结果表 temp_{{ontology_id}}_result_table。\n"
        "6. 语法要求：显式 JOIN ... ON，英文别名，禁止中文别名，分号结束。\n\n"
        f"本体对象：{list(ttl.get('object_classes', {}).keys())}\n"
        f"属性映射（中文→物理字段，已按问题裁剪，仅用下方字段）：{filtered_map}\n"
        f"逻辑定义：{_render_logical_defs(ttl, state)}\n"
        f"{derived_rules_text}"
        f"{relations_text}"
        f"{field_meta_text}"
        f"推算分区：p_day={state.get('p_day')}, p_mon={state.get('p_mon')}\n"
        f"{example_text}"
        "\n硬性要求：\n"
        "- 只能使用上方列出的本体对象表与属性映射中的物理字段，禁止编造任何表名/字段名（如 users、orders、dim_user、fact_user_active 等一律禁止）。\n"
        "- 用户问题中的业务含义必须体现在 SQL 中（业务账期、用户类型等），不得输出与问题无关的通用查询。\n"
        "- 业务账期必须从用户问题中提取（如问题说'5月'则用 '202605'），推算分区 p_mon 仅用于问题未指明账期时的兜底。\n"
        "- 仅添加用户问题明确提及的业务条件，不要套用示例中问题未提及的条件（如用户没提沉默就不得加沉默判断）。\n"
        "- 若业务在本体逻辑定义中（如沉默用户），必须使用该定义生成条件。\n"
        "- 若存在「口径推导」段落，必须严格按其口径与字段生成过滤条件。\n"
        "- 排除类口径（如未订购某服务、非某种用户）优先用 NOT EXISTS 子查询实现，控制 SQL 长度避免输出过长。\n"
        "- 涉及多表时，必须按上方关系定义给出的关联键 JOIN，禁止自行猜测关联键。\n"
        "- 只输出一条完整 HiveSQL，以分号结束，不要任何解释文字。\n"
    )
    ctx = state.get("conversation_context")
    if ctx:
        prompt += f"对话上下文（常驻约束，必须遵守）：{ctx}\n"
    history = state.get("history") or []
    if history:
        prompt += "历史对话（用户之前的提问与已生成的 SQL，供继续完善参考，仅作上下文不要重复回答）：\n"
        for h in history[-6:]:
            role = "用户" if h.get("role") == "user" else "助手"
            prompt += f"{role}：{h.get('content', '')}\n"
            if h.get("sql"):
                prompt += f"助手已生成SQL：{h['sql']}\n"
    return prompt


def _parse_business_month(query: str, state: AgentState) -> str:
    """从问题中解析业务账期（如 '2026年6月' / '6月'）→ YYYYMM；无则用推算 p_mon。"""
    m = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月", query)
    if m:
        return f"{m.group(1)}{int(m.group(2)):02d}"
    m = re.search(r"(\d{1,2})(?<!个)\s*月", query)
    if m:
        year = (state.get("system_time") or "")[:4] or str(datetime.now().year)
        return f"{year}{int(m.group(1)):02d}"
    return state.get("p_mon", "202606")


# ---------------------------------------------------------------------------
# 逻辑定义模板渲染（模板化定义：占位符 + 场景开关，避免账期/日期写死）
# ---------------------------------------------------------------------------

_SCENARIO_TAGS = {"A": "current_active", "B": "history_all", "C": "new_order"}


def render_logic_template(
    template: str,
    *,
    p_mon: str,
    p_day: str,
    scenario: str = "history_all",
) -> str:
    """展开逻辑定义模板：
    - 场景开关 {A:...}{B:...}{C:...} 按 scenario 保留（current_active/history_all/new_order）
    - 占位符按账期替换：{p_mon} {开始} {开始日期} {结束} {结束日期} {月末分区} {T-2}
    """
    if not template:
        return template

    # 先替换占位符（避免场景块内嵌套 {占位符} 干扰场景开关匹配），再处理场景开关
    try:
        year, month = int(p_mon[:4]), int(p_mon[4:6])
        last_day = calendar.monthrange(year, month)[1]
    except (ValueError, IndexError):
        year, month, last_day = 2026, 6, 30
    start_date = f"{year}-{month:02d}-01"
    end_date = f"{year}-{month:02d}-{last_day:02d}"
    placeholders = {
        "{p_mon}": p_mon,
        "{开始}": f"{start_date} 00:00:00",
        "{开始日期}": start_date,
        "{结束}": f"{end_date} 23:59:59",
        "{结束日期}": end_date,
        "{月末分区}": f"{p_mon}{last_day:02d}",
        "{T-2}": (p_day or "")[:8],
    }
    t = template
    for k, v in placeholders.items():
        t = t.replace(k, v)

    def _scene(m: re.Match) -> str:
        tag = m.group(1).strip().upper()
        return m.group(2) if _SCENARIO_TAGS.get(tag) == scenario else ""

    t = re.sub(r"\{([ABC]):\s*(.*?)\}", _scene, t, flags=re.DOTALL)
    # 清理残留的花括号（占位符已替换、场景块已展开后剩余的 {基块} 外层括号）
    t = re.sub(r"\{([^{}]*)\}", r"\1", t)
    return t


def _infer_scenario(query: str) -> str:
    """从需求文本推断场景：当前生效 / 时间段内全部 / 新增。"""
    q = query or ""
    if any(w in q for w in ("当前生效", "当前有效", "正在生效", "有效期内", "生效中")):
        return "current_active"
    if any(w in q for w in ("新增", "新订购", "新办理", "本月新增")):
        return "new_order"
    return "history_all"


def _render_logical_defs(ttl: dict[str, Any], state: AgentState) -> dict[str, str]:
    """渲染逻辑定义（模板展开）：占位符按账期替换、场景开关按需求推断。"""
    logdefs = ttl.get("logical_definitions", {}) or {}
    if not logdefs:
        return {}
    scenario = _infer_scenario(state.get("user_query", ""))
    p_mon = state.get("p_mon") or ""
    p_day = state.get("p_day") or ""
    return {
        k: render_logic_template(v, p_mon=p_mon, p_day=p_day, scenario=scenario)
        for k, v in logdefs.items()
    }


def _parse_silent_months(query: str) -> int:
    """解析沉默月数（如 '沉默3个月' / '沉默6个月'），默认 1 个月。"""
    m = re.search(r"沉默\s*(\d+)\s*个月?", query)
    return max(1, int(m.group(1))) if m else 1


def _pmon_range(mon: str, n: int) -> str:
    """生成最近 n 个账期的 IN 列表（如 '202606','202605'）。"""
    year, month = int(mon[:4]), int(mon[4:6])
    parts = []
    for _ in range(n):
        parts.append(f"{year}{month:02d}")
        month -= 1
        if month == 0:
            year -= 1
            month = 12
    return ",".join(f"'{p}'" for p in parts)


def _mock_generate_sql(state: AgentState) -> str:
    """无有效 LLM 产出时的确定性兜底：按问题动态生成，字段取自本体映射（不硬编码过时字段）。"""
    query = state.get("user_query", "")
    ttl = state.get("ttl_def", {})
    first = next(iter(ttl.get("object_classes", {}).items()), (None, {}))
    _name, obj = first
    if not obj:
        return "SELECT *;"
    table = str(obj["table_name"])
    db = str(obj.get("db_prefix", ""))
    prefix = f"{db}." if db else ""
    mon = _parse_business_month(query, state)
    partition = obj.get("partition")
    attrs = obj.get("attributes", {})
    fields = [a["field"] for a in attrs.values() if a.get("field")]

    # 动态选字段：分区字段 + 前 2 个其他字段
    select_fields: list[str] = []
    if partition:
        select_fields.append(partition)
    for f in fields:
        if f != partition and len(select_fields) < 3:
            select_fields.append(f)
    select_cols = ", ".join(select_fields) if select_fields else "*"

    # 优先用 LLM 推导的口径条件（rule_condition）：LLM SQL 失败回退时不丢口径
    derived = state.get("derived_rules") or {}
    rule_cond = (derived.get("rule_condition") or "").strip()
    if rule_cond:
        if partition:
            where = f"WHERE {partition}='{mon}' AND ({rule_cond})"
        else:
            where = f"WHERE ({rule_cond})"
        return f"SELECT {select_cols} FROM {prefix}{table} {where};"

    if "沉默" in query:
        months = _parse_silent_months(query)
        # 按中文注释精确匹配沉默口径字段（已验证：通话次数=CALL_COUNTS、GPRS流量=GPRS_VOLUME）
        call_field = None
        gprs_field = None
        for comment, a in attrs.items():
            f = a.get("field") if isinstance(a, dict) else None
            if not f:
                continue
            if comment == "通话次数" and call_field is None:
                call_field = f
            elif "GPRS流量" in comment and gprs_field is None:
                gprs_field = f
        # 注释未命中时兜底：按字段名精确匹配（避免 CALL_COUNTS_ID / GPRS_COUNTS 等相似字段）
        if call_field is None:
            call_field = next((f for f in fields if f == "CALL_COUNTS"), None)
        if gprs_field is None:
            gprs_field = next((f for f in fields if f == "GPRS_VOLUME"), None)
        where = f"WHERE {partition} IN ({_pmon_range(mon, months)})" if partition else ""
        conds = []
        if call_field:
            conds.append(f"({call_field}=0 OR {call_field} IS NULL)")
        if gprs_field:
            conds.append(f"({gprs_field}=0 OR {gprs_field} IS NULL)")
        if conds:
            where += " AND " + " AND ".join(conds)
        return f"SELECT {select_cols} FROM {prefix}{table} {where};"
    # 本体暂未覆盖的业务：按业务账期返回用户（SQL 随账期变化）
    where_pmon = f"WHERE {partition}='{mon}'" if partition else ""
    return f"SELECT {select_cols} FROM {prefix}{table} {where_pmon};"


def _extract_sql(text: str) -> str:
    """从 LLM 响应中提取 SQL（支持 ```sql 代码块与纯文本）。"""
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text.strip()


def node_build_sql(state: AgentState) -> dict[str, Any]:
    """构建 SQL：LLM 优先，产出必须通过自检（语法+语义）才采用，否则回退确定性模板。

    flash 模型对长需求偶发空响应：空/异常时重试 1 次；自检失败不重试（避免浪费时间），直接回退。
    """
    llm = get_llm_client()
    if llm.api_key and llm.api_key != PLACEHOLDER_KEY:
        prompt = _build_system_prompt(state)
        query = state["user_query"]
        client = get_ontology_client()
        sql = ""
        raw = ""
        for attempt in range(2):
            try:
                raw = llm.generate_sql(prompt, query)
            except Exception as exc:
                logger.warning("LLM 调用异常(第%d次): %s", attempt + 1, exc)
                raw = ""
            sql = _extract_sql(raw)
            if not sql:
                logger.warning("LLM 返回空(第%d次)，重试", attempt + 1)
                continue
            syntax = client.validate_sql(sql)
            if not syntax["valid"]:
                # 语法失败多为超长输出被截断 → 重试一次
                logger.warning("LLM 语法自检未通过(第%d次): %s", attempt + 1, syntax.get("errors"))
                continue
            sem = client.validate_sql_semantics(sql, state.get("ttl_def"))
            if sem["valid"]:
                return {"sql": sql}
            # 语义失败（编造字段等）是逻辑问题，重试意义小 → 直接回退
            logger.warning("LLM 语义自检未通过: %s", sem.get("errors"))
            break
    sql = _mock_generate_sql(state)
    logger.info("回退确定性模板生成 SQL")
    return {"sql": sql}


# ---------------------------------------------------------------------------
# 节点 7a/7b：审计校验
# ---------------------------------------------------------------------------


def node_validate_syntax(state: AgentState) -> dict[str, Any]:
    client = get_ontology_client()
    result = client.validate_sql(state.get("sql", ""))
    return {"sql_valid": bool(result.get("valid")), "errors": result.get("errors", [])}


def node_validate_semantics(state: AgentState) -> dict[str, Any]:
    client = get_ontology_client()
    result = client.validate_sql_semantics(state.get("sql", ""), state.get("ttl_def"))
    return {"sql_valid": bool(result.get("valid")), "errors": result.get("errors", [])}


# ---------------------------------------------------------------------------
# fix 节点：受限修复（仅语法调整）
# ---------------------------------------------------------------------------


def node_fix_sql(state: AgentState) -> dict[str, Any]:
    sql = state.get("sql", "")
    fixed = sql
    if fixed.strip() and not fixed.strip().endswith(";"):
        fixed = fixed.rstrip() + ";"
    return {"sql": fixed, "retry_count": state.get("retry_count", 0) + 1}


# ---------------------------------------------------------------------------
# 节点 8：格式化输出 / 失败输出
# ---------------------------------------------------------------------------


def node_format_output(state: AgentState) -> dict[str, Any]:
    """格式化输出：推理逻辑基于真实中间产物动态生成（非模板文案）。"""
    sql = state.get("sql", "")
    query = state.get("user_query", "")
    ttl = state.get("ttl_def", {})
    objs = ttl.get("object_classes", {})
    logdefs = ttl.get("logical_definitions", {})
    p_mon = state.get("p_mon", "")

    # 业务账期：问题指定优先，否则推算兜底
    biz_mon = _parse_business_month(query, state)
    if biz_mon and biz_mon != p_mon:
        mon_desc = f"问题指定 {biz_mon}，按月分区 P_MON 过滤"
    else:
        mon_desc = f"问题未指定账期，按推算 {p_mon} 兜底"

    # 命中逻辑定义（问题文本包含定义名 → 按定义生成条件）
    hit_logdefs = [k for k in logdefs if k and k in query]

    # 涉及表（库前缀.表名）
    tables = [f"{v.get('db_prefix', '')}.{v['table_name']}" for v in objs.values()]

    # 审计校验结果（从 trace 提取）
    checks = [
        s.get("summary") or s["label"]
        for s in (state.get("trace") or [])
        if s["node"] in ("validate_syntax", "validate_semantics")
    ]

    lines = [
        f"- 系统时间：{state.get('system_time')}，推算分区 p_day={state.get('p_day')} / p_mon={p_mon}",
        f"- 业务账期：{mon_desc}",
    ]
    if hit_logdefs:
        lines.append(f"- 命中逻辑定义：{'、'.join(hit_logdefs)}（按其口径生成过滤条件）")
    derived = state.get("derived_rules")
    if derived and derived.get("business_rules"):
        lines.append(f"- 口径推导：{derived['business_rules']}")
    if "沉默" in query:
        lines.append(f"- 沉默口径：最近 {_parse_silent_months(query)} 个月无通话次数且无流量")
    if state.get("external_tables"):
        lines.append(f"- 外部表：{', '.join(state['external_tables'])}")
    lines.append(f"- 涉及表：{('、'.join(tables)) if tables else '无'}")
    lines.append(f"- 审计校验：{'、'.join(checks) if checks else '已执行'}")

    markdown = (
        "## 推理逻辑\n" + "\n".join(lines) + "\n\n"
        f"## sql代码\n\n{sql}\n\n"
        "## 输入表清单\n" + "\n".join(f"- {t}" for t in tables) + "\n"
    )
    return {
        "output": {
            "success": True,
            "markdown": markdown,
            "sql": sql,
            "p_day": state.get("p_day"),
            "p_mon": p_mon,
        }
    }


def node_format_failure(state: AgentState) -> dict[str, Any]:
    if state.get("irrelevant"):
        # 无关问题：输出友好提示（不带"生成失败"前缀）
        msg = (state.get("errors") or [IRRELEVANT_MESSAGE])[0]
        return {
            "output": {
                "success": False,
                "errors": [msg],
                "markdown": msg,
                "irrelevant": True,
            }
        }
    return {
        "output": {
            "success": False,
            "errors": state.get("errors", []),
            "retry_count": state.get("retry_count", 0),
        }
    }


# ---------------------------------------------------------------------------
# 条件边路由
# ---------------------------------------------------------------------------


def route_after_7a(state: AgentState) -> str:
    return "validate_semantics" if state.get("sql_valid") else "fix_sql"


def route_after_7b(state: AgentState) -> str:
    return "format_output" if state.get("sql_valid") else "fix_sql"


def route_after_fix(state: AgentState) -> str:
    return "validate_syntax" if state.get("retry_count", 0) < 3 else "format_failure"


# ---------------------------------------------------------------------------
# 图构建
# ---------------------------------------------------------------------------

# 节点 → 用户可读步骤名（全链路可视化）
_STEP_LABELS = {
    "get_ttl_definition": "检索本体定义",
    "parse_external_tables": "解析外部表",
    "get_attr_mapping": "获取属性映射",
    "transform_fields": "字段转换",
    "calc_dates": "推算分区",
    "derive_rules": "口径推导",
    "build_sql": "生成 SQL",
    "validate_syntax": "语法校验",
    "validate_semantics": "语义校验",
    "fix_sql": "修复重试",
    "format_output": "输出结果",
    "format_failure": "输出失败",
}


def _step_summary(node: str, out: dict[str, Any], state: AgentState) -> str:
    """按节点生成关键产出摘要（注入 trace 步骤，供前端展示）。"""
    try:
        if node == "get_ttl_definition":
            objs = list((out.get("ttl_def") or {}).get("object_classes", {}).keys())
            return f"选中表: {', '.join(objs) if objs else '无'}"
        if node == "parse_external_tables":
            return f"识别 {len(out.get('external_tables') or [])} 个外部表"
        if node == "get_attr_mapping":
            n = sum(len(v) for v in (out.get("attr_map") or {}).values() if isinstance(v, dict))
            return f"映射 {n} 个属性字段"
        if node == "transform_fields":
            return f"转换 {len(out.get('field_map') or {})} 个中文属性→物理字段"
        if node == "calc_dates":
            return f"p_day={out.get('p_day')}, p_mon={out.get('p_mon')}"
        if node == "derive_rules":
            rules = out.get("derived_rules")
            if rules and rules.get("business_rules"):
                return f"推导口径: {str(rules['business_rules'])[:60]}"
            return "复用已有逻辑定义或未推导"
        if node == "build_sql":
            sql = out.get("sql") or ""
            return f"SQL {len(sql)} 字符" + ("（LLM 生成）" if sql else "（兜底模板）")
        if node in ("validate_syntax", "validate_semantics"):
            if out.get("sql_valid"):
                return "通过"
            errs = out.get("errors") or []
            return f"未通过: {'; '.join(errs)[:80]}" if errs else "未通过"
        if node == "fix_sql":
            return f"第 {out.get('retry_count', 0)} 次修复"
    except Exception:
        return ""
    return ""


def _traced(node: str, fn: Callable[[AgentState], dict[str, Any]], on_step: Callable[[dict[str, Any]], None] | None):
    """节点包装器：自动记录步骤（名称/状态/耗时/摘要）并累计进 state.trace。"""
    def wrapped(state: AgentState) -> dict[str, Any]:
        start = time.time()
        try:
            out = fn(state)
            status = "success"
        except Exception as exc:
            out = {"errors": (state.get("errors") or []) + [f"{node}: {exc}"]}
            status = "error"
        step = {
            "node": node,
            "label": _STEP_LABELS.get(node, node),
            "status": status,
            "duration_ms": int((time.time() - start) * 1000),
            "summary": _step_summary(node, out, state),
        }
        out["trace"] = (state.get("trace") or []) + [step]
        if on_step is not None:
            try:
                on_step(step)
            except Exception:
                logger.warning("trace 回调异常", exc_info=True)
        return out
    return wrapped


def build_graph(on_step: Callable[[dict[str, Any]], None] | None = None):
    g = StateGraph(AgentState)
    g.add_node("get_ttl_definition", _traced("get_ttl_definition", node_get_ttl_definition, on_step))
    g.add_node("parse_external_tables", _traced("parse_external_tables", node_parse_external_tables, on_step))
    g.add_node("get_attr_mapping", _traced("get_attr_mapping", node_get_attr_mapping, on_step))
    g.add_node("transform_fields", _traced("transform_fields", node_transform_fields, on_step))
    g.add_node("calc_dates", _traced("calc_dates", node_calc_dates, on_step))
    g.add_node("derive_rules", _traced("derive_rules", node_derive_rules, on_step))
    g.add_node("build_sql", _traced("build_sql", node_build_sql, on_step))
    g.add_node("validate_syntax", _traced("validate_syntax", node_validate_syntax, on_step))
    g.add_node("validate_semantics", _traced("validate_semantics", node_validate_semantics, on_step))
    g.add_node("fix_sql", _traced("fix_sql", node_fix_sql, on_step))
    g.add_node("format_output", _traced("format_output", node_format_output, on_step))
    g.add_node("format_failure", _traced("format_failure", node_format_failure, on_step))

    g.add_edge(START, "get_ttl_definition")
    g.add_conditional_edges(
        "get_ttl_definition",
        route_after_ttl,
        {
            "parse_external_tables": "parse_external_tables",
            "format_failure": "format_failure",
        },
    )
    g.add_edge("parse_external_tables", "get_attr_mapping")
    g.add_edge("get_attr_mapping", "transform_fields")
    g.add_edge("transform_fields", "calc_dates")
    g.add_edge("calc_dates", "derive_rules")
    g.add_edge("derive_rules", "build_sql")
    g.add_edge("build_sql", "validate_syntax")

    g.add_conditional_edges(
        "validate_syntax",
        route_after_7a,
        {"validate_semantics": "validate_semantics", "fix_sql": "fix_sql"},
    )
    g.add_conditional_edges(
        "validate_semantics",
        route_after_7b,
        {"format_output": "format_output", "fix_sql": "fix_sql"},
    )
    g.add_conditional_edges(
        "fix_sql",
        route_after_fix,
        {"validate_syntax": "validate_syntax", "format_failure": "format_failure"},
    )

    g.add_edge("format_output", END)
    g.add_edge("format_failure", END)
    return g.compile()


graph = build_graph()


def run_agent(
    user_query: str,
    additional_context: str | None = None,
    ontology_id: str | None = None,
    system_time: str | None = None,
    history: list[dict[str, str]] | None = None,
    conversation_context: str | None = None,
    on_step: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """执行 8 步编排，返回格式化输出（output 内附 trace 生成链路步骤）。

    history：历史消息列表 [{"role": "user|assistant", "content": str, "sql": str|None}]，
    作为上下文注入 system prompt，供多轮继续完善 SQL。
    conversation_context：对话级常驻约束/补充信息。
    on_step：每个节点完成时的回调（实时链路可视化用，收到 {node,label,status,duration_ms,summary}）。
    """
    g = build_graph(on_step) if on_step else graph
    result = g.invoke(
        {
            "user_query": user_query,
            "additional_context": additional_context,
            "ontology_id": ontology_id,
            "system_time": system_time,
            "history": history or [],
            "conversation_context": conversation_context,
            "retry_count": 0,
            "errors": [],
        }
    )
    output = result.get("output", {})
    if isinstance(output, dict):
        output["trace"] = result.get("trace", [])
    return output
