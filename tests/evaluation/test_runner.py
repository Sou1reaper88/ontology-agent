from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from evaluation.contracts import GenerationSnapshot
from evaluation.generation import AgentEvaluationAdapter
from evaluation.runner import EvaluationRunner
from models import Base, EvaluationCase, EvaluationRun, Role, User


class FakeAdapter:
    def __init__(self, snapshots: list[GenerationSnapshot | Exception]) -> None:
        self.snapshots = snapshots
        self.calls: list[tuple[str, str]] = []

    def generate(self, requirement: str, *, system_time: str) -> GenerationSnapshot:
        self.calls.append((requirement, system_time))
        result = self.snapshots.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def snapshot(
    *,
    legacy_sql: str = "SELECT ID FROM T",
    ontology_sql: str | None = "SELECT ID FROM T",
    ontology_status: str = "generated",
    package_sha256: str = "a" * 12,
) -> GenerationSnapshot:
    return GenerationSnapshot(
        legacy_sql=legacy_sql,
        legacy_success=True,
        ontology_sql=ontology_sql,
        ontology_status=ontology_status,
        ontology_summary="synthetic",
        ontology_evidence={},
        temporal_decisions=[],
        package_id="pkg",
        package_version="1.0.0",
        package_sha256=package_sha256,
        duration_ms=5,
    )


def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Role.__table__,
            User.__table__,
            EvaluationRun.__table__,
            EvaluationCase.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        role = Role(name="evaluation-test")
        session.add(role)
        session.flush()
        session.add(
            User(
                id=1,
                username="evaluation-user",
                display_name="Evaluation User",
                role_id=role.id,
            )
        )
        session.commit()
    return factory


def add_run(factory, *, count: int = 2) -> int:
    with factory() as session:
        run = EvaluationRun(
            user_id=1,
            name="baseline",
            dialect="hive",
            system_time=date(2026, 8, 24),
            total_cases=count,
        )
        run.cases = [
            EvaluationCase(
                case_number=index,
                source_row=index + 1,
                requirement=f"requirement-{index}",
                reference_sql="SELECT ID FROM T",
            )
            for index in range(1, count + 1)
        ]
        session.add(run)
        session.commit()
        return run.id


def test_runner_processes_cases_serially_and_summarizes() -> None:
    factory = session_factory()
    run_id = add_run(factory)
    adapter = FakeAdapter([snapshot(), snapshot(ontology_status="no_match", ontology_sql=None)])

    EvaluationRunner(factory, adapter=adapter).run(run_id)

    with factory() as session:
        run = session.get(EvaluationRun, run_id)
        assert run is not None
        assert run.status == "completed"
        assert run.processed_cases == 2
        assert run.failed_cases == 0
        assert run.package_sha256 == "a" * 12
        assert run.summary["legacy"]["strict_pass"]["numerator"] == 2
        assert run.summary["ontology_generation"]["numerator"] == 1
        assert run.summary["diagnoses"]["ontology"] == {
            "candidate_parse_failed": 1,
            "manual_review_required": 1,
            "ontology_no_match": 1,
        }
        assert run.cases[1].diagnosis_codes["ontology"][0] == "ontology_no_match"
    assert adapter.calls == [
        ("requirement-1", "2026-08-24"),
        ("requirement-2", "2026-08-24"),
    ]


def test_completed_run_is_idempotent() -> None:
    factory = session_factory()
    run_id = add_run(factory, count=1)
    adapter = FakeAdapter([snapshot()])
    runner = EvaluationRunner(factory, adapter=adapter)

    runner.run(run_id)
    runner.run(run_id)

    assert len(adapter.calls) == 1


def test_case_error_does_not_stop_following_cases_or_leak_message() -> None:
    factory = session_factory()
    run_id = add_run(factory)
    adapter = FakeAdapter([RuntimeError("C:/private/secret"), snapshot()])

    EvaluationRunner(factory, adapter=adapter).run(run_id)

    with factory() as session:
        run = session.get(EvaluationRun, run_id)
        assert run is not None
        assert run.status == "completed"
        assert run.failed_cases == 1
        assert run.cases[0].error_code == "generation_runtime_error"
        assert "secret" not in str(run.cases[0].__dict__).casefold()
        assert run.cases[1].generation_status == "completed"


def test_package_change_stops_remaining_cases() -> None:
    factory = session_factory()
    run_id = add_run(factory, count=3)
    adapter = FakeAdapter(
        [snapshot(package_sha256="a" * 12), snapshot(package_sha256="b" * 12), snapshot()]
    )

    EvaluationRunner(factory, adapter=adapter).run(run_id)

    with factory() as session:
        run = session.get(EvaluationRun, run_id)
        assert run is not None
        assert run.status == "failed"
        assert run.error_code == "ontology_package_changed"
        assert run.cases[2].generation_status == "pending"
    assert len(adapter.calls) == 2


def test_agent_adapter_reads_single_canonical_result() -> None:
    calls: list[dict] = []

    def fake_run_agent(requirement: str, **kwargs):
        calls.append({"requirement": requirement, **kwargs})
        return {
            "success": True,
            "sql": "SELECT ID FROM T",
            "package": {
                "package_id": "pkg",
                "version": "1.0.0",
                "sha256": "abc",
            },
            "temporal_evidence": [{"source": "default"}],
            "inference_evidence": {"overall_confidence": "medium"},
        }

    result = AgentEvaluationAdapter(
        run_agent_fn=fake_run_agent,
    ).generate("requirement", system_time="2026-08-24")

    assert result.legacy_success is False
    assert result.legacy_sql is None
    assert result.ontology_sql == "SELECT ID FROM T"
    assert result.ontology_status == "generated"
    assert result.package_sha256 == "abc"
    assert result.temporal_decisions == [{"source": "default"}]
    assert calls[0]["history"] == []
    assert calls[0]["conversation_context"] is None
