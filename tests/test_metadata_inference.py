from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from dataclasses import replace

from agent.metadata_inference import MetadataInferenceService
from ontology_core.inference_models import CandidateContext, InferredProgramDraft
from ontology_core.program_models import (
    CompiledProgram,
    CompiledStatement,
    ProgramCompilationEvidence,
)
from tools.llm_client import StructuredPlanningError
from tests.ontology_core.test_inference_validation import (
    _object,
    _snapshot as _real_snapshot,
    _validate,
)
from tests.ontology_core.test_relation_evidence import _catalog, _join
from ontology_core.relational_plan import CanonicalRelationalPlan


def _snapshot(sha256: str = "a" * 64):
    snapshot = _real_snapshot()
    return replace(snapshot, info=snapshot.info.model_copy(update={"sha256": sha256}))


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

    def get(self, dialect):
        assert dialect == "hive"
        return self


def test_service_compiles_model_relation_without_configured_ontology(monkeypatch):
    candidates, catalog = _catalog()
    draft = InferredProgramDraft(
        selected_object_refs=("GsmHu", "GsmHz"),
        requested_field_refs=("GsmHuMobile",),
        joins=(_join(),),
    )
    events = []
    from agent import metadata_inference as module

    graph_builder = module.build_relation_evidence_graph
    adapter_convert = module.InferenceRelationalAdapter.convert
    validator_validate = module.MetadataInferenceValidator.validate
    compiler_compile = module.RelationalCompilerRegistry.default().get("hive").__class__.compile

    def traced_adapt(self, *args):
        events.append("adapt")
        return adapter_convert(self, *args)

    def traced_validate(self, *args, **kwargs):
        events.append("validate")
        return validator_validate(self, *args, **kwargs)

    def traced_compile(self, *args, **kwargs):
        events.append("compile")
        return compiler_compile(self, *args, **kwargs)

    def traced_graph(*args, **kwargs):
        events.append("complete_graph" if kwargs else "initial_graph")
        return graph_builder(*args, **kwargs)

    monkeypatch.setattr(module, "build_relation_evidence_graph", traced_graph)
    monkeypatch.setattr(module.InferenceRelationalAdapter, "convert", traced_adapt)
    monkeypatch.setattr(module.MetadataInferenceValidator, "validate", traced_validate)
    monkeypatch.setattr(
        module.RelationalCompilerRegistry.default().get("hive").__class__, "compile", traced_compile
    )
    retrieve = catalog.retrieve

    def traced_retrieve(*args, **kwargs):
        events.append("retrieve")
        return retrieve(*args, **kwargs)

    monkeypatch.setattr(catalog, "retrieve", traced_retrieve)

    class Runtime(_Runtime):
        def snapshot(self):
            events.append("snapshot")
            return super().snapshot()

    class Client(_Client):
        def infer_metadata_program(self, **kwargs):
            events.append("llm")
            assert kwargs["relation_evidence"].edges == ()
            return super().infer_metadata_program(**kwargs)

    client = Client(draft)
    outcome = MetadataInferenceService(
        client=client,
        runtime=Runtime(catalog.snapshot),
        catalog_factory=lambda snapshot: catalog,
    ).infer(
        "查询国内 GSM 通话",
        program_id="a1b2c3d4e5f6",
        system_time=datetime(2026, 8, 24, tzinfo=UTC),
    )
    assert events == [
        "snapshot",
        "retrieve",
        "initial_graph",
        "llm",
        "complete_graph",
        "validate",
        "adapt",
        "snapshot",
        "compile",
    ]
    assert outcome.status == "ready"
    assert isinstance(outcome.plan, CanonicalRelationalPlan)
    assert outcome.relation_graph.edges[0].source == "model"
    assert outcome.program.evidence.inference is not None


def test_invalid_proposed_relation_stops_without_compilation():
    _, catalog = _catalog()
    client = _Client(
        InferredProgramDraft(
            selected_object_refs=("GsmHu", "GsmHz"),
            requested_field_refs=("GsmHuMobile",),
            joins=(_join(right_field_ref="UnknownKey"),),
        )
    )
    outcome = MetadataInferenceService(
        client=client,
        runtime=_Runtime(catalog.snapshot),
        catalog_factory=lambda snapshot: catalog,
    ).infer(
        "查询国内 GSM 通话",
        program_id="a1b2c3d4e5f6",
        system_time=datetime(2026, 8, 24, tzinfo=UTC),
    )
    assert outcome.diagnostics[0].code == "invalid_relation_evidence"
    assert outcome.program is None


