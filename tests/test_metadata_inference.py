from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from agent.metadata_inference import MetadataInferenceService
from ontology_core.inference_models import CandidateContext, InferredProgramDraft
from ontology_core.program_models import (
    CompiledProgram,
    CompiledStatement,
    ProgramCompilationEvidence,
)
from tools.llm_client import StructuredPlanningError


def _snapshot(sha256: str = "a" * 64):
    return SimpleNamespace(
        info=SimpleNamespace(
            package_id="evaluation",
            version="1.0.0",
            sha256=sha256,
        )
    )


def _context(sha256: str = "a" * 64) -> CandidateContext:
    return CandidateContext(
        package_id="evaluation",
        package_version="1.0.0",
        package_sha256=sha256,
    )


def _program() -> CompiledProgram:
    target = "temp_oa_a1b2c3d4e5f6_result_table"
    statement = CompiledStatement(
        step_id="result",
        target_table=target,
        drop_sql=f"DROP TABLE IF EXISTS {target};",
        create_sql=f"CREATE TABLE {target} AS\nSELECT 1;",
    )
    return CompiledProgram(
        program_id="a1b2c3d4e5f6",
        dialect="hive",
        sql=f"{statement.drop_sql}\n{statement.create_sql}",
        statements=(statement,),
        result_table=target,
        evidence=ProgramCompilationEvidence(),
    )


class _Runtime:
    def __init__(self, *snapshots) -> None:
        self.snapshots = list(snapshots)

    def snapshot(self):
        return self.snapshots.pop(0) if len(self.snapshots) > 1 else self.snapshots[0]


class _Catalog:
    def __init__(self, snapshot, context: CandidateContext) -> None:
        self.snapshot = snapshot
        self.context = context

    def retrieve(self, request: str) -> CandidateContext:
        return self.context


class _Client:
    def __init__(self, result) -> None:
        self.result = result
        self.calls = []

    def infer_metadata_program(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _Validator:
    def __init__(self, plan) -> None:
        self.plan = plan

    def validate(self, draft, **kwargs):
        return SimpleNamespace(
            plan=self.plan,
            diagnostics=(),
            missing_information=(),
        )


class _Compiler:
    def __init__(self, program: CompiledProgram) -> None:
        self.program = program
        self.calls = []

    def compile(self, plan, *, program_id: str):
        self.calls.append((plan, program_id))
        return self.program


def test_service_runs_retrieval_llm_validation_and_compile_in_order() -> None:
    snapshot = _snapshot()
    context = _context().model_copy(
        update={"objects": (SimpleNamespace(ref="Customer"),)}
    )
    draft = InferredProgramDraft(
        selected_object_refs=("Customer",),
        requested_field_refs=("CustomerMobile",),
    )
    client = _Client(draft)
    validated = SimpleNamespace(evidence="evidence")
    compiler = _Compiler(_program())
    service = MetadataInferenceService(
        client=client,
        runtime=_Runtime(snapshot, snapshot),
        validator=_Validator(validated),
        compiler=compiler,
        catalog_factory=lambda value: _Catalog(value, context),
    )

    outcome = service.infer(
        "查询客户手机号码",
        program_id="a1b2c3d4e5f6",
        system_time=datetime(2026, 8, 24, tzinfo=UTC),
        conversation_context="客户指个人客户",
    )

    assert outcome.status == "ready"
    assert outcome.program == compiler.program
    assert outcome.plan is validated
    assert client.calls[0]["candidates"] == context
    assert client.calls[0]["conversation_context"] == "客户指个人客户"
    assert compiler.calls == [(validated, "a1b2c3d4e5f6")]


def test_empty_retrieval_stops_before_llm() -> None:
    snapshot = _snapshot()
    client = _Client(AssertionError("LLM must not be called"))
    service = MetadataInferenceService(
        client=client,
        runtime=_Runtime(snapshot),
        validator=_Validator(None),
        compiler=_Compiler(_program()),
        catalog_factory=lambda value: _Catalog(value, _context()),
    )

    outcome = service.infer(
        "解释量子力学",
        program_id="a1b2c3d4e5f6",
        system_time=datetime(2026, 8, 24, tzinfo=UTC),
    )

    assert outcome.status == "no_candidates"
    assert outcome.diagnostics[0].code == "metadata_candidate_no_match"
    assert client.calls == []


def test_invalid_llm_output_returns_safe_diagnostic() -> None:
    snapshot = _snapshot()
    context = _context().model_copy(
        update={"objects": (SimpleNamespace(ref="Customer"),)}
    )
    client = _Client(StructuredPlanningError("provider-secret"))
    service = MetadataInferenceService(
        client=client,
        runtime=_Runtime(snapshot),
        validator=_Validator(None),
        compiler=_Compiler(_program()),
        catalog_factory=lambda value: _Catalog(value, context),
    )

    outcome = service.infer(
        "查询客户",
        program_id="a1b2c3d4e5f6",
        system_time=datetime(2026, 8, 24, tzinfo=UTC),
    )

    assert outcome.status == "failed"
    assert outcome.diagnostics[0].code == "invalid_inferred_plan"
    assert "provider-secret" not in outcome.diagnostics[0].message


def test_snapshot_change_aborts_before_compile() -> None:
    first = _snapshot("a" * 64)
    second = _snapshot("b" * 64)
    context = _context().model_copy(
        update={"objects": (SimpleNamespace(ref="Customer"),)}
    )
    compiler = _Compiler(_program())
    service = MetadataInferenceService(
        client=_Client(
            InferredProgramDraft(
                selected_object_refs=("Customer",),
                requested_field_refs=("CustomerMobile",),
            )
        ),
        runtime=_Runtime(first, second),
        validator=_Validator(SimpleNamespace()),
        compiler=compiler,
        catalog_factory=lambda value: _Catalog(value, context),
    )

    outcome = service.infer(
        "查询客户",
        program_id="a1b2c3d4e5f6",
        system_time=datetime(2026, 8, 24, tzinfo=UTC),
    )

    assert outcome.status == "unavailable"
    assert outcome.diagnostics[0].code == "ontology_snapshot_changed"
    assert compiler.calls == []
