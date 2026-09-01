"""Generate safe ontology programs and wrap only verified legacy queries."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import lru_cache
from typing import Protocol

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from agent.ontology_shadow import get_ontology_runtime
from agent.program_planner import AdaptiveProgramPlanner, ProgramPlanningOutcome
from ontology_core.errors import OntologyCompileError, PackageNotFoundError
from ontology_core.program_compiler import (
    HiveProgramCompiler,
    ProgramCompilerRegistry,
    ProgramTableNamer,
)
from ontology_core.program_models import (
    CompiledProgram,
    CompiledStatement,
    IntentSpec,
    LineageEdge,
    ProgramCompilationEvidence,
    ProgramDiagnostic,
    ProgramStepKind,
    SqlProgramPlan,
)
from ontology_core.repository import OntologySnapshot
from tools.llm_client import get_llm_client

_PROGRAM_NAMESPACE = b"ontology-agent:program:v1\0"


class ProgramGenerationMode(StrEnum):
    PROGRAM = "program"
    REPAIRED_PROGRAM = "repaired_program"
    WRAPPED_LEGACY = "wrapped_legacy"
    CLARIFICATION_REQUIRED = "clarification_required"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ProgramGenerationResult:
    sql: str | None
    program: CompiledProgram | None
    plan: SqlProgramPlan | None
    intent: IntentSpec | None
    mode: ProgramGenerationMode
    diagnostics: tuple[ProgramDiagnostic, ...]
    clarification: str | None = None


class ProgramPlanner(Protocol):
    def plan(
        self,
        query: str,
        *,
        program_id: str,
        system_time: datetime,
    ) -> ProgramPlanningOutcome: ...


class SnapshotRuntime(Protocol):
    def snapshot(self) -> OntologySnapshot: ...


def derive_program_id(request_id: str) -> str:
    digest = hashlib.sha256(_PROGRAM_NAMESPACE + request_id.encode("utf-8")).hexdigest()
    return digest[:16]


class ProgramGenerationService:
    def __init__(
        self,
        *,
        planner: ProgramPlanner,
        runtime: SnapshotRuntime,
        registry: ProgramCompilerRegistry | None = None,
    ) -> None:
        self._planner = planner
        self._runtime = runtime
        self._registry = registry or ProgramCompilerRegistry.default()

    def generate(
        self,
        query: str,
        *,
        request_id: str,
        system_time: datetime,
        legacy_sql_factory: Callable[[], str] | None = None,
    ) -> ProgramGenerationResult:
        program_id = derive_program_id(request_id)
        try:
            outcome = self._planner.plan(
                query,
                program_id=program_id,
                system_time=system_time,
            )
        except PackageNotFoundError:
            return self._fallback(
                program_id,
                ProgramGenerationMode.UNAVAILABLE,
                (
                    ProgramDiagnostic(
                        code="ontology_unavailable",
                        message="当前没有可用的本体快照",
                    ),
                ),
                legacy_sql_factory,
            )
        if outcome.status == "clarification_required":
            clarification = (
                outcome.diagnostics[0].message
                if outcome.diagnostics
                else "业务语义需要进一步确认"
            )
            return ProgramGenerationResult(
                sql=None,
                program=None,
                plan=None,
                intent=None,
                mode=ProgramGenerationMode.CLARIFICATION_REQUIRED,
                diagnostics=outcome.diagnostics,
                clarification=clarification,
            )
        if outcome.plan is None:
            mode = self._failure_mode(outcome)
            return self._fallback(
                program_id,
                mode,
                outcome.diagnostics,
                legacy_sql_factory,
            )
        plan = outcome.plan
        try:
            live_snapshot = self._runtime.snapshot()
        except PackageNotFoundError:
            return self._fallback(
                program_id,
                ProgramGenerationMode.UNAVAILABLE,
                (
                    ProgramDiagnostic(
                        code="ontology_unavailable",
                        message="本体快照在编译前不可用",
                    ),
                ),
                legacy_sql_factory,
            )
        if not self._same_snapshot(plan, live_snapshot):
            return ProgramGenerationResult(
                sql=None,
                program=None,
                plan=plan,
                intent=plan.intent,
                mode=ProgramGenerationMode.UNAVAILABLE,
                diagnostics=(
                    ProgramDiagnostic(
                        code="ontology_snapshot_changed",
                        message="规划期间本体版本已变更，本次编译已中止",
                    ),
                ),
            )
        try:
            compiler = self._registry.get(plan.dialect)
            program = compiler.compile(plan)
        except OntologyCompileError:
            return self._fallback(
                program_id,
                ProgramGenerationMode.UNSUPPORTED,
                (
                    ProgramDiagnostic(
                        code="unsupported_dialect",
                        message="当前方言无法安全编译取数程序",
                    ),
                ),
                legacy_sql_factory,
            )
        mode = (
            ProgramGenerationMode.REPAIRED_PROGRAM
            if plan.repair_count == 1
            else ProgramGenerationMode.PROGRAM
        )
        return ProgramGenerationResult(
            sql=program.sql,
            program=program,
            plan=plan,
            intent=plan.intent,
            mode=mode,
            diagnostics=outcome.diagnostics,
        )

    def _fallback(
        self,
        program_id: str,
        origin_mode: ProgramGenerationMode,
        diagnostics: tuple[ProgramDiagnostic, ...],
        legacy_sql_factory: Callable[[], str] | None,
    ) -> ProgramGenerationResult:
        if legacy_sql_factory is None:
            return ProgramGenerationResult(
                sql=None,
                program=None,
                plan=None,
                intent=None,
                mode=origin_mode,
                diagnostics=diagnostics,
            )
        try:
            legacy_sql = legacy_sql_factory()
            program = self._wrap_legacy(program_id, legacy_sql)
        except Exception:
            return ProgramGenerationResult(
                sql=None,
                program=None,
                plan=None,
                intent=None,
                mode=origin_mode,
                diagnostics=(
                    *diagnostics,
                    ProgramDiagnostic(
                        code="unsafe_legacy_sql",
                        message="旧链路输出不是可安全包装的单条只读查询",
                    ),
                ),
            )
        return ProgramGenerationResult(
            sql=program.sql,
            program=program,
            plan=None,
            intent=None,
            mode=ProgramGenerationMode.WRAPPED_LEGACY,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _failure_mode(outcome: ProgramPlanningOutcome) -> ProgramGenerationMode:
        if any(item.code == "unsupported_plan" for item in outcome.diagnostics):
            return ProgramGenerationMode.UNSUPPORTED
        return ProgramGenerationMode.UNAVAILABLE

    @staticmethod
    def _same_snapshot(plan: SqlProgramPlan, snapshot: OntologySnapshot) -> bool:
        return (
            plan.package_id,
            plan.package_version,
            plan.package_sha256,
        ) == (
            snapshot.info.package_id,
            snapshot.info.version,
            snapshot.info.sha256,
        )

    @staticmethod
    def _wrap_legacy(program_id: str, legacy_sql: str) -> CompiledProgram:
        try:
            parsed = sqlglot.parse(legacy_sql, read="hive")
        except ParseError as error:
            raise OntologyCompileError("旧链路 SQL 无法解析") from error
        if len(parsed) != 1 or not isinstance(parsed[0], exp.Query):
            raise OntologyCompileError("旧链路必须是单条只读查询")
        query_sql = legacy_sql.strip().rstrip(";")
        target = ProgramTableNamer().target_for(
            program_id,
            1,
            ProgramStepKind.RESULT,
        )
        statement = CompiledStatement(
            step_id="result",
            target_table=target,
            drop_sql=f"DROP TABLE IF EXISTS {target};",
            create_sql=f"CREATE TABLE {target} AS\n{query_sql};",
        )
        source_tables = tuple(
            sorted(
                {
                    ".".join(part.name for part in table.parts)
                    for table in parsed[0].find_all(exp.Table)
                }
            )
        )
        program = CompiledProgram(
            program_id=program_id,
            dialect="hive",
            sql=f"{statement.drop_sql}\n{statement.create_sql}",
            statements=(statement,),
            result_table=target,
            lineage=tuple(
                LineageEdge(source=item, target="result", kind="ontology_source")
                for item in source_tables
            ),
            evidence=ProgramCompilationEvidence(source_tables=source_tables),
        )
        HiveProgramCompiler().validate_program(program)
        return program


class _RuntimeRepository:
    def __init__(self, runtime: SnapshotRuntime) -> None:
        self._runtime = runtime

    def current(self) -> OntologySnapshot:
        return self._runtime.snapshot()


@lru_cache(maxsize=1)
def get_program_generation_service() -> ProgramGenerationService:
    runtime = get_ontology_runtime()
    planner = AdaptiveProgramPlanner(
        client=get_llm_client(),
        repository=_RuntimeRepository(runtime),
    )
    return ProgramGenerationService(planner=planner, runtime=runtime)


def generate_program(
    query: str,
    *,
    request_id: str,
    system_time: datetime,
    legacy_sql_factory: Callable[[], str] | None = None,
) -> ProgramGenerationResult:
    return get_program_generation_service().generate(
        query,
        request_id=request_id,
        system_time=system_time,
        legacy_sql_factory=legacy_sql_factory,
    )
