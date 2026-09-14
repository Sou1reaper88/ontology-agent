"""Generate one canonical metadata-bound SQL program; never retry via old planners."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import lru_cache
from typing import Protocol

from agent.metadata_inference import (
    MetadataInferenceOutcome,
    MetadataInferenceService,
)
from agent.ontology_shadow import get_ontology_runtime
from ontology_core.relational_plan import CanonicalRelationalPlan
from ontology_core.relation_evidence import RelationEvidenceGraph
from ontology_core.program_models import (
    CompiledProgram,
    IntentSpec,
    ProgramDiagnostic,
    SqlProgramPlan,
)
from tools.llm_client import get_llm_client

_PROGRAM_NAMESPACE = b"ontology-agent:program:v1\0"


class ProgramGenerationMode(StrEnum):
    PROGRAM = "program"
    REPAIRED_PROGRAM = "repaired_program"
    INFERRED_PROGRAM = "inferred_program"
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
    inferred_plan: CanonicalRelationalPlan | None = None
    relation_graph: RelationEvidenceGraph | None = None
    missing_information: tuple[str, ...] = ()


class MetadataInference(Protocol):
    def infer(
        self,
        request: str,
        *,
        program_id: str,
        system_time: datetime,
        conversation_context: str | None = None,
    ) -> MetadataInferenceOutcome: ...


def derive_program_id(request_id: str) -> str:
    digest = hashlib.sha256(_PROGRAM_NAMESPACE + request_id.encode("utf-8")).hexdigest()
    return digest[:16]


class ProgramGenerationService:
    def __init__(self, *, inference_service: MetadataInference) -> None:
        self._inference = inference_service

    def generate(
        self,
        query: str,
        *,
        request_id: str,
        system_time: datetime,
        conversation_context: str | None = None,
    ) -> ProgramGenerationResult:
        kwargs = {"program_id": derive_program_id(request_id), "system_time": system_time}
        if conversation_context:
            kwargs["conversation_context"] = conversation_context
        outcome = self._inference.infer(query, **kwargs)
        if outcome.status == "ready" and outcome.program is not None and outcome.plan is not None:
            return ProgramGenerationResult(
                sql=outcome.program.sql,
                program=outcome.program,
                plan=None,
                intent=None,
                mode=ProgramGenerationMode.INFERRED_PROGRAM,
                diagnostics=outcome.diagnostics,
                inferred_plan=outcome.plan,
                relation_graph=outcome.relation_graph,
            )
        return ProgramGenerationResult(
            sql=None,
            program=None,
            plan=None,
            intent=None,
            mode=ProgramGenerationMode.UNAVAILABLE
            if outcome.status == "unavailable"
            else ProgramGenerationMode.UNSUPPORTED,
            diagnostics=outcome.diagnostics,
            missing_information=outcome.missing_information,
            relation_graph=outcome.relation_graph,
        )


@lru_cache(maxsize=1)
def get_program_generation_service() -> ProgramGenerationService:
    return ProgramGenerationService(
        inference_service=MetadataInferenceService(
            client=get_llm_client(),
            runtime=get_ontology_runtime(),
        )
    )


def generate_program(
    query: str,
    *,
    request_id: str,
    system_time: datetime,
    conversation_context: str | None = None,
) -> ProgramGenerationResult:
    return get_program_generation_service().generate(
        query,
        request_id=request_id,
        system_time=system_time,
        conversation_context=conversation_context,
    )
