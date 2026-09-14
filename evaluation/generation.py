"""A narrow, conversation-free adapter around the existing agent."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from agent.orchestrator import run_agent
from evaluation.contracts import GenerationSnapshot


class AgentEvaluationAdapter:
    """Generate one canonical result without chat or execution records."""

    def __init__(
        self,
        *,
        run_agent_fn: Callable[..., dict[str, Any]] = run_agent,
    ) -> None:
        self._run_agent = run_agent_fn

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

        sql = output.get("sql") if output.get("success") else None
        package = output.get("package") if isinstance(output.get("package"), dict) else {}
        evidence = (
            output.get("inference_evidence")
            if isinstance(output.get("inference_evidence"), dict)
            else {}
        )
        temporal = (
            output.get("temporal_evidence")
            if isinstance(output.get("temporal_evidence"), list)
            else []
        )
        diagnostics = output.get("diagnostics") or []
        error_code = (
            diagnostics[0].get("code")
            if diagnostics and isinstance(diagnostics[0], dict)
            else "canonical_generation_failed"
        )
        return GenerationSnapshot(
            legacy_sql=None,
            legacy_success=False,
            ontology_sql=sql,
            ontology_status="generated"
            if sql is not None
            else "unavailable"
            if output.get("generation_mode") == "unavailable"
            else "no_match",
            ontology_summary=output.get("markdown"),
            ontology_evidence=evidence,
            temporal_decisions=temporal,
            package_id=package.get("package_id"),
            package_version=package.get("version"),
            package_sha256=package.get("sha256"),
            duration_ms=int((time.perf_counter() - started) * 1000),
            error_code=None if sql is not None else error_code,
        )
