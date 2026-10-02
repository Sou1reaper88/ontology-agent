"""A narrow, conversation-free adapter around the existing agent."""

from __future__ import annotations

import time
from hashlib import sha256
from collections.abc import Callable
from typing import Any

from agent.context_engineering import get_context_assembler
from agent.conversation_agent import run_conversation_agent
from evaluation.contracts import GenerationSnapshot


class AgentEvaluationAdapter:
    """Generate one canonical result without chat or execution records."""

    def __init__(
        self,
        *,
        run_agent_fn: Callable[..., dict[str, Any]] = run_conversation_agent,
    ) -> None:
        self._run_agent = run_agent_fn

    def generate(self, requirement: str, *, system_time: str) -> GenerationSnapshot:
        started = time.perf_counter()
        try:
            context = get_context_assembler().assemble((), current_input=requirement)
            request_hash = sha256(f"{system_time}:{requirement}".encode("utf-8")).hexdigest()[:16]
            output = self._run_agent(
                requirement,
                system_time=system_time,
                history=[],
                conversation_context=None,
                assembled_context=context.render(),
                request_id=f"evaluation:{request_hash}",
            )
        except Exception:
            return GenerationSnapshot(
                duration_ms=int((time.perf_counter() - started) * 1000),
                error_code="agent_generation_failed",
            )

        mode = output.get("generation_mode")
        sql = output.get("sql") if output.get("success") or mode == "authored_draft" else None
        trace = output.get("trace") or []
        package = output.get("package") if isinstance(output.get("package"), dict) else None
        if package is None:
            package = next(
                (step.get("payload", {}).get("package") for step in reversed(trace)
                 if isinstance(step.get("payload", {}).get("package"), dict)),
                {},
            )
        evidence = (
            output.get("inference_evidence")
            if isinstance(output.get("inference_evidence"), dict)
            else {}
        )
        temporal = output.get("temporal_evidence")
        if not isinstance(temporal, list):
            temporal = []
        diagnostics = output.get("diagnostics") or []
        error_code = (
            diagnostics[0].get("code")
            if diagnostics and isinstance(diagnostics[0], dict)
            else "canonical_generation_failed"
        )
        status = (
            "generated" if output.get("success") and sql else
            "draft" if mode == "authored_draft" else
            "unavailable" if not output.get("success") else "no_match"
        )
        return GenerationSnapshot(
            legacy_sql=None,
            legacy_success=False,
            ontology_sql=sql,
            ontology_status=status,
            ontology_summary=output.get("markdown"),
            ontology_evidence=evidence,
            temporal_decisions=temporal,
            package_id=package.get("package_id"),
            package_version=package.get("version"),
            package_sha256=package.get("sha256"),
            duration_ms=int((time.perf_counter() - started) * 1000),
            error_code=None if status == "generated" else error_code,
        )
