"""健康检查接口测试。"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.main as main_module
from agent.ontology_shadow import RuntimeHealth
from api.main import app
from config.settings import OntologySettings


def test_health() -> None:
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready() -> None:
    with TestClient(app) as client:
        resp = client.get("/ready")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["database"] == "ok"
    assert payload["ontology"] in {"ok", "degraded"}
    assert payload["status"] == ("ok" if payload["ontology"] == "ok" else "degraded")


def test_ready_reports_bootstrap_reason_without_triggering_recovery(monkeypatch) -> None:
    monkeypatch.setattr(
        main_module,
        "get_runtime_health",
        lambda _app: RuntimeHealth(
            status="degraded",
            reason="ontology_runtime_bootstrap_failed",
        ),
        raising=False,
    )

    def fail_if_recovered_during_request():
        raise AssertionError("/ready must not recover ontology state")

    monkeypatch.setattr(
        "api.routes.ontology_packages.get_management_service",
        fail_if_recovered_during_request,
    )

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["ontology"] == "degraded"
    assert response.json()["ontology_reason"] == "ontology_runtime_bootstrap_failed"


def test_lifespan_recovers_once(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        main_module,
        "bootstrap_runtime",
        lambda: calls.append("recover")
        or RuntimeHealth(status="degraded", reason="not_loaded"),
        raising=False,
    )

    with TestClient(app):
        assert calls == ["recover"]


def test_management_configured_requires_non_blank_root() -> None:
    assert OntologySettings(management_root="").management_configured is False
    assert OntologySettings(management_root="   ").management_configured is False
    assert OntologySettings(management_root="D:/ontology-management").management_configured is True


def test_runtime_health_uses_startup_reason_while_runtime_is_not_loaded(monkeypatch) -> None:
    application = FastAPI()
    application.state.ontology_bootstrap = RuntimeHealth(
        status="degraded",
        reason="ontology_management_configuration_error",
    )
    monkeypatch.setattr(
        main_module,
        "get_ontology_runtime",
        lambda: SimpleNamespace(
            health=lambda: RuntimeHealth(status="degraded", reason="not_loaded")
        ),
    )

    assert main_module.get_runtime_health(application).reason == (
        "ontology_management_configuration_error"
    )


def test_runtime_health_does_not_hide_later_degradation(monkeypatch) -> None:
    application = FastAPI()
    application.state.ontology_bootstrap = RuntimeHealth(
        status="ok",
        package_id="synthetic.package",
        version="1.0.0",
        sha256="a" * 64,
    )
    monkeypatch.setattr(
        main_module,
        "get_ontology_runtime",
        lambda: SimpleNamespace(
            health=lambda: RuntimeHealth(
                status="degraded",
                reason="published_version_not_found",
            )
        ),
    )

    health = main_module.get_runtime_health(application)

    assert health.status == "degraded"
    assert health.reason == "published_version_not_found"
