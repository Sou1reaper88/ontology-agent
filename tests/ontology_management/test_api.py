"""FastAPI management boundaries backed by the real ontology package services."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.main import app
from api.routes import ontology_packages
from api.routes.ontology_packages import _read_uploads, get_management_service
from auth.jwt import get_current_user
from models import Role, User
from ontology_core.management.models import DraftDataSource, WorkspaceDraft
from ontology_core.management.service import OntologyManagementService
from ontology_core.management.store import FileDraftStore

HEADER = "对象英文名称\t对象中文名称\t对象描述\t属性英文名\t属性中文名\t属性类型\t属性描述\n"
ACCOUNT = (
    HEADER + "SYNTHETIC_ACCOUNT\t合成账户\t合成账户表\tACCOUNT_ID\t账户标识\tbigint\t合成稳定键\n"
)
ORDER = HEADER + "SYNTHETIC_ORDER\t合成订单\t合成订单表\tACCOUNT_ID\t账户标识\tbigint\t合成关联键\n"


def _draft() -> WorkspaceDraft:
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


def _user(role_name: str) -> User:
    return User(
        id=101,
        username=f"{role_name}-user",
        display_name="Synthetic API user",
        password_hash="not-used",
        role_id=1,
        role=Role(id=1, name=role_name),
    )


@pytest.fixture()
def management_service(tmp_path: Path) -> OntologyManagementService:
    root = tmp_path / "external-management-root"
    store = FileDraftStore(root)
    store.create_workspace(_draft())
    return OntologyManagementService(root)


@pytest.fixture()
def management_client(management_service: OntologyManagementService):
    role_name = ["本体维护者"]
    app.dependency_overrides[get_management_service] = lambda: management_service
    app.dependency_overrides[get_current_user] = lambda: _user(role_name[0])
    try:
        with TestClient(app) as client:
            yield client, role_name
    finally:
        app.dependency_overrides.clear()


def _multipart(revision: int) -> dict[str, str]:
    return {"expected_revision": str(revision)}


def test_upload_streams_are_all_closed_when_byte_cap_rejects_one_file() -> None:
    class Stream:
        def __init__(self, content: bytes) -> None:
            self.filename = "synthetic.tsv"
            self._content = content
            self.closed = False

        async def read(self, size: int) -> bytes:
            content, self._content = self._content, b""
            return content

        async def close(self) -> None:
            self.closed = True

    oversized = Stream(b"12345")
    untouched = Stream(b"123")

    with pytest.raises(HTTPException) as error:
        asyncio.run(_read_uploads([oversized, untouched], maximum_bytes=4))

    assert error.value.status_code == 413
    assert oversized.closed is True
    assert untouched.closed is True


def test_management_api_composes_existing_services_without_route_domain_logic(
    management_client: tuple[TestClient, list[str]],
) -> None:
    client, role_name = management_client
    preview = client.post(
        "/ontology-packages/workspaces/evaluation/imports/preview",
        data=_multipart(0),
        files=[
            ("files", ("accounts.tsv", ACCOUNT.encode("utf-8"), "text/tab-separated-values")),
            ("files", ("orders.tsv", ORDER.encode("utf-8"), "text/tab-separated-values")),
        ],
    )
    assert preview.status_code == 200, preview.text
    preview_data = preview.json()["data"]
    assert preview_data["status"] == "ready"
    assert preview_data["object_count"] == 2
    assert preview.json()["revision"] == 0

    confirmed = client.post(
        f"/ontology-packages/workspaces/evaluation/imports/{preview_data['token']}/confirm",
        json={"expected_revision": 0},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["revision"] == 1

    overview = client.get("/ontology-packages/workspaces/evaluation")
    assert overview.status_code == 200, overview.text
    objects = overview.json()["data"]["objects"]
    account, order = objects
    assert overview.json()["revision"] == 1

    object_patch = client.patch(
        f"/ontology-packages/workspaces/evaluation/objects/{account['id']}",
        json={"expected_revision": 1, "label": "合成账户新名称"},
    )
    assert object_patch.status_code == 200, object_patch.text
    assert object_patch.json()["revision"] == 2

    account_field = account["fields"][0]
    field_patch = client.patch(
        f"/ontology-packages/workspaces/evaluation/fields/{account_field['id']}",
        json={"expected_revision": 2, "description": "合成账户键说明"},
    )
    assert field_patch.status_code == 200, field_patch.text
    assert field_patch.json()["revision"] == 3

    relation = client.put(
        "/ontology-packages/workspaces/evaluation/relations/relation/synthetic-order-account",
        json={
            "expected_revision": 3,
            "label": "订单关联账户",
            "source_object_id": order["id"],
            "source_field_id": order["fields"][0]["id"],
            "target_object_id": account["id"],
            "target_field_id": account_field["id"],
            "cardinality": "many_to_one",
            "confirmed": True,
        },
    )
    assert relation.status_code == 200, relation.text
    assert relation.json()["revision"] == 4

    policy = client.put(
        f"/ontology-packages/workspaces/evaluation/temporal-policies/{order['id']}",
        json={
            "expected_revision": 4,
            "partition_field_id": order["fields"][0]["id"],
            "grain": "day",
            "default_strategy": "t_minus_2",
            "allow_query_override": False,
        },
    )
    assert policy.status_code == 200, policy.text
    assert policy.json()["revision"] == 5

    validation = client.post("/ontology-packages/workspaces/evaluation/validate")
    assert validation.status_code == 200, validation.text
    assert validation.json()["revision"] == 5

    role_name[0] = "全省管理员"
    published = client.post(
        "/ontology-packages/workspaces/evaluation/versions",
        json={
            "version": "1.0.0",
            "release_notes": "synthetic first release",
            "expected_revision": 5,
        },
    )
    assert published.status_code == 200, published.text
    assert published.json()["data"]["version"] == "1.0.0"
    published_summary = published.json()["data"]
    assert published_summary["counts"]["concepts"] == 2
    assert published_summary["counts"]["properties"] == 2
    assert published_summary["counts"]["relations"] == 1
    assert published_summary["counts"]["temporal_policies"] == 1
    assert len(published_summary["content_digest"]) == 64
    assert set(published_summary["content_digest"]) <= set("0123456789abcdef")

    active = client.get("/ontology-packages/active")
    assert active.status_code == 200, active.text
    assert active.json() == {
        "data": published.json()["data"],
        "revision": published.json()["revision"],
    }

    role_name[0] = "本体维护者"
    versions = client.get("/ontology-packages/workspaces/evaluation/versions")
    assert versions.status_code == 200, versions.text
    assert versions.json()["data"][0]["active"] is True

    role_name[0] = "全省管理员"
    rollback = client.post(
        "/ontology-packages/workspaces/evaluation/versions/1.0.0/rollback",
        json={"reason": "synthetic rollback verification"},
    )
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["data"]["version"] == "1.0.0"


def test_maintainer_cannot_publish(management_client: tuple[TestClient, list[str]]) -> None:
    client, _ = management_client

    response = client.post(
        "/ontology-packages/workspaces/evaluation/versions",
        json={"version": "1.0.0", "release_notes": "synthetic", "expected_revision": 0},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "ontology_administrator_required"


def test_fresh_service_injects_durable_published_identifiers_into_editor(
    management_service: OntologyManagementService,
) -> None:
    preview = management_service.preview_import(
        "evaluation",
        expected_revision=0,
        uploads=(management_service.upload_payload("accounts.tsv", ACCOUNT.encode("utf-8")),),
    )
    assert preview.token is not None
    imported = management_service.confirm_import("evaluation", preview.token, expected_revision=0)
    published = management_service.publish(
        "evaluation", "1.0.0", "synthetic first release", imported.revision, "admin"
    )
    assert published.version == "1.0.0"

    restarted = OntologyManagementService(management_service.root)
    draft = restarted.overview("evaluation").draft
    object_id = draft.objects[0].id
    field_id = draft.objects[0].fields[0].id

    with pytest.raises(Exception) as object_error:
        restarted.delete_object("evaluation", object_id, expected_revision=draft.revision)
    assert getattr(object_error.value, "code", None) == "draft_edit_published_identifier"

    with pytest.raises(Exception) as field_error:
        restarted.delete_field("evaluation", field_id, expected_revision=draft.revision)
    assert getattr(field_error.value, "code", None) == "draft_edit_published_identifier"


def test_unknown_field_patch_and_delete_return_stable_not_found_envelopes(
    management_client: tuple[TestClient, list[str]],
) -> None:
    client, role_name = management_client
    unknown_field_url = "/ontology-packages/workspaces/evaluation/fields/field/missing"

    patched = client.patch(
        unknown_field_url,
        json={"expected_revision": 0, "label": "Synthetic missing field"},
    )

    role_name[0] = "全省管理员"
    deleted = client.request("DELETE", unknown_field_url, json={"expected_revision": 0})

    expected = {"code": "draft_field_not_found", "message": "未找到属性", "details": {}}
    assert patched.status_code == 404
    assert patched.json() == expected
    assert deleted.status_code == 404
    assert deleted.json() == expected


def test_draft_revision_reads_the_stored_draft_revision(
    management_service: OntologyManagementService,
) -> None:
    assert management_service.draft_revision("evaluation") == 0


def test_write_audit_records_stored_revisions_for_success_and_stale_conflict(
    management_client: tuple[TestClient, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = management_client
    preview = client.post(
        "/ontology-packages/workspaces/evaluation/imports/preview",
        data=_multipart(0),
        files=[("files", ("accounts.tsv", ACCOUNT.encode("utf-8"), "text/tab-separated-values"))],
    )
    assert preview.status_code == 200, preview.text
    confirmed = client.post(
        f"/ontology-packages/workspaces/evaluation/imports/{preview.json()['data']['token']}/confirm",
        json={"expected_revision": 0},
    )
    assert confirmed.status_code == 200, confirmed.text
    object_id = confirmed.json()["data"]["objects"][0]["id"]
    records: list[dict[str, object]] = []

    def capture(user_id, action, *, detail=None, status="success", **unused) -> None:
        records.append({"user_id": user_id, "action": action, "detail": detail, "status": status})

    monkeypatch.setattr(ontology_packages, "write_audit_log", capture)
    successful = client.patch(
        f"/ontology-packages/workspaces/evaluation/objects/{object_id}",
        json={"expected_revision": 1, "label": "Synthetic renamed object"},
    )
    conflict = client.patch(
        f"/ontology-packages/workspaces/evaluation/objects/{object_id}",
        json={"expected_revision": 0, "label": "Synthetic stale object"},
    )

    assert successful.status_code == 200, successful.text
    assert conflict.status_code == 409, conflict.text
    assert records[0]["detail"] == {
        "workspace_id": "evaluation",
        "revision_before": 1,
        "revision_after": 2,
        "action": "object_patch",
        "result": "success",
        "time": records[0]["detail"]["time"],
        "counts": {"objects": 1, "fields": 1, "relations": 0, "temporal_policies": 0},
    }
    assert records[1]["detail"] == {
        "workspace_id": "evaluation",
        "revision_before": 2,
        "revision_after": 2,
        "action": "object_patch",
        "result": "draft_revision_conflict",
        "time": records[1]["detail"]["time"],
        "counts": {},
    }
    assert records[1]["status"] == "failed"


def test_expired_import_confirmation_audit_uses_the_stored_revision(
    management_client: tuple[TestClient, list[str]],
    management_service: OntologyManagementService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = management_client
    preview = client.post(
        "/ontology-packages/workspaces/evaluation/imports/preview",
        data=_multipart(0),
        files=[("files", ("accounts.tsv", ACCOUNT.encode("utf-8"), "text/tab-separated-values"))],
    )
    assert preview.status_code == 200, preview.text
    records: list[dict[str, object]] = []

    def capture(user_id, action, *, detail=None, status="success", **unused) -> None:
        records.append({"user_id": user_id, "action": action, "detail": detail, "status": status})

    monkeypatch.setattr(ontology_packages, "write_audit_log", capture)
    management_service._imports._now = lambda: datetime.now(UTC) + timedelta(hours=1)
    expired = client.post(
        f"/ontology-packages/workspaces/evaluation/imports/{preview.json()['data']['token']}/confirm",
        json={"expected_revision": 0},
    )

    assert expired.status_code == 410, expired.text
    assert records[0]["detail"] == {
        "workspace_id": "evaluation",
        "revision_before": 0,
        "revision_after": 0,
        "action": "import_confirm",
        "result": "import_token_expired",
        "time": records[0]["detail"]["time"],
        "counts": {},
    }
    assert records[0]["status"] == "failed"


def test_maintainer_can_resolve_a_confirmation_diagnostic(
    management_client: tuple[TestClient, list[str]],
) -> None:
    client, _ = management_client
    preview = client.post(
        "/ontology-packages/workspaces/evaluation/imports/preview",
        data=_multipart(0),
        files=[
            ("files", ("accounts.tsv", ACCOUNT.encode("utf-8"), "text/tab-separated-values")),
            ("files", ("orders.tsv", ORDER.encode("utf-8"), "text/tab-separated-values")),
        ],
    )
    assert preview.status_code == 200, preview.text
    confirmed = client.post(
        f"/ontology-packages/workspaces/evaluation/imports/{preview.json()['data']['token']}/confirm",
        json={"expected_revision": 0},
    )
    assert confirmed.status_code == 200, confirmed.text
    account, order = confirmed.json()["data"]["objects"]
    relation = client.put(
        "/ontology-packages/workspaces/evaluation/relations/relation/synthetic-unconfirmed",
        json={
            "expected_revision": 1,
            "source_object_id": order["id"],
            "source_field_id": order["fields"][0]["id"],
            "target_object_id": account["id"],
            "target_field_id": account["fields"][0]["id"],
            "cardinality": "many_to_one",
            "confirmed": False,
        },
    )
    assert relation.status_code == 200, relation.text
    diagnostics = client.get("/ontology-packages/workspaces/evaluation")
    assert diagnostics.status_code == 200, diagnostics.text
    diagnostic_id = next(
        item["id"]
        for item in diagnostics.json()["data"]["diagnostics"]
        if item["severity"] == "confirmation_required"
    )

    resolved = client.post(
        f"/ontology-packages/workspaces/evaluation/diagnostics/{diagnostic_id}/resolve",
        json={
            "expected_revision": 2,
            "explanation": "Synthetic confirmation evidence",
            "status": "resolved",
        },
    )

    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["revision"] == 3


def test_administrator_can_delete_a_draft_relation(
    management_client: tuple[TestClient, list[str]],
) -> None:
    client, role_name = management_client
    preview = client.post(
        "/ontology-packages/workspaces/evaluation/imports/preview",
        data=_multipart(0),
        files=[
            ("files", ("accounts.tsv", ACCOUNT.encode("utf-8"), "text/tab-separated-values")),
            ("files", ("orders.tsv", ORDER.encode("utf-8"), "text/tab-separated-values")),
        ],
    )
    assert preview.status_code == 200, preview.text
    confirmed = client.post(
        f"/ontology-packages/workspaces/evaluation/imports/{preview.json()['data']['token']}/confirm",
        json={"expected_revision": 0},
    )
    assert confirmed.status_code == 200, confirmed.text
    account, order = confirmed.json()["data"]["objects"]
    relation_id = "relation/synthetic-delete"
    created = client.put(
        f"/ontology-packages/workspaces/evaluation/relations/{relation_id}",
        json={
            "expected_revision": 1,
            "source_object_id": order["id"],
            "source_field_id": order["fields"][0]["id"],
            "target_object_id": account["id"],
            "target_field_id": account["fields"][0]["id"],
            "cardinality": "many_to_one",
            "confirmed": True,
        },
    )
    assert created.status_code == 200, created.text

    role_name[0] = "全省管理员"
    deleted = client.request(
        "DELETE",
        f"/ontology-packages/workspaces/evaluation/relations/{relation_id}",
        json={"expected_revision": 2},
    )

    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["revision"] == 3
    assert deleted.json()["data"]["relations"] == []


def test_publish_blocked_by_diagnostics_returns_safe_422_envelope(
    management_client: tuple[TestClient, list[str]],
) -> None:
    client, role_name = management_client
    preview = client.post(
        "/ontology-packages/workspaces/evaluation/imports/preview",
        data=_multipart(0),
        files=[
            ("files", ("accounts.tsv", ACCOUNT.encode("utf-8"), "text/tab-separated-values")),
            ("files", ("orders.tsv", ORDER.encode("utf-8"), "text/tab-separated-values")),
        ],
    )
    assert preview.status_code == 200, preview.text
    confirmed = client.post(
        f"/ontology-packages/workspaces/evaluation/imports/{preview.json()['data']['token']}/confirm",
        json={"expected_revision": 0},
    )
    assert confirmed.status_code == 200, confirmed.text
    account, order = confirmed.json()["data"]["objects"]
    relation = client.put(
        "/ontology-packages/workspaces/evaluation/relations/relation/synthetic-blocked-publish",
        json={
            "expected_revision": 1,
            "source_object_id": order["id"],
            "source_field_id": order["fields"][0]["id"],
            "target_object_id": account["id"],
            "target_field_id": account["fields"][0]["id"],
            "cardinality": "many_to_one",
            "confirmed": False,
        },
    )
    assert relation.status_code == 200, relation.text

    role_name[0] = "全省管理员"
    response = client.post(
        "/ontology-packages/workspaces/evaluation/versions",
        json={
            "version": "1.0.0",
            "release_notes": "RAW_RELEASE_NOTE_SECRET",
            "expected_revision": 2,
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": "draft_not_publishable",
        "message": "草稿尚未满足发布条件",
        "details": {},
    }
    assert "RAW_RELEASE_NOTE_SECRET" not in response.text
    assert "SYNTHETIC_ACCOUNT" not in response.text
