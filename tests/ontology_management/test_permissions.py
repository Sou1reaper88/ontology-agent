"""Management API authorization, error privacy, and disabled-root tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes.ontology_packages import get_management_service
from audit.middleware import _safe_audit_query
from auth.jwt import create_access_token, get_current_user
from auth.ontology_roles import require_ontology_administrator, require_ontology_maintainer
from config.settings import settings
from models import Role, User
from ontology_core.management.service import OntologyManagementService


def _user(role_name: str) -> User:
    return User(
        id=202,
        username=f"{role_name}-user",
        display_name="Synthetic permission user",
        password_hash="not-used",
        role_id=2,
        role=Role(id=2, name=role_name),
        status=1,
    )


@pytest.mark.parametrize(
    ("role_name", "dependency", "allowed"),
    [
        ("地市生产岗", require_ontology_maintainer, False),
        ("本体维护者", require_ontology_maintainer, True),
        ("全省管理员", require_ontology_maintainer, True),
        ("本体维护者", require_ontology_administrator, False),
        ("全省管理员", require_ontology_administrator, True),
    ],
)
def test_role_dependencies_use_exact_current_database_role_names(
    role_name: str, dependency, allowed: bool
) -> None:
    user = _user(role_name)
    if allowed:
        assert dependency(user) is user
    else:
        with pytest.raises(Exception) as error:
            dependency(user)
        assert getattr(error.value, "status_code", None) == 403
        assert getattr(error.value, "detail", {}).get("code") in {
            "ontology_maintainer_required",
            "ontology_administrator_required",
        }


def test_loaded_database_role_overrides_stale_jwt_role_claim() -> None:
    class _Database:
        def get(self, model, user_id):
            assert model is User
            assert user_id == 202
            return _user("地市生产岗")

    token = create_access_token(202, "synthetic", role_id=999)
    current = get_current_user(token=token, db=_Database())

    with pytest.raises(Exception) as error:
        require_ontology_maintainer(current)
    assert getattr(error.value, "detail", {}).get("code") == "ontology_maintainer_required"


def test_active_endpoint_is_authenticated_but_workspace_access_requires_maintainer() -> None:
    app.dependency_overrides[get_current_user] = lambda: _user("地市生产岗")
    try:
        with TestClient(app) as client:
            active = client.get("/ontology-packages/active")
            workspace = client.get("/ontology-packages/workspaces/evaluation")
    finally:
        app.dependency_overrides.clear()

    assert active.status_code != 401
    assert workspace.status_code == 403
    assert workspace.json()["code"] == "ontology_maintainer_required"


def test_missing_management_root_disables_writes_without_breaking_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings.ontology, "management_root", "")
    app.dependency_overrides[get_current_user] = lambda: _user("本体维护者")
    try:
        with TestClient(app) as client:
            health = client.get("/health")
            ready = client.get("/ready")
            blocked_write = client.patch(
                "/ontology-packages/workspaces/evaluation/objects/object/synthetic",
                json={"expected_revision": 0, "label": "Synthetic"},
            )
    finally:
        app.dependency_overrides.clear()
    assert health.status_code == 200
    assert ready.status_code == 200
    assert ready.json()["ontology"] == "degraded"
    assert blocked_write.status_code == 503
    assert blocked_write.json()["code"] == "ontology_management_unavailable"


def test_error_responses_never_leak_upload_text_ttl_or_management_root(
    tmp_path: Path,
) -> None:
    service = OntologyManagementService(tmp_path / "outside")
    app.dependency_overrides[get_management_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: _user("本体维护者")
    secret = "RAW_UPLOAD_SECRET"
    try:
        with TestClient(app) as client:
            response = client.post(
                "/ontology-packages/workspaces/missing/imports/preview",
                data={"expected_revision": "0"},
                files=[("files", ("input.tsv", secret.encode("utf-8"), "text/plain"))],
            )
    finally:
        app.dependency_overrides.clear()

    serialized = response.text
    assert response.status_code in {404, 422}
    assert secret not in serialized
    assert str(tmp_path) not in serialized
    assert "ttl" not in serialized.casefold()


def test_management_http_audit_never_records_query_values() -> None:
    assert _safe_audit_query("/ontology-packages/active", "token=synthetic-secret") is None
    assert _safe_audit_query("/health", "probe=1") == "probe=1"
