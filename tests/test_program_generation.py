from datetime import UTC, datetime

import pytest

from agent.metadata_inference import MetadataInferenceOutcome
from agent.program_generation import (
    ProgramGenerationMode,
    ProgramGenerationService,
    derive_program_id,
)
from config.settings import Settings
from ontology_core.inference_models import InferredProgramDraft
from ontology_core.program_models import ProgramDiagnostic
from ontology_core.relational_compiler import HiveRelationalCompiler
from tests.ontology_core.test_inference_to_relational import _convert
from tests.ontology_core.test_inference_validation import _object

SYSTEM_TIME = datetime(2026, 8, 24, tzinfo=UTC)


class _Inference:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def infer(self, query, **kwargs):
        self.calls.append((query, kwargs))
        return self.outcome


def test_llm_author_pipeline_is_default():
    assert Settings(_env_file=None).sql_pipeline == "llm"


def test_program_id_is_stable_and_does_not_expose_request_id():
    request = "conversation-user-secret"
    assert derive_program_id(request) == derive_program_id(request)
    assert len(derive_program_id(request)) == 16
    assert request not in derive_program_id(request)


@pytest.mark.parametrize("status", ["failed", "no_candidates", "unavailable"])
def test_canonical_failure_returns_original_diagnostics_without_fallback(status):
    diagnostic = ProgramDiagnostic(code="original_failure", message="原始失败原因")
    inference = _Inference(
        MetadataInferenceOutcome(
            status=status,
            diagnostics=(diagnostic,),
            missing_information=("需要确认的内容",),
        )
    )
    service = ProgramGenerationService(inference_service=inference)
    result = service.generate("查询客户", request_id="request-001", system_time=SYSTEM_TIME)
    assert result.sql is None
    assert result.diagnostics == (diagnostic,)
    assert result.missing_information == inference.outcome.missing_information
    assert len(inference.calls) == 1
    assert not hasattr(service, "_planner")
    assert not hasattr(service, "_fallback")
    assert result.mode == (
        ProgramGenerationMode.UNAVAILABLE
        if status == "unavailable"
        else ProgramGenerationMode.UNSUPPORTED
    )


def test_canonical_success_returns_the_only_program_and_shared_context():
    plan = _convert(
        InferredProgramDraft(
            selected_object_refs=("Customer",),
            requested_field_refs=("CustomerMobile",),
        ),
        _object("Customer"),
    )
    program = HiveRelationalCompiler().compile(plan, program_id=derive_program_id("request-001"))
    inference = _Inference(MetadataInferenceOutcome(status="ready", plan=plan, program=program))
    result = ProgramGenerationService(inference_service=inference).generate(
        "查询客户",
        request_id="request-001",
        system_time=SYSTEM_TIME,
        conversation_context="已确认口径",
    )
    assert result.sql == program.sql
    assert result.inferred_plan == plan
    assert result.mode == ProgramGenerationMode.INFERRED_PROGRAM
    assert inference.calls == [
        (
            "查询客户",
            {
                "program_id": derive_program_id("request-001"),
                "system_time": SYSTEM_TIME,
                "conversation_context": "已确认口径",
            },
        )
    ]
