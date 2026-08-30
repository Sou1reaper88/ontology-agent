"""Stable, JSON-serializable contracts for SQL evaluation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

StructureStatus = Literal["parsed", "unparsed", "unsupported"]
DimensionStatus = Literal[
    "matched",
    "partial",
    "mismatched",
    "not_applicable",
    "unscorable",
]


class FrozenModel(BaseModel):
    """Base model for deterministic snapshots."""

    model_config = ConfigDict(frozen=True)


class JoinSignature(FrozenModel):
    join_type: str
    left: str
    right: str
    conditions: tuple[str, ...] = ()


class PredicateSignature(FrozenModel):
    field: str
    operator: str
    values: tuple[str, ...] = ()


class SqlStructure(FrozenModel):
    status: StructureStatus
    is_read_only: bool
    tables: tuple[str, ...] = ()
    projections: tuple[str, ...] = ()
    joins: tuple[JoinSignature, ...] = ()
    predicates: tuple[PredicateSignature, ...] = ()
    having: tuple[PredicateSignature, ...] = ()
    aggregates: tuple[str, ...] = ()
    group_by: tuple[str, ...] = ()
    distinct: bool = False
    order_by: tuple[str, ...] = ()
    limit: int | None = None
    has_star: bool = False
    has_cte: bool = False
    has_subquery: bool = False
    warnings: tuple[str, ...] = ()


class DimensionResult(FrozenModel):
    status: DimensionStatus
    score: int | None
    missing: tuple[str, ...] = ()
    extra: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()


class CandidateEvaluation(FrozenModel):
    score: int | None
    strict_pass: bool
    manual_review: bool
    dimensions: dict[str, DimensionResult]
    diagnosis_codes: tuple[str, ...] = ()


class MetricCount(FrozenModel):
    numerator: int
    denominator: int
    rate: float | None


class CandidateSummary(FrozenModel):
    total: int
    scorable: int
    strict_pass: MetricCount
    manual_review: MetricCount
    average_score: float | None
    dimensions: dict[str, MetricCount]


class ImportedCase(FrozenModel):
    row_number: int
    requirement: str
    reference_sql: str


class GenerationSnapshot(FrozenModel):
    legacy_sql: str | None = None
    legacy_success: bool = False
    ontology_sql: str | None = None
    ontology_status: str | None = None
    ontology_summary: str | None = None
    ontology_evidence: dict = {}
    temporal_decisions: list[dict] = []
    package_id: str | None = None
    package_version: str | None = None
    package_sha256: str | None = None
    duration_ms: int = 0
    error_code: str | None = None
