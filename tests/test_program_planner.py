from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from agent.program_planner import AdaptiveProgramPlanner
from ontology_core.program_models import (
    DraftProgramStep,
    DraftSqlProgramPlan,
    IntentSpec,
    ProgramDiagnostic,
    ProgramStep,
    ProgramStepKind,
    ResultShapeSpec,
    SqlProgramPlan,
    StepSourceBinding,
    TimeIntentSpec,
)
from ontology_core.program_validation import ProgramValidationResult
from ontology_core.query_plan import BoundObject, BoundProperty, QueryPlan
from ontology_core.semantic_models import Concept, DataSource, PhysicalMapping, Property
from tools.llm_client import LLMClient, StructuredPlanningError


def _draft(*, purpose: str = "生成客户结果") -> DraftSqlProgramPlan:
    return DraftSqlProgramPlan(
        intent=IntentSpec(
            normalized_request="生成客户结果",
            business_concepts=("Customer",),
            requested_properties=("CustomerId",),
            time_intent=TimeIntentSpec(requires_default=True),
            result_shape=ResultShapeSpec(),
        ),
        steps=(
            DraftProgramStep(
                step_id="result",
                kind=ProgramStepKind.RESULT,
                purpose=purpose,
                source_objects=("Customer",),
                source_bindings=(StepSourceBinding(object_ref="Customer"),),
                requested_properties=("CustomerId",),
            ),
        ),
    )


def _bound_plan(*, repair_count: int = 0) -> SqlProgramPlan:
    draft = _draft()
    concept = Concept(
        uri="https://example.invalid/Customer",
        short_name="Customer",
        label="客户",
        labels=(),
    )
    property_ = Property(
        uri="https://example.invalid/CustomerId",
        short_name="CustomerId",
        label="客户编号",
        labels=(),
        concept_uri=concept.uri,
        datatype_uri="http://www.w3.org/2001/XMLSchema#string",
    )
    source = DataSource(
        uri="https://example.invalid/Hive",
        short_name="Hive",
        label="Hive",
        labels=(),
        platform_type="hive",
        dialect="hive",
    )
    object_ = BoundObject(
        alias="t0",
        semantic=concept,
        binding=PhysicalMapping(
            uri="https://example.invalid/CustomerTable",
            short_name="CustomerTable",
            label="客户表",
            labels=(),
            semantic_element_uri=concept.uri,
            data_source_uri=source.uri,
            physical_namespace="dm",
            object_name="customer",
        ),
    )
    field = BoundProperty(
        semantic=property_,
        binding=PhysicalMapping(
            uri="https://example.invalid/CustomerIdField",
            short_name="CustomerIdField",
            label="客户编号字段",
            labels=(),
            semantic_element_uri=property_.uri,
            data_source_uri=source.uri,
            field_name="customer_id",
        ),
        object_alias="t0",
    )
    query_plan = QueryPlan(
        concepts=(concept,),
        data_source=source,
        objects=(object_,),
        selections=(field,),
        property_bindings=(field,),
    )
    return SqlProgramPlan(
        program_id="a1b2c3d4e5f6",
        package_id="example.program",
        package_version="1.0.0",
        package_sha256="a" * 64,
        data_source_id="https://example.invalid/Hive",
        dialect="hive",
        intent=draft.intent,
        steps=(
            ProgramStep(
                step_id="result",
                kind=ProgramStepKind.RESULT,
                purpose="生成客户结果",
                source_objects=("Customer",),
                source_bindings=(StepSourceBinding(object_ref="Customer"),),
                query_plan=query_plan,
            ),
        ),
        result_step_id="result",
        diagnostics=(),
        repair_count=repair_count,
    )


class _Repository:
    def current(self):
        concept = SimpleNamespace(
            uri="https://example.invalid/Customer",
            short_name="Customer",
            label="客户",
        )
        mapping = SimpleNamespace(object_name="physical_customer_secret")
        catalog = SimpleNamespace(
            concepts=(concept,),
            properties=(),
            relations=(),
            rules=(),
            mappings=(mapping,),
        )
        return SimpleNamespace(catalog=catalog)


class _Client:
    def __init__(
        self,
        initial: DraftSqlProgramPlan | Exception,
        repaired: DraftSqlProgramPlan | Exception | None = None,
    ) -> None:
        self.initial = initial
        self.repaired = repaired
        self.plan_calls: list[tuple[str, str]] = []
        self.repair_calls: list[tuple[str, DraftSqlProgramPlan, tuple, str | None]] = []

    def plan_sql_program(self, *, system_prompt: str, user_query: str):
        self.plan_calls.append((system_prompt, user_query))
        if isinstance(self.initial, Exception):
            raise self.initial
        return self.initial

    def repair_sql_program(
        self,
        *,
        original_query: str,
        draft,
        diagnostics,
        conversation_context: str | None = None,
    ):
        self.repair_calls.append(
            (original_query, draft, tuple(diagnostics), conversation_context)
        )
        if isinstance(self.repaired, Exception):
            raise self.repaired
        assert self.repaired is not None
        return self.repaired


class _Binder:
    def __init__(self, *results: ProgramValidationResult) -> None:
        self.results = list(results)
        self.calls: list[DraftSqlProgramPlan] = []

    def bind(self, draft, **kwargs):
        self.calls.append(draft)
        return self.results.pop(0)


