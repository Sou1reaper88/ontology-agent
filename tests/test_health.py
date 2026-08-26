"""健康检查接口测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready() -> None:
    resp = client.get("/ready")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["database"] == "ok"
    assert payload["ontology"] in {"ok", "degraded"}
    assert payload["status"] == ("ok" if payload["ontology"] == "ok" else "degraded")
