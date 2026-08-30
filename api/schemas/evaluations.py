"""Public response contracts for SQL evaluation APIs."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class EvaluationRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    dialect: str
    system_time: date
    status: str
    total_cases: int
    processed_cases: int
    failed_cases: int
    package_id: str | None
    package_version: str | None
    package_sha256: str | None
    summary: dict | None
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class EvaluationCaseSummary(BaseModel):
    id: int
    case_number: int
    generation_status: str
    ontology_status: str | None
    legacy_score: int | None
    legacy_strict_pass: bool
    ontology_score: int | None
    ontology_strict_pass: bool
    primary_diagnosis: str | None
    manual_review: bool
    duration_ms: int | None


class EvaluationCaseDetail(EvaluationCaseSummary):
    requirement: str
    reference_sql: str
    legacy_sql: str | None
    ontology_sql: str | None
    reference_structure: dict | None
    legacy_structure: dict | None
    ontology_structure: dict | None
    legacy_comparison: dict | None
    ontology_comparison: dict | None
    diagnosis_codes: dict | None
    ontology_evidence: dict | None
    temporal_decisions: list | None
    error_code: str | None
