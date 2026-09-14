"""Agent 编排单元测试：8 步流程 + 审计循环（含受限修复与 retry 上限）。

LLM 统一由 tests/conftest.py 的 harness fixture 强制为确定性模板路径。
"""

from __future__ import annotations

from agent.orchestrator import (
    node_fix_sql,
    node_format_failure,
    route_after_7a,
    route_after_7b,
    route_after_fix,
    run_agent,
    _run_legacy_agent as run_legacy_agent,
)
from tools.ontology_client import MockOntologyClient


def test_assembled_context_is_shared_by_rules_and_sql_prompts() -> None:
    from agent.orchestrator import _build_rules_prompt, _build_system_prompt

    state = {
        "user_query": "查询客户",
        "ttl_def": {"object_classes": {}, "logical_definitions": {}},
        "field_map": {},
        "assembled_context": "已确认业务口径：仅查询正常在网客户",
        "p_day": "20260822",
        "p_mon": "202607",
    }

    assert "已确认业务口径：仅查询正常在网客户" in _build_rules_prompt(state)
    assert "已确认业务口径：仅查询正常在网客户" in _build_system_prompt(state)


def test_explicit_legacy_mode_selects_only_legacy_graph(monkeypatch):
    import agent.orchestrator as orchestrator

    monkeypatch.setattr(orchestrator.settings, "sql_pipeline", "legacy")
    expected = {"success": True, "sql": "SELECT 1;"}
    calls = []

    def legacy(*args, **kwargs):
        calls.append((args, kwargs))
        return expected

    monkeypatch.setattr(orchestrator, "_run_legacy_agent", legacy)
    monkeypatch.setattr(
        orchestrator,
        "generate_program",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("canonical called")),
    )
    assert orchestrator.run_agent("查询客户", system_time="2026-08-24") == expected
    assert len(calls) == 1


def test_run_agent_uses_native_program_as_default_without_legacy_graph(monkeypatch) -> None:
    import agent.orchestrator as orchestrator
    from agent.program_generation import (
        ProgramGenerationMode,
        ProgramGenerationResult,
    )
    from ontology_core.program_compiler import HiveProgramCompiler
    from tests.test_program_planner import _bound_plan

    plan = _bound_plan()
    program = HiveProgramCompiler().compile(plan)
    calls: list[tuple[str, str]] = []

    def fake_generate(
        query,
        *,
        request_id,
        system_time,
    ):
        calls.append((query, request_id))
        return ProgramGenerationResult(
            sql=program.sql,
            program=program,
            plan=plan,
            intent=plan.intent,
            mode=ProgramGenerationMode.PROGRAM,
            diagnostics=(),
        )

    monkeypatch.setattr(orchestrator, "generate_program", fake_generate)
    monkeypatch.setattr(
        orchestrator,
        "build_graph",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy graph called")),
    )

    output = orchestrator.run_agent(
        "生成客户结果",
        request_id="message-001",
        system_time="2026-08-24",
    )

    assert output["success"] is True
    assert output["sql"] == program.sql
    assert output["generation_mode"] == "program"
    assert output["program_id"] == plan.program_id
    assert output["intent"] == plan.intent.model_dump(mode="json")
    assert output["program_plan"]["package_sha256"] == "a" * 64
    assert output["program_steps"][0]["target_table"] == program.result_table
    assert output["temporal_evidence"] == []
    assert output["trace"][0]["node"] == "program_generation"
    assert calls == [("生成客户结果", "message-001")]


