"""Management API authorization, error privacy, and disabled-root tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import api.main as main_module
from agent.ontology_shadow import RuntimeHealth
from api.main import app
from api.routes import ontology
from api.routes.ontology_packages import get_management_service
from audit.middleware import _safe_audit_query
from auth.jwt import create_access_token, get_current_user
from auth.ontology_roles import require_ontology_administrator, require_ontology_maintainer
from config.settings import settings
from models import Role, User
from models.base import SessionLocal
from ontology_core.management.models import DraftDataSource, WorkspaceDraft
from ontology_core.management.service import OntologyManagementService
from ontology_core.management.store import FileDraftStore


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


def _workspace() -> WorkspaceDraft:
    return WorkspaceDraft(
        workspace_id="evaluation",
        display_name="Synthetic evaluation",
        package_id="tests.evaluation",
        base_uri="https://example.invalid/tests/evaluation/",
        revision=0,
        updated_at=datetime(2026, 8, 26, tzinfo=UTC),
        data_source=DraftDataSource(
            id="source/evaluation",
            label="Synthetic source",
            platform_type="generic_sql",
            dialect="generic",
            physical_namespace="synthetic",
        ),
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
    expected_legacy_body = [
        {
            "id": 41,
            "source_table": "SYNTHETIC_SOURCE",
            "source_field": "SOURCE_ID",
            "target_table": "SYNTHETIC_TARGET",
            "target_field": "TARGET_ID",
            "relation_type": "many_to_one",
            "relation_label": "Synthetic legacy relation",
        }
    ]

    class LegacyCursor:
        def execute(self, statement: str) -> None:
            assert "FROM ontology_relations" in statement

        def fetchall(self) -> list[tuple[object, ...]]:
            return [
                (
                    41,
                    "SYNTHETIC_SOURCE",
                    "SOURCE_ID",
                    "SYNTHETIC_TARGET",
                    "TARGET_ID",
                    "many_to_one",
                    "Synthetic legacy relation",
                )
            ]

    class LegacyConnection:
        def cursor(self) -> LegacyCursor:
            return LegacyCursor()

        def close(self) -> None:
            return None

    monkeypatch.setattr(settings.ontology, "management_root", "")
    monkeypatch.setattr(
        main_module,
        "get_ontology_runtime",
        lambda: SimpleNamespace(
            health=lambda: RuntimeHealth(status="degraded", reason="not_loaded")
        ),
    )
    monkeypatch.setattr(ontology, "_conn", lambda database: LegacyConnection())
    app.dependency_overrides[get_current_user] = lambda: _user("本体维护者")
    try:
        with TestClient(app) as client:
            health = client.get("/health")
            ready = client.get("/ready")
            blocked_write = client.patch(
                "/ontology-packages/workspaces/evaluation/objects/object/synthetic",
                json={"expected_revision": 0, "label": "Synthetic"},
            )
            legacy = client.get("/ontology/relations")
    finally:
        app.dependency_overrides.clear()
    assert health.status_code == 200
    assert ready.status_code == 200
    assert ready.json()["ontology"] == "degraded"
    assert blocked_write.status_code == 503
    assert blocked_write.json()["code"] == "ontology_management_unavailable"
    assert legacy.status_code == 200
    assert legacy.json() == expected_legacy_body


def test_request_roles_use_current_persisted_users_not_jwt_role_claims(
    tmp_path: Path,
) -> None:
    root = tmp_path / "external-management-root"
    store = FileDraftStore(root)
    store.create_workspace(_workspace())
    management_service = OntologyManagementService(root)
    db = SessionLocal()
    created_roles: list[Role] = []
    created_users: list[User] = []
    try:
        roles: dict[str, Role] = {}
        for name in ("地市生产岗", "本体维护者", "全省管理员"):
            role = db.query(Role).filter(Role.name == name).one_or_none()
            if role is None:
                role = Role(name=name, description="Synthetic request role")
                db.add(role)
                db.flush()
                created_roles.append(role)
            roles[name] = role
        suffix = uuid4().hex[:8]
        for index, (role_name, role) in enumerate(roles.items(), start=1):
            user = User(
                username=f"ontology-role-api-{suffix}-{index}",
                display_name=f"Synthetic {role_name}",
                password_hash="not-used",
                role_id=role.id,
                status=1,
            )
            db.add(user)
            created_users.append(user)
        db.commit()
        for user in created_users:
            db.refresh(user)
        tokens = {
            user.role.name: create_access_token(user.id, user.username, role_id=999)
            for user in created_users
        }
        app.dependency_overrides[get_management_service] = lambda: management_service
        with TestClient(app) as client:
            producer_workspace = client.get(
                "/ontology-packages/workspaces/evaluation",
                headers={"Authorization": f"Bearer {tokens['地市生产岗']}"},
            )
            maintainer_workspace = client.get(
                "/ontology-packages/workspaces/evaluation",
                headers={"Authorization": f"Bearer {tokens['本体维护者']}"},
            )
            maintainer_publish = client.post(
                "/ontology-packages/workspaces/evaluation/versions",
                json={"version": "1.0.0", "release_notes": "Synthetic", "expected_revision": 0},
                headers={"Authorization": f"Bearer {tokens['本体维护者']}"},
            )
            administrator_workspace = client.get(
                "/ontology-packages/workspaces/evaluation",
                headers={"Authorization": f"Bearer {tokens['全省管理员']}"},
            )
    finally:
        app.dependency_overrides.clear()
        for user in created_users:
            attached = db.get(User, user.id)
            if attached is not None:
                db.delete(attached)
        db.flush()
        for role in created_roles:
            attached = db.get(Role, role.id)
            if attached is not None:
                db.delete(attached)
        db.commit()
        db.close()

    assert producer_workspace.status_code == 403
    assert producer_workspace.json()["code"] == "ontology_maintainer_required"
    assert maintainer_workspace.status_code == 200
    assert maintainer_publish.status_code == 403
    assert maintainer_publish.json()["code"] == "ontology_administrator_required"
    assert administrator_workspace.status_code == 200


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