def _planner(client: _Client, binder: _Binder) -> AdaptiveProgramPlanner:
    return AdaptiveProgramPlanner(client=client, repository=_Repository(), binder=binder)


def _plan(planner: AdaptiveProgramPlanner):
    return planner.plan(
        "生成客户结果",
        program_id="a1b2c3d4e5f6",
        system_time=datetime(2026, 8, 24, tzinfo=UTC),
    )


def test_planning_and_repair_receive_the_same_conversation_context() -> None:
    diagnostic = ProgramDiagnostic(
        code="repairable_reference",
        message="步骤引用未知步骤",
    )
    client = _Client(_draft(), _draft(purpose="修复后的结果"))
    binder = _Binder(
        ProgramValidationResult(diagnostics=(diagnostic,), should_repair=True),
        ProgramValidationResult(plan=_bound_plan()),
    )

    outcome = _planner(client, binder).plan(
        "生成客户结果",
        program_id="a1b2c3d4e5f6",
        system_time=datetime(2026, 8, 24, tzinfo=UTC),
        conversation_context="用户已确认仅查询浙江客户",
    )

    assert outcome.status == "ready"
    assert "用户已确认仅查询浙江客户" in client.plan_calls[0][0]
    assert client.repair_calls[0][3] == "用户已确认仅查询浙江客户"


def test_valid_first_draft_uses_one_call_and_sql_free_prompt() -> None:
    client = _Client(_draft())
    binder = _Binder(ProgramValidationResult(plan=_bound_plan()))

    outcome = _plan(_planner(client, binder))

    assert outcome.status == "ready"
    assert outcome.llm_call_count == 1
    assert len(client.repair_calls) == 0
    prompt = client.plan_calls[0][0]
    assert "禁止输出 SQL" in prompt
    assert "禁止输出目标表名" in prompt
    assert "physical_customer_secret" not in prompt


def test_repairable_reference_uses_exactly_one_repair_call() -> None:
    diagnostic = ProgramDiagnostic(
        code="repairable_reference",
        message="步骤引用未知步骤",
        step_id="result",
        candidates=("base",),
    )
    client = _Client(_draft(), _draft(purpose="修复后的结果"))
    binder = _Binder(
        ProgramValidationResult(
            diagnostics=(diagnostic,),
            should_repair=True,
        ),
        ProgramValidationResult(plan=_bound_plan()),
    )

    outcome = _plan(_planner(client, binder))

    assert outcome.status == "ready"
    assert outcome.llm_call_count == 2
    assert outcome.plan is not None
    assert outcome.plan.repair_count == 1
    assert len(client.repair_calls) == 1
    assert client.repair_calls[0][2] == (diagnostic,)


def test_failed_repair_stops_after_two_calls() -> None:
    repairable = ProgramValidationResult(
        diagnostics=(
            ProgramDiagnostic(
                code="repairable_reference",
                message="步骤引用无效",
            ),
        ),
        should_repair=True,
    )
    client = _Client(_draft(), _draft(purpose="仍然无效"))
    binder = _Binder(repairable, repairable)

    outcome = _plan(_planner(client, binder))

    assert outcome.status == "failed"
    assert outcome.llm_call_count == 2
    assert len(client.plan_calls) == 1
    assert len(client.repair_calls) == 1


def test_business_ambiguity_requests_clarification_without_repair() -> None:
    ambiguous = ProgramValidationResult(
        diagnostics=(
            ProgramDiagnostic(
                code="ambiguous_business_term",
                message="业务概念需要确认",
            ),
        ),
        should_clarify=True,
    )
    client = _Client(_draft())
    binder = _Binder(ambiguous)

    outcome = _plan(_planner(client, binder))

    assert outcome.status == "clarification_required"
    assert outcome.llm_call_count == 1
    assert len(client.repair_calls) == 0


def test_malformed_structured_output_is_sanitized_before_binding() -> None:
    client = _Client(
        StructuredPlanningError(
            "结构化计划字段约束不满足",
            category="schema_validation",
        )
    )
    binder = _Binder()

    outcome = _plan(_planner(client, binder))

    assert outcome.status == "failed"
    assert outcome.llm_call_count == 1
    assert binder.calls == []
    assert outcome.diagnostics[0].code == "structured_plan_schema_invalid"
    assert "字段约束" in outcome.diagnostics[0].message


def test_llm_client_does_not_expose_malformed_model_output() -> None:
    class _RawClient(LLMClient):
        def __init__(self) -> None:
            pass

        def _generate(
            self,
            system_prompt: str,
            user_query: str,
            *,
            json_output: bool = False,
        ) -> str:
            return '{"secret_business_value": "do-not-expose"'

    with pytest.raises(StructuredPlanningError) as caught:
        _RawClient().plan_sql_program(system_prompt="plan", user_query="request")

    assert "do-not-expose" not in str(caught.value)
    assert caught.value.category == "invalid_json"


def test_llm_client_sanitizes_provider_failure() -> None:
    class _FailingClient(LLMClient):
        def __init__(self) -> None:
            pass

        def _generate(self, system_prompt: str, user_query: str) -> str:
            raise RuntimeError("provider-response-secret")

    with pytest.raises(StructuredPlanningError) as caught:
        _FailingClient().plan_sql_program(system_prompt="plan", user_query="request")

    assert "provider-response-secret" not in str(caught.value)