def test_run_agent_exposes_inferred_evidence_without_running_shadow(monkeypatch) -> None:
    import agent.orchestrator as orchestrator
    from agent.program_generation import ProgramGenerationMode, ProgramGenerationResult
    from ontology_core.relational_compiler import HiveRelationalCompiler
    from ontology_core.inference_to_relational import InferenceRelationalAdapter
    from tests.ontology_core.test_inference_to_relational import _graph
    from tests.ontology_core.test_inference_compiler import _object, _plan

    plan = _plan(_object("Customer"))
    plan = InferenceRelationalAdapter().convert(plan, _graph(plan))
    program = HiveRelationalCompiler().compile(plan, program_id="a1b2c3d4e5f6")

    def fake_generate(query, **kwargs):
        return ProgramGenerationResult(
            sql=program.sql,
            program=program,
            plan=None,
            intent=None,
            mode=ProgramGenerationMode.INFERRED_PROGRAM,
            diagnostics=(),
            inferred_plan=plan,
        )

    monkeypatch.setattr(orchestrator, "generate_program", fake_generate)
    monkeypatch.setattr(
        __import__("agent.ontology_shadow", fromlist=["get_ontology_shadow_service"]),
        "get_ontology_shadow_service",
        lambda: (_ for _ in ()).throw(AssertionError("shadow must not run")),
    )

    output = orchestrator.run_agent(
        "查询客户手机号码",
        request_id="message-003",
        system_time="2026-08-24",
    )

    assert output["success"] is True
    assert output["generation_mode"] == "inferred_program"
    assert output["inference_evidence"]["overall_confidence"] == "medium"
    assert output["package"]["sha256"] == "a" * 64
    assert "未经本体确认" in output["markdown"]
    assert "ontology_shadow" not in output


def test_run_agent_does_not_fallback_when_clarification_is_required(monkeypatch) -> None:
    import agent.orchestrator as orchestrator
    from agent.program_generation import (
        ProgramGenerationMode,
        ProgramGenerationResult,
    )
    from ontology_core.program_models import ProgramDiagnostic

    diagnostic = ProgramDiagnostic(
        code="ambiguous_business_term",
        message="请确认客户口径",
    )

    def fake_generate(
        query,
        *,
        request_id,
        system_time,
    ):
        return ProgramGenerationResult(
            sql=None,
            program=None,
            plan=None,
            intent=None,
            mode=ProgramGenerationMode.CLARIFICATION_REQUIRED,
            diagnostics=(diagnostic,),
            clarification="请确认客户口径",
        )

    monkeypatch.setattr(orchestrator, "generate_program", fake_generate)

    output = orchestrator.run_agent(
        "生成客户结果",
        request_id="message-002",
        system_time="2026-08-24",
    )

    assert output["success"] is False
    assert output.get("sql") is None
    assert output["generation_mode"] == "clarification_required"
    assert output["clarification"] == "请确认客户口径"


def test_canonical_failure_does_not_start_legacy_graph(monkeypatch):
    import agent.orchestrator as orchestrator
    from agent.program_generation import ProgramGenerationMode, ProgramGenerationResult
    from ontology_core.program_models import ProgramDiagnostic

    diagnostic = ProgramDiagnostic(
        code="inferred_plan_provider_unavailable", message="模型服务暂不可用"
    )
    monkeypatch.setattr(
        orchestrator,
        "generate_program",
        lambda *a, **kw: ProgramGenerationResult(
            sql=None,
            program=None,
            plan=None,
            intent=None,
            mode=ProgramGenerationMode.UNSUPPORTED,
            diagnostics=(diagnostic,),
            missing_information=("原始信息",),
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "_run_legacy_agent",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("legacy called")),
    )
    output = orchestrator.run_agent("查询客户")
    assert output["success"] is False
    assert output["diagnostics"] == [diagnostic.model_dump(mode="json")]
    assert output["missing_information"] == ["原始信息"]
    assert len(output["trace"]) == 1


def test_irrelevant_question_short_circuits(monkeypatch) -> None:
    """无关问题：检索器返回 irrelevant → 编排短路输出友好提示，不生成 SQL。"""

    class _FakeClient:
        def get_ontology_definition(self, *a, **k):
            return {
                "object_classes": {},
                "irrelevant": True,
                "message": "您好！我是本体取数助手。您的问题与取数业务无关。",
            }

    monkeypatch.setattr("agent.orchestrator.get_ontology_client", lambda: _FakeClient())
    out = run_legacy_agent("今天天气怎么样")
    assert out["success"] is False
    assert out.get("sql") is None
    assert "与取数业务无关" in out["markdown"]
    assert out.get("irrelevant") is True


