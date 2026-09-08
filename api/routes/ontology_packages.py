"""Secure FastAPI boundary for the structured ontology package management core."""

# ruff: noqa: B008

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute

from api.schemas.ontology_packages import (
    CascadeDeleteRequest,
    DescriptivePatch,
    DiagnosticResolutionRequest,
    PublishRequest,
    RelationRequest,
    RevisionRequest,
    RollbackRequest,
    TemporalPolicyRequest,
)
from audit.utils import write_audit_log
from auth.jwt import get_current_user
from auth.ontology_roles import require_ontology_administrator, require_ontology_maintainer
from config.settings import settings
from models import User
from ontology_core.errors import OntologyError
from ontology_core.management.imports import UploadPayload
from ontology_core.management.service import OntologyManagementService

_UPLOAD_CHUNK_SIZE = 64 * 1024


class _ManagementRoute(APIRoute):
    """Convert management-domain failures into one stable JSON error envelope."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def wrapped(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                _audit_failure(request, "ontology_request_invalid")
                return _error(422, "ontology_request_invalid", "本体管理请求无效")
            except HTTPException as error:
                _audit_failure(request, _http_code(error))
                return _http_error(error)
            except OntologyError as error:
                _audit_failure(request, error.code)
                return _error(
                    int(getattr(error, "status_code", 400)),
                    error.code,
                    error.message,
                    _safe_details(error),
                )

        return wrapped


router = APIRouter(
    prefix="/ontology-packages", tags=["ontology-packages"], route_class=_ManagementRoute
)


def get_management_service() -> OntologyManagementService:
    """Build from external configuration without caching management state in routes."""
    return OntologyManagementService(
        Path(settings.ontology.management_root),
        repository_root=Path(__file__).resolve().parents[2],
        limits=_upload_limits(),
        import_token_ttl=_token_ttl(),
    )


@router.get("/workspaces/{workspace_id}")
def workspace_overview(
    workspace_id: str,
    user: User = Depends(require_ontology_maintainer),
    service: OntologyManagementService = Depends(get_management_service),
) -> dict[str, Any]:
    overview = service.overview(workspace_id)
    return _envelope(overview.public_data(), overview.draft.revision)


@router.get("/workspaces/{workspace_id}/imports/template")
def download_import_template(
    workspace_id: str,
    variant: str,
    user: User = Depends(require_ontology_maintainer),
    service: OntologyManagementService = Depends(get_management_service),
) -> Response:
    generated = service.import_template(workspace_id, variant)
    return Response(
        content=generated.content,
        media_type=generated.media_type,
        headers={"Content-Disposition": f'attachment; filename="{generated.file_name}"'},
    )


@router.post("/workspaces/{workspace_id}/imports/preview")
async def preview_import(
    request: Request,
    workspace_id: str,
    expected_revision: int = Form(..., ge=0),
    files: list[UploadFile] = File(...),
    user: User = Depends(require_ontology_maintainer),
    service: OntologyManagementService = Depends(get_management_service),
) -> dict[str, Any]:
    before = service.draft_revision(workspace_id)
    _audit_context(request, user, service, workspace_id, "import_preview")
    preview = service.preview_import(
        workspace_id,
        expected_revision=expected_revision,
        uploads=tuple(await _read_uploads(files, settings.ontology.max_upload_bytes)),
    )
    _audit_success(
        request,
        revision_after=before,
        counts={"objects": preview.object_count, "fields": preview.field_count},
    )
    return _envelope(preview.model_dump(mode="json"), before)


@router.post("/workspaces/{workspace_id}/imports/{token}/confirm")
def confirm_import(
    request: Request,
    workspace_id: str,
    token: str,
    payload: RevisionRequest,
    user: User = Depends(require_ontology_maintainer),
    service: OntologyManagementService = Depends(get_management_service),
) -> dict[str, Any]:
    _audit_context(request, user, service, workspace_id, "import_confirm")
    draft = service.confirm_import(workspace_id, token, expected_revision=payload.expected_revision)
    _audit_success(request, revision_after=draft.revision, counts=_counts(draft))
    return _draft_envelope(draft)


@router.get("/workspaces/{workspace_id}/objects/{object_id:path}/delete-impact")
def object_delete_impact(
    workspace_id: str,
    object_id: str,
    user: User = Depends(require_ontology_administrator),
    service: OntologyManagementService = Depends(get_management_service),
) -> dict[str, Any]:
    impact = service.object_delete_impact(workspace_id, object_id)
    return _envelope(impact.model_dump(mode="json"), service.draft_revision(workspace_id))


@router.patch("/workspaces/{workspace_id}/objects/{object_id:path}")
def patch_object(
    request: Request,
    workspace_id: str,
    object_id: str,
    payload: DescriptivePatch,
    user: User = Depends(require_ontology_maintainer),
    service: OntologyManagementService = Depends(get_management_service),
) -> dict[str, Any]:
    _audit_context(request, user, service, workspace_id, "object_patch")
    draft = service.update_object(
        workspace_id,
        object_id,
        expected_revision=payload.expected_revision,
        changes=payload.changes(),
    )
    _audit_success(request, revision_after=draft.revision, counts=_counts(draft))
    return _draft_envelope(draft)


@router.delete("/workspaces/{workspace_id}/objects/{object_id:path}")
def delete_object(
    request: Request,
    workspace_id: str,
    object_id: str,
    payload: CascadeDeleteRequest,
    user: User = Depends(require_ontology_administrator),
    service: OntologyManagementService = Depends(get_management_service),
) -> dict[str, Any]:
    impact = service.object_delete_impact(workspace_id, object_id)
    _audit_context(request, user, service, workspace_id, "object_delete")
    draft = service.delete_object(
        workspace_id,
        object_id,
        expected_revision=payload.expected_revision,
        cascade=payload.cascade,
        confirmation_name=payload.confirmation_name,
    )
    _audit_success(
        request,
        revision_after=draft.revision,
        counts=_delete_counts(impact),
    )
    return _draft_envelope(draft)


@router.get("/workspaces/{workspace_id}/fields/{field_id:path}/delete-impact")
def field_delete_impact(
    workspace_id: str,
    field_id: str,
    user: User = Depends(require_ontology_administrator),
    service: OntologyManagementService = Depends(get_management_service),
) -> dict[str, Any]:
    impact = service.field_delete_impact(workspace_id, field_id)
    return _envelope(impact.model_dump(mode="json"), service.draft_revision(workspace_id))


@router.patch("/workspaces/{workspace_id}/fields/{field_id:path}")
def patch_field(
    request: Request,
    workspace_id: str,
    field_id: str,
    payload: DescriptivePatch,
    user: User = Depends(require_ontology_maintainer),
    service: OntologyManagementService = Depends(get_management_service),
) -> dict[str, Any]:
    _audit_context(request, user, service, workspace_id, "field_patch")
    draft = service.update_field(
        workspace_id,
        field_id,
        expected_revision=payload.expected_revision,
        changes=payload.changes(),
    )
    _audit_success(request, revision_after=draft.revision, counts=_counts(draft))
    return _draft_envelope(draft)


@router.delete("/workspaces/{workspace_id}/fields/{field_id:path}")
def delete_field(
    request: Request,
    workspace_id: str,
    field_id: str,
    payload: CascadeDeleteRequest,
    user: User = Depends(require_ontology_administrator),
    service: OntologyManagementService = Depends(get_management_service),
) -> dict[str, Any]:
    impact = service.field_delete_impact(workspace_id, field_id)
    _audit_context(request, user, service, workspace_id, "field_delete")
    draft = service.delete_field(
        workspace_id,
        field_id,
        expected_revision=payload.expected_revision,
        cascade=payload.cascade,
        confirmation_name=payload.confirmation_name,
    )
    _audit_success(
        request,
        revision_after=draft.revision,
        counts=_delete_counts(impact),
    )
    return _draft_envelope(draft)


@router.put("/workspaces/{workspace_id}/relations/{relation_id:path}")
def put_relation(
    request: Request,
    workspace_id: str,
    relation_id: str,
    payload: RelationRequest,
    user: User = Depends(require_ontology_maintainer),
    service: OntologyManagementService = Depends(get_management_service),
) -> dict[str, Any]:
    _audit_context(request, user, service, workspace_id, "relation_upsert")
    draft = service.upsert_relation(
        workspace_id, payload.relation(relation_id), expected_revision=payload.expected_revision
    )
    _audit_success(request, revision_after=draft.revision, counts=_counts(draft))
    return _draft_envelope(draft)


@router.delete("/workspaces/{workspace_id}/relations/{relation_id:path}")
def delete_relation(
    request: Request,
    workspace_id: str,
    relation_id: str,
    payload: RevisionRequest,
    user: User = Depends(require_ontology_administrator),
    service: OntologyManagementService = Depends(get_management_service),
) -> dict[str, Any]:
    _audit_context(request, user, service, workspace_id, "relation_delete")
    draft = service.delete_relation(
        workspace_id, relation_id, expected_revision=payload.expected_revision
    )
    _audit_success(request, revision_after=draft.revision, counts=_counts(draft))
    return _draft_envelope(draft)


@router.put("/workspaces/{workspace_id}/temporal-policies/{object_id:path}")
def put_temporal_policy(
    request: Request,
    workspace_id: str,
    object_id: str,
    payload: TemporalPolicyRequest,
    user: User = Depends(require_ontology_maintainer),
    service: OntologyManagementService = Depends(get_management_service),
) -> dict[str, Any]:
    _audit_context(request, user, service, workspace_id, "temporal_policy_upsert")
    draft = service.upsert_temporal_policy(
        workspace_id, payload.policy(object_id), expected_revision=payload.expected_revision
    )
    _audit_success(request, revision_after=draft.revision, counts=_counts(draft))
    return _draft_envelope(draft)


@router.post("/workspaces/{workspace_id}/diagnostics/{diagnostic_id:path}/resolve")
def resolve_diagnostic(
    request: Request,
    workspace_id: str,
    diagnostic_id: str,
    payload: DiagnosticResolutionRequest,
    user: User = Depends(require_ontology_maintainer),
    service: OntologyManagementService = Depends(get_management_service),
) -> dict[str, Any]:
    _audit_context(request, user, service, workspace_id, "diagnostic_resolve")
    draft = service.resolve_diagnostic(
        workspace_id,
        diagnostic_id,
        expected_revision=payload.expected_revision,
        actor=str(user.id),
        explanation=payload.explanation,
        status=payload.status,
    )
    _audit_success(request, revision_after=draft.revision, counts=_counts(draft))
    return _draft_envelope(draft)


@router.post("/workspaces/{workspace_id}/validate")
def validate_workspace(
    workspace_id: str,
    user: User = Depends(require_ontology_maintainer),
    service: OntologyManagementService = Depends(get_management_service),
) -> dict[str, Any]:
    overview = service.overview(workspace_id)
    return _envelope(
        {"diagnostics": [item.model_dump(mode="json") for item in service.validate(workspace_id)]},
        overview.draft.revision,
    )


@router.get("/workspaces/{workspace_id}/versions")
def list_versions(
    workspace_id: str,
    user: User = Depends(require_ontology_maintainer),
    service: OntologyManagementService = Depends(get_management_service),
) -> dict[str, Any]:
    overview = service.overview(workspace_id)
    return _envelope(
        [item.model_dump(mode="json") for item in service.list_versions(workspace_id)],
        overview.draft.revision,
    )


@router.post("/workspaces/{workspace_id}/versions")
def publish_version(
    request: Request,
    workspace_id: str,
    payload: PublishRequest,
    user: User = Depends(require_ontology_administrator),
    service: OntologyManagementService = Depends(get_management_service),
) -> dict[str, Any]:
    _audit_context(request, user, service, workspace_id, "version_publish")
    summary = service.publish(
        workspace_id,
        payload.version,
        payload.release_notes,
        payload.expected_revision,
        str(user.id),
    )
    _audit_success(request, revision_after=summary.revision, counts={"versions": 1})
    return _envelope(summary.model_dump(mode="json"), summary.revision)


@router.post("/workspaces/{workspace_id}/versions/{version}/rollback")
def rollback_version(
    request: Request,
    workspace_id: str,
    version: str,
    payload: RollbackRequest,
    user: User = Depends(require_ontology_administrator),
    service: OntologyManagementService = Depends(get_management_service),
) -> dict[str, Any]:
    _audit_context(request, user, service, workspace_id, "version_rollback")
    summary = service.rollback(workspace_id, version, payload.reason, str(user.id))
    _audit_success(request, revision_after=summary.revision, counts={"versions": 1})
    return _envelope(summary.model_dump(mode="json"), summary.revision)


@router.get("/active")
def active_version(
    user: User = Depends(get_current_user),
    service: OntologyManagementService = Depends(get_management_service),
) -> dict[str, Any]:
    summary = service.active_version(settings.ontology.management_workspace)
    return _envelope(summary.model_dump(mode="json"), summary.revision)


async def _read_uploads(files: list[UploadFile], maximum_bytes: int) -> list[UploadPayload]:
    uploads: list[UploadPayload] = []
    try:
        for upload in files:
            content = bytearray()
            while chunk := await upload.read(_UPLOAD_CHUNK_SIZE):
                content.extend(chunk)
                if len(content) > maximum_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail={
                            "code": "upload_too_large",
                            "message": "上传文件超过大小限制",
                            "details": {},
                        },
                    )
            uploads.append(
                UploadPayload(file_name=upload.filename or "upload", content=bytes(content))
            )
    finally:
        for upload in files:
            await upload.close()
    return uploads


def _envelope(data: Any, revision: int | None) -> dict[str, Any]:
    return {"data": data, "revision": revision}


def _draft_envelope(draft) -> dict[str, Any]:
    from ontology_core.management.temporal import effective_temporal_policies

    return _envelope(
        {
            "objects": [item.model_dump(mode="json") for item in draft.objects],
            "relations": [item.model_dump(mode="json") for item in draft.relations],
            "temporal_policies": [
                item.model_dump(mode="json") for item in effective_temporal_policies(draft)
            ],
        },
        draft.revision,
    )


def _counts(draft) -> dict[str, int]:
    from ontology_core.management.temporal import effective_temporal_policies

    return {
        "objects": len(draft.objects),
        "fields": sum(len(item.fields) for item in draft.objects),
        "relations": len(draft.relations),
        "temporal_policies": len(effective_temporal_policies(draft)),
    }


def _delete_counts(impact) -> dict[str, int]:
    return {
        "objects": impact.object_count,
        "fields": impact.field_count,
        "relations": impact.relation_count,
        "temporal_policies": impact.temporal_policy_count,
    }


def _upload_limits():
    from ontology_core.management.models import UploadLimits

    return UploadLimits(
        max_upload_bytes=settings.ontology.max_upload_bytes,
        max_xlsx_uncompressed_bytes=settings.ontology.max_xlsx_uncompressed_bytes,
    )


def _token_ttl():
    from datetime import timedelta

    return timedelta(seconds=settings.ontology.import_token_ttl_seconds)


def _error(
    status_code: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "details": details or {}},
    )


def _http_code(error: HTTPException) -> str:
    return (
        error.detail.get("code", "ontology_request_forbidden")
        if isinstance(error.detail, dict)
        else "authentication_required"
    )


def _http_error(error: HTTPException) -> JSONResponse:
    if isinstance(error.detail, dict):
        return _error(
            error.status_code,
            error.detail.get("code", "ontology_request_forbidden"),
            error.detail.get("message", "本体管理请求被拒绝"),
            error.detail.get("details", {}),
        )
    return _error(error.status_code, "authentication_required", "需要有效身份凭据")


def _safe_details(error: OntologyError) -> dict[str, Any]:
    details = error.details
    if set(details).issubset({"current_revision", "operation"}):
        return details
    return {}


def _audit_context(
    request: Request,
    user: User,
    service: OntologyManagementService,
    workspace_id: str,
    action: str,
) -> None:
    request.state.ontology_audit = {
        "user_id": user.id,
        "workspace_id": workspace_id,
        "action": action,
        "revision_before": service.draft_revision(workspace_id),
        "service": service,
    }


def _audit_success(request: Request, *, revision_after: int | None, counts: dict[str, int]) -> None:
    context = getattr(request.state, "ontology_audit", None)
    if context is None:
        return
    write_audit_log(
        context["user_id"],
        context["action"],
        detail={
            "workspace_id": context["workspace_id"],
            "revision_before": context["revision_before"],
            "revision_after": revision_after,
            "action": context["action"],
            "result": "success",
            "time": datetime.now(UTC).isoformat(),
            "counts": counts,
        },
    )


def _audit_failure(request: Request, result: str) -> None:
    context = getattr(request.state, "ontology_audit", None)
    if context is None:
        return
    try:
        revision_after = context["service"].draft_revision(context["workspace_id"])
    except OntologyError:
        revision_after = context["revision_before"]
    write_audit_log(
        context["user_id"],
        context["action"],
        detail={
            "workspace_id": context["workspace_id"],
            "revision_before": context["revision_before"],
            "revision_after": revision_after,
            "action": context["action"],
            "result": result,
            "time": datetime.now(UTC).isoformat(),
            "counts": {},
        },
        status="failed",
    )
