"""Orchestrate metadata retrieval, LLM inference, validation, and compilation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from ontology_core.errors import OntologyCompileError, PackageNotFoundError
from ontology_core.inference_compiler import HiveInferenceCompiler
from ontology_core.inference_models import (
    CandidateContext,
    InferredProgramDraft,
    ValidatedInferredProgram,
)
from ontology_core.inference_validation import (
    InferenceValidationResult,
    MetadataInferenceValidator,
)
from ontology_core.metadata_candidates import MetadataCandidateCatalog
from ontology_core.metadata_lookup import FieldDetailLookup
from ontology_core.program_models import CompiledProgram, ProgramDiagnostic
from ontology_core.repository import OntologySnapshot
from tools.llm_client import StructuredPlanningError


class InferenceClient(Protocol):
    def infer_metadata_program(
        self,
        *,
        request: str,
        candidates: CandidateContext,
        conversation_context: str | None = None,
        lookup_fields: Callable[[list[str]], list[dict]] | None = None,
    ) -> InferredProgramDraft: ...


class SnapshotRuntime(Protocol):
    def snapshot(self) -> OntologySnapshot: ...


class InferenceValidator(Protocol):
    def validate(
        self,
        draft: InferredProgramDraft,
        *,
        candidates: CandidateContext,
        catalog: MetadataCandidateCatalog,
        system_time: datetime,
        request: str,
    ) -> InferenceValidationResult: ...


class InferenceCompiler(Protocol):
    def compile(
        self,
        plan: ValidatedInferredProgram,
        *,
        program_id: str,
    ) -> CompiledProgram: ...


@dataclass(frozen=True)
class MetadataInferenceOutcome:
    status: Literal["ready", "no_candidates", "failed", "unavailable"]
    program: CompiledProgram | None = None
    plan: ValidatedInferredProgram | None = None
    diagnostics: tuple[ProgramDiagnostic, ...] = ()
    missing_information: tuple[str, ...] = ()


class MetadataInferenceService:
    def __init__(
        self,
        *,
        client: InferenceClient,
        runtime: SnapshotRuntime,
        validator: InferenceValidator | None = None,
        compiler: InferenceCompiler | None = None,
        catalog_factory: Callable[[OntologySnapshot], MetadataCandidateCatalog]
        | None = None,
    ) -> None:
        self._client = client
        self._runtime = runtime
        self._validator = validator or MetadataInferenceValidator()
        self._compiler = compiler or HiveInferenceCompiler()
        self._catalog_factory = catalog_factory or MetadataCandidateCatalog.from_snapshot

    def infer(
        self,
        request: str,
        *,
        program_id: str,
        system_time: datetime,
        conversation_context: str | None = None,
    ) -> MetadataInferenceOutcome:
        try:
            snapshot = self._runtime.snapshot()
        except PackageNotFoundError:
            return MetadataInferenceOutcome(
                status="unavailable",
                diagnostics=(
                    ProgramDiagnostic(
                        code="ontology_unavailable",
                        message="当前没有可用于候选推断的活动本体版本",
                    ),
                ),
                missing_information=("请先发布包含所需表字段元数据的本体版本",),
            )
        catalog = self._catalog_factory(snapshot)
        candidates = catalog.retrieve(request)
        if not candidates.objects:
            return MetadataInferenceOutcome(
                status="no_candidates",
                diagnostics=(
                    ProgramDiagnostic(
                        code="metadata_candidate_no_match",
                        message="活动本体中没有命中需求的候选表字段",
                    ),
                ),
                missing_information=("请补充需求涉及的表名、表描述和字段描述",),
            )
        lookup = FieldDetailLookup(catalog, candidates)
        try:
            kwargs = {
                "request": request,
                "candidates": candidates,
                "lookup_fields": lookup,
            }
            if conversation_context:
                kwargs["conversation_context"] = conversation_context
            draft = self._client.infer_metadata_program(**kwargs)
        except StructuredPlanningError:
            return MetadataInferenceOutcome(
                status="failed",
                diagnostics=(
                    ProgramDiagnostic(
                        code="invalid_inferred_plan",
                        message="大模型未返回可验证的元数据候选计划",
                    ),
                ),
                missing_information=("请重试或补充更明确的表字段与业务口径",),
            )
        validation = self._validator.validate(
            draft,
            candidates=lookup.enriched(),
            catalog=catalog,
            system_time=system_time,
            request=request,
        )
        if validation.plan is None:
            return MetadataInferenceOutcome(
                status="failed",
                diagnostics=validation.diagnostics,
                missing_information=validation.missing_information,
            )
        try:
            live_snapshot = self._runtime.snapshot()
        except PackageNotFoundError:
            return self._snapshot_unavailable()
        if live_snapshot.info.sha256 != snapshot.info.sha256:
            return self._snapshot_unavailable()
        try:
            program = self._compiler.compile(validation.plan, program_id=program_id)
        except OntologyCompileError:
            return MetadataInferenceOutcome(
                status="failed",
                diagnostics=(
                    ProgramDiagnostic(
                        code="inferred_program_compile_failed",
                        message="候选计划未能通过确定性 SQL 安全编译",
                    ),
                ),
                missing_information=("请检查字段类型、关联键和时间策略",),
            )
        return MetadataInferenceOutcome(
            status="ready",
            program=program,
            plan=validation.plan,
            diagnostics=validation.diagnostics,
        )

    @staticmethod
    def _snapshot_unavailable() -> MetadataInferenceOutcome:
        return MetadataInferenceOutcome(
            status="unavailable",
            diagnostics=(
                ProgramDiagnostic(
                    code="ontology_snapshot_changed",
                    message="候选推断期间活动本体版本发生变化，本次编译已中止",
                ),
            ),
            missing_information=("请基于新的活动本体版本重新生成",),
        )