def test_derive_rules_parses_json(monkeypatch) -> None:
    """口径推导：LLM 返回 JSON → 解析为 derived_rules；命中逻辑定义/无 Key 时跳过。"""
    import agent.orchestrator as orch

    class _FakeLLM:
        api_key = "test"

        def generate_sql(self, prompt, query):
            return (
                '{"business_rules": "沉默=无通话次数且无GPRS流量", '
                '"rule_fields": ["CALL_COUNTS", "GPRS_VOLUME"], '
                '"rule_condition": "(CALL_COUNTS=0 OR CALL_COUNTS IS NULL) AND (GPRS_VOLUME=0 OR GPRS_VOLUME IS NULL)"}'
            )

    monkeypatch.setattr(orch, "get_llm_client", lambda: _FakeLLM())
    ttl = {"object_classes": {}, "logical_definitions": {}}
    out = orch.node_derive_rules({"user_query": "查询5G用户发展", "ttl_def": ttl})
    assert out["derived_rules"]["rule_fields"] == ["CALL_COUNTS", "GPRS_VOLUME"]
    assert "无通话次数" in out["derived_rules"]["business_rules"]

    # 命中已有逻辑定义时仍调 LLM（由 LLM 判断是否全部覆盖）；返回空 JSON → 不推导
    class _FakeLLMEmpty:
        api_key = "test"

        def generate_sql(self, prompt, query):
            return '{"business_rules": "", "rule_fields": [], "rule_condition": ""}'

    monkeypatch.setattr(orch, "get_llm_client", lambda: _FakeLLMEmpty())
    ttl2 = {"object_classes": {}, "logical_definitions": {"沉默用户": "xx"}}
    out2 = orch.node_derive_rules({"user_query": "查询6月沉默用户", "ttl_def": ttl2})
    assert out2["derived_rules"] is None

    # 无 API Key → 跳过
    monkeypatch.setattr(
        orch,
        "get_llm_client",
        lambda: type("X", (), {"api_key": "", "generate_sql": lambda *a: "{}"})(),
    )
    out3 = orch.node_derive_rules({"user_query": "查询5G用户", "ttl_def": ttl})
    assert out3["derived_rules"] is None


def test_derive_rules_injected_into_prompt() -> None:
    """口径推导注入生成 SQL 的 prompt（严格按口径生成）。"""
    from agent.orchestrator import _build_system_prompt

    state = {
        "user_query": "查询5G用户",
        "ttl_def": {
            "object_classes": {
                "D_X": {"table_name": "D_X", "db_prefix": "bddwd_hive_db", "attributes": {}}
            },
            "logical_definitions": {},
        },
        "derived_rules": {
            "business_rules": "5G用户=有GPRS流量",
            "rule_fields": ["GPRS_VOLUME"],
            "rule_condition": "GPRS_VOLUME>0",
        },
    }
    prompt = _build_system_prompt(state)
    assert "口径推导（本次需求由模型推导，必须严格遵守）：5G用户=有GPRS流量" in prompt
    assert "口径涉及字段：['GPRS_VOLUME']" in prompt


def test_mock_template_uses_rule_condition() -> None:
    """回退模板优先使用推导口径条件（rule_condition），不丢口径。"""
    from agent.orchestrator import _mock_generate_sql

    state = {
        "user_query": "查询5G用户",
        "ttl_def": {
            "object_classes": {
                "D_BBZX_DW_PRODUCT_M": {
                    "table_name": "D_BBZX_DW_PRODUCT_M",
                    "db_prefix": "bddwd_hive_db",
                    "partition": "P_MON",
                    "attributes": {
                        "通话次数": {"field": "CALL_COUNTS"},
                        "GPRS流量": {"field": "GPRS_VOLUME"},
                        "用户号码": {"field": "SUBS_NUMBER"},
                    },
                }
            }
        },
        "derived_rules": {
            "business_rules": "5G用户=有GPRS流量",
            "rule_fields": ["GPRS_VOLUME"],
            "rule_condition": "GPRS_VOLUME>0",
        },
    }
    sql = _mock_generate_sql(state)
    assert "GPRS_VOLUME>0" in sql
    assert "P_MON='202606'" in sql  # 分区保留


