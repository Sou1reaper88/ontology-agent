"""Validate a draft program DAG and bind every step to one ontology snapshot."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from ontology_core.errors import (
    AmbiguousIdentifierError,
    AmbiguousQueryConceptError,
    ConceptNotFoundError,
    PropertyNotFoundError,
    TemporalIntentError,
    UnsupportedQueryPlanError,
)
from ontology_core.planner import OntologyPlanner
from ontology_core.program_models import (
    DraftProgramStep,
    DraftSqlProgramPlan,
    ProgramDiagnostic,
    ProgramModel,
    ProgramStep,
    ProgramStepKind,
    SqlProgramPlan,
)
from ontology_core.repository import OntologySnapshot
from ontology_core.resolver import OntologyResolver


class ProgramDiagnosticCode(StrEnum):
    REPAIRABLE_REFERENCE = "repairable_reference"
    AMBIGUOUS_BUSINESS_TERM = "ambiguous_business_term"
    UNSUPPORTED_PLAN = "unsupported_plan"


class ProgramValidationResult(ProgramModel):
    plan: SqlProgramPlan | None = None
    diagnostics: tuple[ProgramDiagnostic, ...] = ()
    should_repair: bool = False
    should_clarify: bool = False


class OntologyProgramBinder:
    def bind(
        self,
        draft: DraftSqlProgramPlan,
        *,
        program_id: str,
        system_time: datetime,
        snapshot: OntologySnapshot,
    ) -> ProgramValidationResult:
        if draft.intent.ambiguities:
            return ProgramValidationResult(
                diagnostics=(
                    ProgramDiagnostic(
                        code=ProgramDiagnosticCode.AMBIGUOUS_BUSINESS_TERM,
                        message="业务意图包含需要确认的歧义",
                    ),
                ),
                should_clarify=True,
            )
        ordered, graph_diagnostic = self._ordered_steps(draft.steps)
        if graph_diagnostic is not None:
            return ProgramValidationResult(
                diagnostics=(graph_diagnostic,),
                should_repair=True,
            )
        planner = OntologyPlanner(OntologyResolver(snapshot))
        bound_steps: list[ProgramStep] = []
        bound_by_id: dict[str, ProgramStep] = {}
        try:
            for step in ordered:
                self._validate_upstream_objects(step, bound_by_id)
                query_plan = planner.plan_structured(
                    step,
                    draft.intent,
                    system_time=system_time,
                    snapshot=snapshot,
                )
                bound = ProgramStep(
                    step_id=step.step_id,
                    kind=step.kind,
                    purpose=step.purpose,
                    source_objects=step.source_objects,
                    source_bindings=step.source_bindings,
                    query_plan=query_plan,
                )
                bound_steps.append(bound)
                bound_by_id[bound.step_id] = bound
        except (AmbiguousIdentifierError, AmbiguousQueryConceptError, TemporalIntentError) as error:
            return ProgramValidationResult(
                diagnostics=(
                    self._diagnostic(
                        ProgramDiagnosticCode.AMBIGUOUS_BUSINESS_TERM,
                        "业务语义或时间范围需要确认",
                        error,
                    ),
                ),
                should_clarify=True,
            )
        except (ConceptNotFoundError, PropertyNotFoundError, UnsupportedQueryPlanError) as error:
            return ProgramValidationResult(
                diagnostics=(
                    self._diagnostic(
                        ProgramDiagnosticCode.UNSUPPORTED_PLAN,
                        "本体映射或程序形态暂不支持",
                        error,
                    ),
                ),
            )
        source_ids = {item.query_plan.data_source.uri for item in bound_steps}
        if len(source_ids) != 1:
            return ProgramValidationResult(
                diagnostics=(
                    ProgramDiagnostic(
                        code=ProgramDiagnosticCode.UNSUPPORTED_PLAN,
                        message="程序步骤未绑定到同一数据源",
                    ),
                ),
            )
        result_step_id = next(
            item.step_id for item in bound_steps if item.kind == ProgramStepKind.RESULT
        )
        source = bound_steps[0].query_plan.data_source
        return ProgramValidationResult(
            plan=SqlProgramPlan(
                program_id=program_id,
                package_id=snapshot.info.package_id,
                package_version=snapshot.info.version,
                package_sha256=snapshot.info.sha256,
                data_source_id=next(iter(source_ids)),
                dialect=source.dialect or source.platform_type,
                intent=draft.intent,
                steps=tuple(bound_steps),
                result_step_id=result_step_id,
            )
        )

    @staticmethod
    def _ordered_steps(
        steps: tuple[DraftProgramStep, ...],
    ) -> tuple[tuple[DraftProgramStep, ...], ProgramDiagnostic | None]:
        step_ids = tuple(item.step_id for item in steps)
        if len(set(step_ids)) != len(step_ids):
            return (), OntologyProgramBinder._graph_diagnostic("步骤标识重复")
        result_ids = tuple(
            item.step_id for item in steps if item.kind == ProgramStepKind.RESULT
        )
        if len(result_ids) != 1:
            return (), OntologyProgramBinder._graph_diagnostic("结果步骤数量无效")
        dependencies = {
            step.step_id: {
                item.source_step_id
                for item in step.source_bindings
                if item.source_step_id is not None
            }
            for step in steps
        }
        known = set(step_ids)
        if any(step_id in refs or refs - known for step_id, refs in dependencies.items()):
            return (), OntologyProgramBinder._graph_diagnostic("步骤依赖包含悬空或自身引用")
        result_id = result_ids[0]
        if any(result_id in refs for step_id, refs in dependencies.items() if step_id != result_id):
            return (), OntologyProgramBinder._graph_diagnostic("结果步骤必须是终点")
        remaining = set(step_ids)
        resolved: set[str] = set()
        ordered: list[DraftProgramStep] = []
        while remaining:
            ready = tuple(
                step
                for step in steps
                if step.step_id in remaining and dependencies[step.step_id] <= resolved
            )
            if not ready:
                return (), OntologyProgramBinder._graph_diagnostic("步骤依赖存在循环")
            for step in ready:
                ordered.append(step)
                resolved.add(step.step_id)
                remaining.remove(step.step_id)
        if ordered[-1].step_id != result_id:
            return (), OntologyProgramBinder._graph_diagnostic("结果步骤必须最后生成")
        return tuple(ordered), None

    @staticmethod
    def _validate_upstream_objects(
        step: DraftProgramStep,
        bound_by_id: dict[str, ProgramStep],
    ) -> None:
        for binding in step.source_bindings:
            if binding.source_step_id is None:
                continue
            upstream = bound_by_id.get(binding.source_step_id)
            if upstream is None or binding.object_ref not in upstream.source_objects:
                raise UnsupportedQueryPlanError(
                    "前置步骤没有产生所需语义对象",
                    details={"step_id": step.step_id},
                )

    @staticmethod
    def _graph_diagnostic(message: str) -> ProgramDiagnostic:
        return ProgramDiagnostic(
            code=ProgramDiagnosticCode.REPAIRABLE_REFERENCE,
            message=message,
        )

    @staticmethod
    def _diagnostic(
        code: ProgramDiagnosticCode,
        message: str,
        error: Exception,
    ) -> ProgramDiagnostic:
        details = getattr(error, "details", {})
        candidates = details.get("candidates", ()) if isinstance(details, dict) else ()
        return ProgramDiagnostic(
            code=code,
            message=message,
            candidates=tuple(str(item) for item in candidates),
        )
