"""Adaptive SQL-free LLM planning with one targeted repair at most."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Literal, Protocol

from pydantic import Field

from ontology_core.program_models import (
    DraftSqlProgramPlan,
    ProgramDiagnostic,
    ProgramModel,
    SqlProgramPlan,
)
from ontology_core.program_validation import (
    OntologyProgramBinder,
    ProgramValidationResult,
)
from ontology_core.repository import OntologyRepository, OntologySnapshot
from tools.llm_client import StructuredPlanningError


class StructuredPlanningClient(Protocol):
    def plan_sql_program(
        self,
        *,
        system_prompt: str,
        user_query: str,
    ) -> DraftSqlProgramPlan: ...

    def repair_sql_program(
        self,
        *,
        original_query: str,
        draft: DraftSqlProgramPlan,
        diagnostics: Sequence[ProgramDiagnostic],
        conversation_context: str | None = None,
    ) -> DraftSqlProgramPlan: ...


class ProgramBinder(Protocol):
    def bind(
        self,
        draft: DraftSqlProgramPlan,
        *,
        program_id: str,
        system_time: datetime,
        snapshot: OntologySnapshot,
    ) -> ProgramValidationResult: ...


class ProgramPlanningOutcome(ProgramModel):
    status: Literal["ready", "clarification_required", "failed"]
    plan: SqlProgramPlan | None = None
    diagnostics: tuple[ProgramDiagnostic, ...] = ()
    llm_call_count: int = Field(ge=0, le=2)


class AdaptiveProgramPlanner:
    def __init__(
        self,
        *,
        client: StructuredPlanningClient,
        repository: OntologyRepository,
        binder: ProgramBinder | None = None,
    ) -> None:
        self._client = client
        self._repository = repository
        self._binder = binder or OntologyProgramBinder()

    def plan(
        self,
        query: str,
        *,
        program_id: str,
        system_time: datetime,
        conversation_context: str | None = None,
    ) -> ProgramPlanningOutcome:
        snapshot = self._repository.current()
        try:
            draft = self._client.plan_sql_program(
                system_prompt=self._planning_prompt(snapshot, conversation_context),
                user_query=query,
            )
        except StructuredPlanningError as error:
            return self._invalid_output(call_count=1, error=error)
        validation = self._bind(
            draft,
            program_id=program_id,
            system_time=system_time,
            snapshot=snapshot,
        )
        if validation.plan is not None:
            return ProgramPlanningOutcome(
                status="ready",
                plan=validation.plan,
                diagnostics=validation.diagnostics,
                llm_call_count=1,
            )
        if validation.should_clarify:
            return ProgramPlanningOutcome(
                status="clarification_required",
                diagnostics=validation.diagnostics,
                llm_call_count=1,
            )
        if not validation.should_repair:
            return ProgramPlanningOutcome(
                status="failed",
                diagnostics=validation.diagnostics,
                llm_call_count=1,
            )
        try:
            if conversation_context:
                repaired = self._client.repair_sql_program(
                    original_query=query,
                    draft=draft,
                    diagnostics=validation.diagnostics,
                    conversation_context=conversation_context,
                )
            else:
                repaired = self._client.repair_sql_program(
                    original_query=query,
                    draft=draft,
                    diagnostics=validation.diagnostics,
                )
        except StructuredPlanningError as error:
            return self._invalid_output(call_count=2, error=error)
        repaired_validation = self._bind(
            repaired,
            program_id=program_id,
            system_time=system_time,
            snapshot=snapshot,
        )
        if repaired_validation.plan is not None:
            repaired_plan = repaired_validation.plan.model_copy(
                update={"repair_count": 1},
            )
            return ProgramPlanningOutcome(
                status="ready",
                plan=repaired_plan,
                diagnostics=repaired_validation.diagnostics,
                llm_call_count=2,
            )
        status = (
            "clarification_required"
            if repaired_validation.should_clarify
            else "failed"
        )
        return ProgramPlanningOutcome(
            status=status,
            diagnostics=repaired_validation.diagnostics,
            llm_call_count=2,
        )

    def _bind(
        self,
        draft: DraftSqlProgramPlan,
        *,
        program_id: str,
        system_time: datetime,
        snapshot: OntologySnapshot,
    ) -> ProgramValidationResult:
        return self._binder.bind(
            draft,
            program_id=program_id,
            system_time=system_time,
            snapshot=snapshot,
        )

    @staticmethod
    def _invalid_output(
        *,
        call_count: int,
        error: StructuredPlanningError,
    ) -> ProgramPlanningOutcome:
        diagnostic = {
            "invalid_json": ProgramDiagnostic(
                code="structured_plan_json_invalid",
                message="大模型返回的结构化计划不是有效 JSON",
            ),
            "schema_validation": ProgramDiagnostic(
                code="structured_plan_schema_invalid",
                message="大模型返回 JSON，但未满足取数计划字段约束",
            ),
        }.get(
            error.category,
            ProgramDiagnostic(
                code="structured_plan_provider_unavailable",
                message="结构化规划服务暂不可用",
            ),
        )
        return ProgramPlanningOutcome(
            status="failed",
            diagnostics=(diagnostic,),
            llm_call_count=call_count,
        )

    @classmethod
    def _planning_prompt(
        cls,
        snapshot: OntologySnapshot,
        conversation_context: str | None = None,
    ) -> str:
        summary = cls._semantic_summary(snapshot)
        schema = json.dumps(
            DraftSqlProgramPlan.model_json_schema(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        prompt = (
            "你是本体驱动的取数程序规划器。"
            "仅输出一个符合 JSON Schema 的 JSON 对象。"
            "禁止输出 SQL；禁止输出目标表名、物理表名、物理字段名。"
            "只能使用语义摘要中的 URI 或稳定短名；有歧义时写入 ambiguities，"
            "不得猜测。简单需求使用一个结果步骤，只在多来源、复杂排除、"
            "重复聚合或可复用逻辑时创建中间步骤。\n"
            f"JSON Schema: {schema}\n"
            f"本体语义摘要: {summary}"
        )
        if conversation_context:
            prompt += f"\n本轮共享会话上下文：{conversation_context}"
        return prompt

    @staticmethod
    def _semantic_summary(snapshot: OntologySnapshot) -> str:
        catalog = snapshot.catalog

        def identity(item) -> dict[str, str]:
            return {
                "uri": item.uri,
                "short_name": item.short_name,
                "label": item.label,
            }

        payload = {
            "concepts": [identity(item) for item in catalog.concepts],
            "properties": [identity(item) for item in catalog.properties],
            "relations": [identity(item) for item in catalog.relations],
            "rules": [identity(item) for item in catalog.rules],
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
