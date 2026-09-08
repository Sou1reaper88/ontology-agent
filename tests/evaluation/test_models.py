from __future__ import annotations

from datetime import date

from sqlalchemy import UniqueConstraint

from models import EvaluationCase, EvaluationRun


def test_evaluation_run_defaults_are_pending_and_private() -> None:
    run = EvaluationRun(
        user_id=7,
        name="baseline",
        dialect="hive",
        system_time=date(2026, 8, 24),
        total_cases=2,
    )

    assert run.status == "pending"
    assert run.processed_cases == 0
    assert run.failed_cases == 0
    assert run.summary is None


def test_cases_are_ordered_and_deleted_with_parent() -> None:
    relationship = EvaluationRun.__mapper__.relationships["cases"]
    foreign_key = next(iter(EvaluationCase.__table__.c.run_id.foreign_keys))

    assert "delete-orphan" in relationship.cascade
    assert str(relationship.order_by[0]) == "evaluation_cases.case_number"
    assert foreign_key.ondelete == "CASCADE"


def test_case_number_is_unique_within_run() -> None:
    constraints = (
        constraint
        for constraint in EvaluationCase.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    )

    assert any(
        tuple(column.name for column in constraint.columns) == ("run_id", "case_number")
        for constraint in constraints
    )


def test_case_accepts_json_evaluation_snapshots() -> None:
    case = EvaluationCase(
        run_id=1,
        case_number=1,
        source_row=2,
        requirement="synthetic requirement",
        reference_sql="SELECT ID FROM T",
        reference_structure={"status": "parsed", "tables": ["t"]},
        legacy_comparison={"score": 100, "strict_pass": True},
        ontology_comparison={"score": 80, "strict_pass": False},
        diagnosis_codes={"legacy": [], "ontology": ["field_mismatch"]},
    )

    assert case.generation_status == "pending"
    assert case.reference_structure["tables"] == ["t"]
    assert case.diagnosis_codes["ontology"] == ["field_mismatch"]