def test_normal_flow_success() -> None:
    """正常流程：生成 SQL 且通过语法+语义审计。"""
    out = run_legacy_agent(
        "查询6月沉默用户",
        system_time="2026-08-14",
    )
    assert out["success"] is True
    sql = out["sql"]
    # 零幻觉：仅物理字段名
    assert "SUBS_NUMBER" in sql and "CALL_COUNTS" in sql
    # 业务账期解析：问题中的"6月"→ 202606（而非推算的 p_mon=202607）
    assert "P_MON IN ('202606')" in sql
    # 表名映射
    assert "bddwd_hive_db.D_BBZX_DW_PRODUCT_M" in sql
    # 分号结束
    assert sql.strip().endswith(";")
    # 日期推算（state 层仍为推算值）
    assert out["p_mon"] == "202607"
    assert out["p_day"] == "20260812"


def test_mock_template_varies_by_query() -> None:
    """不同问题应生成不同 SQL（模板按业务/账期/月数动态变化）。"""
    a = run_legacy_agent(
        "查询6月沉默用户",
        system_time="2026-08-14",
    )["sql"]
    b = run_legacy_agent(
        "查询5月沉默用户",
        system_time="2026-08-14",
    )["sql"]
    c = run_legacy_agent(
        "查询沉默6个月的用户",
        system_time="2026-08-14",
    )["sql"]
    d = run_legacy_agent(
        "查询4月用户清单",
        system_time="2026-08-14",
    )["sql"]
    assert a != b, "不同账期应生成不同 SQL"
    assert "P_MON IN ('202606')" in a
    assert "P_MON IN ('202605')" in b
    # 沉默6个月：无业务账期 → 从推算账期(202607)往前推 6 个月
    assert "P_MON IN ('202607','202606','202605','202604','202603','202602')" in c
    assert "P_MON='202604'" in d


def test_date_calculation_month_boundary() -> None:
    """日期推算：8 月初 → p_mon 回退 7 月，p_day 跨月。"""
    out = run_legacy_agent(
        "查询沉默用户",
        system_time="2026-08-01",
    )
    assert out["p_day"] == "20260730"
    assert out["p_mon"] == "202607"


def test_syntax_validation_and_fix() -> None:
    """语法校验失败 → fix 受限修复（补分号）→ 重跑通过。"""
    client = MockOntologyClient()
    bad_sql = "SELECT SUBS_NUMBER FROM bddwd_hive_db.D_BBZX_DW_PRODUCT_M WHERE P_MON='202607'"
    result = client.validate_sql(bad_sql)
    assert result["valid"] is False

    fixed = node_fix_sql({"sql": bad_sql, "retry_count": 0})
    assert fixed["sql"].strip().endswith(";")
    assert fixed["retry_count"] == 1
    assert client.validate_sql(fixed["sql"])["valid"] is True


def test_semantics_validation() -> None:
    """语义校验：合法 SQL 通过，含未知字段则失败。"""
    client = MockOntologyClient()
    ok_sql = (
        "SELECT SUBS_NUMBER, CALL_COUNTS, GPRS_VOLUME "
        "FROM bddwd_hive_db.D_BBZX_DW_PRODUCT_M WHERE P_MON='202607';"
    )
    assert client.validate_sql_semantics(ok_sql)["valid"] is True

    bad_sql = "SELECT NOT_EXIST_FIELD FROM bddwd_hive_db.D_BBZX_DW_PRODUCT_M WHERE P_MON='202607';"
    assert client.validate_sql_semantics(bad_sql)["valid"] is False


def test_conditional_routing() -> None:
    """条件边路由：valid=true 前进，valid=false 进 fix，retry 上限终止。"""
    assert route_after_7a({"sql_valid": True}) == "validate_semantics"
    assert route_after_7a({"sql_valid": False}) == "fix_sql"
    assert route_after_7b({"sql_valid": True}) == "format_output"
    assert route_after_7b({"sql_valid": False}) == "fix_sql"
    assert route_after_fix({"retry_count": 2}) == "validate_syntax"
    assert route_after_fix({"retry_count": 3}) == "format_failure"


