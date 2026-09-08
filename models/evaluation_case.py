"""One requirement and its deterministic SQL evaluation snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base

if TYPE_CHECKING:
    from models.evaluation_run import EvaluationRun


class EvaluationCase(Base):
    __tablename__ = "evaluation_cases"
    __table_args__ = (
        UniqueConstraint("run_id", "case_number", name="uq_evaluation_case_number"),
        Index("ix_evaluation_cases_run_number", "run_id", "case_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    case_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_row: Mapped[int] = mapped_column(Integer, nullable=False)
    requirement: Mapped[str] = mapped_column(Text, nullable=False)
    reference_sql: Mapped[str] = mapped_column(Text, nullable=False)
    legacy_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    ontology_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    ontology_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ontology_evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    temporal_decisions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    reference_structure: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    legacy_structure: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ontology_structure: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    legacy_comparison: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ontology_comparison: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    diagnosis_codes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[EvaluationRun] = relationship(back_populates="cases")

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("generation_status", "pending")
        super().__init__(**kwargs)
