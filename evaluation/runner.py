"""Serial, resumable evaluation task execution."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.orm import Session

from evaluation.comparison import compare_sql_structures, summarize_candidate_results
from evaluation.contracts import (
    CandidateEvaluation,
    GenerationSnapshot,
    MetricCount,
    SqlStructure,
)
from evaluation.generation import AgentEvaluationAdapter
from evaluation.sql_structure import extract_sql_structure
from models import EvaluationCase, EvaluationRun


class _Generator(Protocol):
    def generate(self, requirement: str, *, system_time: str) -> GenerationSnapshot: ...


_ONTOLOGY_FAILURE_CODES = {
    "no_match": "ontology_no_match",
    "ambiguous": "ontology_ambiguous",
    "unsupported": "ontology_unsupported",
    "unavailable": "ontology_unavailable",
    "clarification_required": "ontology_clarification_required",
}


def _metric(numerator: int, denominator: int) -> MetricCount:
    return MetricCount(
        numerator=numerator,
        denominator=denominator,
        rate=round(numerator / denominator * 100, 1) if denominator else None,
    )


def _missing_structure(reason: str) -> SqlStructure:
    return SqlStructure(
        status="unsupported",
        is_read_only=False,
        warnings=(reason,),
    )


def _diagnoses(
    evaluation: CandidateEvaluation,
    primary: str | None = None,
) -> list[str]:
    values = (*(item for item in (primary,) if item), *evaluation.diagnosis_codes)
    return list(dict.fromkeys(values))


class EvaluationRunner:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        adapter: _Generator | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._adapter = adapter or AgentEvaluationAdapter()

    def run(self, run_id: int) -> None:
        with self._session_factory() as session:
            run = session.get(EvaluationRun, run_id)
            if run is None or run.status == "completed":
                return
            run.status = "running"
            run.started_at = run.started_at or datetime.now(UTC)
            for case in run.cases:
                if case.generation_status == "running":
                    case.generation_status = "pending"
            session.commit()

            for case in run.cases:
                if case.generation_status in {"completed", "failed"}:
                    continue
                case.generation_status = "running"
                session.commit()
                try:
                    generated = self._adapter.generate(
                        case.requirement,
                        system_time=run.system_time.isoformat(),
                    )
                    if self._package_changed(run, generated):
                        case.generation_status = "failed"
                        case.error_code = "ontology_package_changed"
                        run.status = "failed"
                        run.error_code = "ontology_package_changed"
                        session.commit()
                        return
                    self._evaluate_case(run, case, generated)
                except Exception:
                    case.generation_status = "failed"
                    case.error_code = "generation_runtime_error"
                    case.completed_at = datetime.now(UTC)
                self._refresh_counts(run)
                session.commit()

            self._refresh_counts(run)
            run.summary = self._summary(run)
            run.status = "completed"
            run.completed_at = datetime.now(UTC)
            session.commit()

    @staticmethod
    def _package_changed(run: EvaluationRun, generated: GenerationSnapshot) -> bool:
        if not generated.package_sha256:
            return False
        if run.package_sha256 and run.package_sha256 != generated.package_sha256:
            return True
        if not run.package_sha256:
            run.package_id = generated.package_id
            run.package_version = generated.package_version
            run.package_sha256 = generated.package_sha256
        return False

    @staticmethod
    def _evaluate_case(
        run: EvaluationRun,
        case: EvaluationCase,
        generated: GenerationSnapshot,
    ) -> None:
        reference = extract_sql_structure(case.reference_sql, run.dialect)
        legacy = (
            extract_sql_structure(generated.legacy_sql, run.dialect)
            if generated.legacy_sql
            else _missing_structure("legacy_not_generated")
        )
        ontology = (
            extract_sql_structure(generated.ontology_sql, run.dialect)
            if generated.ontology_sql
            else _missing_structure("ontology_not_generated")
        )
        partition_fields = {
            str(item.get("partition_field", ""))
            for item in generated.temporal_decisions
            if item.get("partition_field")
        }
        legacy_result = compare_sql_structures(
            reference,
            legacy,
            partition_fields=partition_fields,
        )
        ontology_result = compare_sql_structures(
            reference,
            ontology,
            partition_fields=partition_fields,
        )
        ontology_primary = _ONTOLOGY_FAILURE_CODES.get(generated.ontology_status or "")
        case.legacy_sql = generated.legacy_sql
        case.ontology_sql = generated.ontology_sql
        case.ontology_status = generated.ontology_status
        case.ontology_evidence = generated.ontology_evidence
        case.temporal_decisions = generated.temporal_decisions
        case.reference_structure = reference.model_dump(mode="json")
        case.legacy_structure = legacy.model_dump(mode="json")
        case.ontology_structure = ontology.model_dump(mode="json")
        case.legacy_comparison = legacy_result.model_dump(mode="json")
        case.ontology_comparison = ontology_result.model_dump(mode="json")
        case.diagnosis_codes = {
            "legacy": _diagnoses(
                legacy_result,
                None if generated.legacy_success else "legacy_generation_failed",
            ),
            "ontology": _diagnoses(ontology_result, ontology_primary),
        }
        case.duration_ms = generated.duration_ms
        case.error_code = generated.error_code
        case.generation_status = "completed"
        case.completed_at = datetime.now(UTC)

    @staticmethod
    def _refresh_counts(run: EvaluationRun) -> None:
        run.processed_cases = sum(
            case.generation_status in {"completed", "failed"} for case in run.cases
        )
        run.failed_cases = sum(case.generation_status == "failed" for case in run.cases)

    @staticmethod
    def _summary(run: EvaluationRun) -> dict:
        legacy = tuple(
            CandidateEvaluation.model_validate(case.legacy_comparison)
            for case in run.cases
            if case.legacy_comparison is not None
        )
        ontology = tuple(
            CandidateEvaluation.model_validate(case.ontology_comparison)
            for case in run.cases
            if case.ontology_comparison is not None
        )
        generated_count = sum(case.ontology_status == "generated" for case in run.cases)
        no_match_count = sum(case.ontology_status == "no_match" for case in run.cases)
        legacy_diagnoses = Counter(
            code
            for case in run.cases
            for code in ((case.diagnosis_codes or {}).get("legacy", []))
        )
        ontology_diagnoses = Counter(
            code
            for case in run.cases
            for code in ((case.diagnosis_codes or {}).get("ontology", []))
        )
        return {
            "legacy": summarize_candidate_results(legacy).model_dump(mode="json"),
            "ontology": summarize_candidate_results(ontology).model_dump(mode="json"),
            "ontology_generation": _metric(generated_count, len(run.cases)).model_dump(
                mode="json"
            ),
            "ontology_no_match": _metric(no_match_count, len(run.cases)).model_dump(
                mode="json"
            ),
            "diagnoses": {
                "legacy": dict(sorted(legacy_diagnoses.items())),
                "ontology": dict(sorted(ontology_diagnoses.items())),
            },
        }