def test_failure_output() -> None:
    """retry≥3 终止：输出失败结果。"""
    out = node_format_failure({"errors": ["未知字段"], "retry_count": 3})
    assert out["output"]["success"] is False
    assert out["output"]["retry_count"] == 3
    assert out["output"]["errors"] == ["未知字段"]


def test_logic_template_rendering() -> None:
    """逻辑定义模板：占位符按账期替换 + 场景开关 + 花括号清理。"""
    from agent.orchestrator import _infer_scenario, render_logic_template

    cond = (
        "{OFFER_ID='610000149732' AND P_DAY='{月末分区}'}"
        "{B: AND EFFECTIVE_DATE<='{结束}' AND EXPIRE_DATE>'{开始}'}"
        "{C: AND CREATE_DATE>='{开始}' AND CREATE_DATE<='{结束}'}"
    )
    # history_all：保留 B 块，删除 C 块
    t = render_logic_template(cond, p_mon="202606", p_day="20260816", scenario="history_all")
    assert "OFFER_ID='610000149732' AND P_DAY='20260630'" in t
    assert "EFFECTIVE_DATE<='2026-06-30 23:59:59' AND EXPIRE_DATE>'2026-06-01 00:00:00'" in t
    assert "CREATE_DATE" not in t
    assert "{" not in t and "}" not in t  # 无残留花括号
    # current_active：只保留基块
    t2 = render_logic_template(cond, p_mon="202606", p_day="20260816", scenario="current_active")
    assert "OFFER_ID='610000149732' AND P_DAY='20260630'" in t2
    assert "EFFECTIVE_DATE" not in t2 and "CREATE_DATE" not in t2
    # new_order：保留 C 块
    t3 = render_logic_template(cond, p_mon="202606", p_day="20260816", scenario="new_order")
    assert "CREATE_DATE>='2026-06-01 00:00:00' AND CREATE_DATE<='2026-06-30 23:59:59'" in t3
    assert "EFFECTIVE_DATE" not in t3
    # 纯占位符定义（兼容）：{p_mon} 替换
    t4 = render_logic_template(
        "USERSTATUS_ID='1' AND P_MON='{p_mon}'", p_mon="202607", p_day="20260816"
    )
    assert "P_MON='202607'" in t4
    # 场景推断
    assert _infer_scenario("2026-06-01至2026-06-30 未订购") == "history_all"
    assert _infer_scenario("查询当前生效的免打扰用户") == "current_active"
    assert _infer_scenario("统计6月新订购免打扰") == "new_order"


def test_build_system_prompt_renders_logical_defs() -> None:
    """生成 SQL 的 prompt 中逻辑定义为模板渲染版（无占位符残留）。"""
    from agent.orchestrator import _build_system_prompt

    state = {
        "user_query": "查询2026年6月未订购来信免打扰的用户",
        "p_day": "20260816",
        "p_mon": "202607",
        "ttl_def": {
            "object_classes": {
                "D_CRM_INS_OFFER_D": {
                    "table_name": "D_CRM_INS_OFFER_D",
                    "db_prefix": "bddwd_hive_db",
                    "attributes": {},
                }
            },
            "logical_definitions": {
                "来信免打扰订购用户": "已订购来信免打扰的用户（条件：{OFFER_ID='610000149732' AND P_DAY='{月末分区}'}{B: AND EFFECTIVE_DATE<='{结束}' AND EXPIRE_DATE>'{开始}'}{C: AND CREATE_DATE>='{开始}' AND CREATE_DATE<='{结束}'}）"
            },
        },
    }
    prompt = _build_system_prompt(state)
    assert "OFFER_ID='610000149732' AND P_DAY='20260731'" in prompt  # 月末分区按 p_mon 展开
    assert "EFFECTIVE_DATE<='2026-07-31 23:59:59'" in prompt
    assert "{月末分区}" not in prompt  # 占位符无残留