def test_provider_failure_is_not_reported_as_missing_business_semantics():
    candidates, catalog = _catalog()
    client = _Client(StructuredPlanningError("provider-secret"))
    outcome = MetadataInferenceService(
        client=client,
        runtime=_Runtime(catalog.snapshot),
        catalog_factory=lambda snapshot: catalog,
    ).infer(
        "查询国内 GSM 通话",
        program_id="a1b2c3d4e5f6",
        system_time=datetime(2026, 8, 24, tzinfo=UTC),
    )
    assert outcome.diagnostics[0].code == "inferred_plan_provider_unavailable"
    assert not outcome.missing_information


def test_service_runs_retrieval_llm_validation_and_compile_in_order() -> None:
    snapshot = _snapshot()
    context = _context().model_copy(update={"objects": (_object("Customer"),)})
    draft = InferredProgramDraft(
        selected_object_refs=("Customer",),
        requested_field_refs=("CustomerMobile",),
    )
    client = _Client(draft)
    validated = _validate(draft, _object("Customer")).plan
    compiler = _Compiler(_program())
    service = MetadataInferenceService(
        client=client,
        runtime=_Runtime(snapshot, snapshot),
        validator=_Validator(validated),
        registry=compiler,
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
    assert isinstance(outcome.plan, CanonicalRelationalPlan)
    assert client.calls[0]["candidates"] == context
    assert client.calls[0]["conversation_context"] == "客户指个人客户"
    assert compiler.calls == [(outcome.plan, "a1b2c3d4e5f6")]


def test_empty_retrieval_stops_before_llm() -> None:
    snapshot = _snapshot()
    client = _Client(AssertionError("LLM must not be called"))
    service = MetadataInferenceService(
        client=client,
        runtime=_Runtime(snapshot),
        validator=_Validator(None),
        registry=_Compiler(_program()),
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


def test_invalid_llm_schema_returns_safe_diagnostic() -> None:
    snapshot = _snapshot()
    context = _context().model_copy(update={"objects": (_object("Customer"),)})
    client = _Client(StructuredPlanningError("provider-secret", category="schema_validation"))
    service = MetadataInferenceService(
        client=client,
        runtime=_Runtime(snapshot),
        validator=_Validator(None),
        registry=_Compiler(_program()),
        catalog_factory=lambda value: _Catalog(value, context),
    )

    outcome = service.infer(
        "查询客户",
        program_id="a1b2c3d4e5f6",
        system_time=datetime(2026, 8, 24, tzinfo=UTC),
    )

    assert outcome.status == "failed"
    assert outcome.diagnostics[0].code == "inferred_plan_schema_invalid"
    assert "provider-secret" not in outcome.diagnostics[0].message


def test_invalid_lookup_response_returns_safe_diagnostic() -> None:
    snapshot = _snapshot()
    context = _context().model_copy(update={"objects": (_object("Customer"),)})
    client = _Client(StructuredPlanningError("tool-secret", category="tool_response_invalid"))
    service = MetadataInferenceService(
        client=client,
        runtime=_Runtime(snapshot),
        validator=_Validator(None),
        registry=_Compiler(_program()),
        catalog_factory=lambda value: _Catalog(value, context),
    )

    outcome = service.infer(
        "查询客户",
        program_id="a1b2c3d4e5f6",
        system_time=datetime(2026, 8, 24, tzinfo=UTC),
    )

    assert outcome.status == "failed"
    assert outcome.diagnostics[0].code == "inferred_plan_tool_response_invalid"
    assert "tool-secret" not in outcome.diagnostics[0].message


def test_empty_lookup_response_returns_specific_safe_diagnostic() -> None:
    snapshot = _snapshot()
    context = _context().model_copy(update={"objects": (_object("Customer"),)})
    client = _Client(
        StructuredPlanningError(
            "tool-secret",
            category="tool_response_empty_response",
        )
    )
    service = MetadataInferenceService(
        client=client,
        runtime=_Runtime(snapshot),
        validator=_Validator(None),
        registry=_Compiler(_program()),
        catalog_factory=lambda value: _Catalog(value, context),
    )

    outcome = service.infer(
        "查询客户",
        program_id="a1b2c3d4e5f6",
        system_time=datetime(2026, 8, 24, tzinfo=UTC),
    )

    assert outcome.status == "failed"
    assert outcome.diagnostics[0].code == "inferred_plan_tool_empty_response"


def test_snapshot_change_aborts_before_compile() -> None:
    first = _snapshot("a" * 64)
    second = _snapshot("b" * 64)
    context = _context().model_copy(update={"objects": (_object("Customer"),)})
    compiler = _Compiler(_program())
    service = MetadataInferenceService(
        client=_Client(
            InferredProgramDraft(
                selected_object_refs=("Customer",),
                requested_field_refs=("CustomerMobile",),
            )
        ),
        runtime=_Runtime(first, second),
        validator=_Validator(
            _validate(
                InferredProgramDraft(
                    selected_object_refs=("Customer",),
                    requested_field_refs=("CustomerMobile",),
                ),
                _object("Customer"),
            ).plan
        ),
        registry=compiler,
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
