"""A narrow, conversation-free adapter around the existing agent."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

from agent.ontology_shadow import get_ontology_shadow_service
from agent.orchestrator import run_agent
from evaluation.contracts import GenerationSnapshot


class _ShadowPreview(Protocol):
    def preview(
        self,
        query: str,
        legacy_sql: str | None,
        *,
        system_time: str | None = None,
    ) -> Any: ...


class AgentEvaluationAdapter:
    """Generate both paths without creating chat or execution records."""

    def __init__(
        self,
        *,
        run_agent_fn: Callable[..., dict[str, Any]] = run_agent,
        shadow_service: _ShadowPreview | None = None,
    ) -> None:
        self._run_agent = run_agent_fn
        self._shadow_service = shadow_service

    def generate(self, requirement: str, *, system_time: str) -> GenerationSnapshot:
        started = time.perf_counter()
        try:
            output = self._run_agent(
                requirement,
                system_time=system_time,
                history=[],
                conversation_context=None,
            )
        except Exception:
            return GenerationSnapshot(
                duration_ms=int((time.perf_counter() - started) * 1000),
                error_code="agent_generation_failed",
            )

        legacy_sql = output.get("sql") if output.get("success") else None
        shadow = output.get("ontology_shadow")
        if not isinstance(shadow, dict):
            service = self._shadow_service or get_ontology_shadow_service()
            try:
                shadow = service.preview(
                    requirement,
                    legacy_sql,
                    system_time=system_time,
                ).model_dump(mode="json")
            except Exception:
                shadow = {
                    "status": "unavailable",
                    "summary": "本体影子链路当前不可用",
                }
        package = shadow.get("package") if isinstance(shadow.get("package"), dict) else {}
        evidence = shadow.get("evidence") if isinstance(shadow.get("evidence"), dict) else {}
        temporal = (
            shadow.get("temporal_decisions")
            if isinstance(shadow.get("temporal_decisions"), list)
            else []
        )
        return GenerationSnapshot(
            legacy_sql=legacy_sql,
            legacy_success=legacy_sql is not None,
            ontology_sql=shadow.get("ontology_sql"),
            ontology_status=shadow.get("status"),
            ontology_summary=shadow.get("summary"),
            ontology_evidence=evidence,
            temporal_decisions=temporal,
            package_id=package.get("package_id"),
            package_version=package.get("version"),
            package_sha256=package.get("sha256"),
            duration_ms=int((time.perf_counter() - started) * 1000),
            error_code=None if legacy_sql is not None else "legacy_generation_failed",
        )
