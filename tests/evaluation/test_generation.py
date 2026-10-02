from __future__ import annotations

from agent.conversation_agent import run_conversation_agent
from evaluation.generation import AgentEvaluationAdapter


def test_adapter_uses_current_conversation_agent() -> None:
    assert AgentEvaluationAdapter()._run_agent is run_conversation_agent


def test_adapter_passes_first_turn_context_and_preserves_trace_package() -> None:
    calls: list[tuple[str, dict]] = []

    def fake_agent(requirement: str, **kwargs):
        calls.append((requirement, kwargs))
        return {
            "success": True,
            "sql": "SELECT ID FROM T",
            "generation_mode": "authored_query",
            "markdown": "已生成",
            "trace": [
                {
                    "node": "program_generation",
                    "payload": {
                        "package": {
                            "package_id": "p",
                            "version": "1",
                            "sha256": "a" * 64,
                        }
                    },
                }
            ],
        }

    result = AgentEvaluationAdapter(run_agent_fn=fake_agent).generate(
        "统计用户", system_time="2026-08-24"
    )

    assert result.ontology_status == "generated"
    assert result.package_sha256 == "a" * 64
    assert calls[0][0] == "统计用户"
    assert calls[0][1]["history"] == []
    assert calls[0][1]["system_time"] == "2026-08-24"
    assert "assembled_context" in calls[0][1]
    assert calls[0][1]["request_id"].startswith("evaluation:")


def test_adapter_preserves_invalid_sql_as_unscorable_draft() -> None:
    def fake_agent(requirement: str, **kwargs):
        return {
            "success": False,
            "sql": "SELECT * FROM T",
            "generation_mode": "authored_draft",
            "diagnostics": [{"code": "authored_sql_invalid"}],
            "trace": [],
        }

    result = AgentEvaluationAdapter(run_agent_fn=fake_agent).generate(
        "统计用户", system_time="2026-08-24"
    )

    assert result.ontology_sql == "SELECT * FROM T"
    assert result.ontology_status == "draft"
    assert result.error_code == "authored_sql_invalid"
