from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from agent.program_generation import (
    ProgramGenerationMode,
    ProgramGenerationService,
    derive_program_id,
)
from agent.program_planner import ProgramPlanningOutcome
from ontology_core.errors import PackageNotFoundError
from ontology_core.program_compiler import ProgramCompilerRegistry
from ontology_core.program_models import ProgramDiagnostic
from tests.test_program_planner import _bound_plan

SYSTEM_TIME = datetime(2026, 8, 24, tzinfo=UTC)


def _snapshot(plan, *, sha256: str | None = None):
    return SimpleNamespace(
        info=SimpleNamespace(
            package_id=plan.package_id,
            version=plan.package_version,
            sha256=sha256 or plan.package_sha256,
        )
    )


class _Runtime:
    def __init__(self, snapshot) -> None:
        self.value = snapshot
        self.calls = 0

    def snapshot(self):
        self.calls += 1
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class _Planner:
    def __init__(self, outcome: ProgramPlanningOutcome | Exception) -> None:
        self.outcome = outcome
        self.calls: list[tuple[str, str, datetime]] = []

    def plan(self, query: str, *, program_id: str, system_time: datetime):
        self.calls.append((query, program_id, system_time))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _service(planner: _Planner, runtime: _Runtime) -> ProgramGenerationService:
    return ProgramGenerationService(
        planner=planner,
        runtime=runtime,
        registry=ProgramCompilerRegistry.default(),
    )


def test_program_id_is_stable_fixed_length_and_does_not_expose_request_id() -> None:
    request_id = "conversation-user-customer-secret"

    first = derive_program_id(request_id)
    second = derive_program_id(request_id)

    assert first == second
    assert len(first) == 16
    assert request_id not in first


@pytest.mark.parametrize(
    ("repair_count", "expected_mode"),
    (
        (0, ProgramGenerationMode.PROGRAM),
        (1, ProgramGenerationMode.REPAIRED_PROGRAM),
    ),
)
def test_native_program_compiles_without_calling_legacy(
    repair_count: int,
    expected_mode: ProgramGenerationMode,
) -> None:
    plan = _bound_plan(repair_count=repair_count)
    planner = _Planner(
        ProgramPlanningOutcome(
            status="ready",
            plan=plan,
            llm_call_count=repair_count + 1,
        )
    )
    legacy_calls: list[str] = []

    result = _service(planner, _Runtime(_snapshot(plan))).generate(
        "生成客户结果",
        request_id="request-001",
        system_time=SYSTEM_TIME,
        legacy_sql_factory=lambda: legacy_calls.append("called") or "SELECT 1",
    )

    assert result.mode == expected_mode
    assert result.program is not None
    assert result.plan == plan
    assert result.sql == result.program.sql
    assert result.sql.count("DROP TABLE IF EXISTS") == 1
    assert result.sql.count("CREATE TABLE") == 1
    assert legacy_calls == []


def test_snapshot_change_aborts_before_compilation_or_fallback() -> None:
    plan = _bound_plan()
    planner = _Planner(
        ProgramPlanningOutcome(status="ready", plan=plan, llm_call_count=1)
    )
    legacy_calls: list[str] = []

    result = _service(
        planner,
        _Runtime(_snapshot(plan, sha256="b" * 64)),
    ).generate(
        "生成客户结果",
        request_id="request-001",
        system_time=SYSTEM_TIME,
        legacy_sql_factory=lambda: legacy_calls.append("called") or "SELECT 1",
    )

    assert result.mode == ProgramGenerationMode.UNAVAILABLE
    assert result.sql is None
    assert result.diagnostics[0].code == "ontology_snapshot_changed"
    assert legacy_calls == []


def test_safe_legacy_select_is_wrapped_in_one_system_named_ctas() -> None:
    planner = _Planner(PackageNotFoundError("当前没有有效本体快照"))
    runtime = _Runtime(PackageNotFoundError("当前没有有效本体快照"))

    result = _service(planner, runtime).generate(
        "生成客户结果",
        request_id="request-001",
        system_time=SYSTEM_TIME,
        legacy_sql_factory=lambda: 'SELECT "customer_id" FROM "dm"."customer";',
    )

    assert result.mode == ProgramGenerationMode.WRAPPED_LEGACY
    assert result.program is not None
    assert result.sql is not None
    assert result.sql.startswith("DROP TABLE IF EXISTS temp_oa_")
    assert "CREATE TABLE temp_oa_" in result.sql
    assert 'FROM "dm"."customer"' in result.sql
    assert result.sql.count("DROP TABLE IF EXISTS") == 1
    assert not result.sql.rstrip().endswith(
        f"DROP TABLE IF EXISTS {result.program.result_table};"
    )


@pytest.mark.parametrize(
    "legacy_sql",
    (
        "SELECT 1; SELECT 2;",
        "DROP TABLE dm.customer;",
        "INSERT INTO dm.customer SELECT 1;",
        "this is not sql",
    ),
)
def test_unsafe_legacy_output_is_never_wrapped(legacy_sql: str) -> None:
    planner = _Planner(PackageNotFoundError("本体不可用"))
    runtime = _Runtime(PackageNotFoundError("本体不可用"))

    result = _service(planner, runtime).generate(
        "生成结果",
        request_id="request-001",
        system_time=SYSTEM_TIME,
        legacy_sql_factory=lambda: legacy_sql,
    )

    assert result.mode == ProgramGenerationMode.UNAVAILABLE
    assert result.sql is None
    assert result.program is None
    assert result.diagnostics[-1].code == "unsafe_legacy_sql"


def test_clarification_never_calls_legacy_fallback() -> None:
    diagnostic = ProgramDiagnostic(
        code="ambiguous_business_term",
        message="客户口径需要确认",
    )
    planner = _Planner(
        ProgramPlanningOutcome(
            status="clarification_required",
            diagnostics=(diagnostic,),
            llm_call_count=1,
        )
    )
    legacy_calls: list[str] = []

    result = _service(planner, _Runtime(PackageNotFoundError("未使用"))).generate(
        "生成客户结果",
        request_id="request-001",
        system_time=SYSTEM_TIME,
        legacy_sql_factory=lambda: legacy_calls.append("called") or "SELECT 1",
    )

    assert result.mode == ProgramGenerationMode.CLARIFICATION_REQUIRED
    assert result.clarification == "客户口径需要确认"
    assert legacy_calls == []

