"""Authenticated APIs for deterministic, non-executing SQL evaluations."""

# ruff: noqa: B008

from __future__ import annotations

import threading
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from api.schemas.evaluations import (
    EvaluationCaseDetail,
    EvaluationCaseSummary,
    EvaluationRunSummary,
)
from auth.jwt import get_current_user
from config.settings import settings
from evaluation.importer import (
    WorkbookValidationError,
    build_evaluation_template,
    import_evaluation_workbook,
)
from evaluation.runner import EvaluationRunner
from models import EvaluationCase, EvaluationRun, SessionLocal, User, get_db

router = APIRouter(prefix="/evaluations", tags=["evaluations"])
_UPLOAD_CHUNK_SIZE = 64 * 1024


def _run_summary(run: EvaluationRun) -> dict[str, Any]:
    return EvaluationRunSummary.model_validate(run).model_dump(mode="json")


def _owned_run(run_id: int, user: User, db: Session) -> EvaluationRun:
    run = (
        db.query(EvaluationRun)
        .filter(EvaluationRun.id == run_id, EvaluationRun.user_id == user.id)
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="评测任务不存在")
    return run


def _owned_case(
    run_id: int,
    case_id: int,
    user: User,
    db: Session,
) -> EvaluationCase:
    _owned_run(run_id, user, db)
    case = (
        db.query(EvaluationCase)
        .filter(EvaluationCase.id == case_id, EvaluationCase.run_id == run_id)
        .first()
    )
    if case is None:
        raise HTTPException(status_code=404, detail="评测案例不存在")
    return case


def _comparison(case: EvaluationCase, path: str) -> dict:
    value = case.legacy_comparison if path == "legacy" else case.ontology_comparison
    return value if isinstance(value, dict) else {}


def _case_summary(case: EvaluationCase) -> dict[str, Any]:
    legacy = _comparison(case, "legacy")
    ontology = _comparison(case, "ontology")
    diagnoses = case.diagnosis_codes if isinstance(case.diagnosis_codes, dict) else {}
    ontology_diagnoses = diagnoses.get("ontology") or []
    legacy_diagnoses = diagnoses.get("legacy") or []
    primary = (ontology_diagnoses or legacy_diagnoses or [None])[0]
    return EvaluationCaseSummary(
        id=case.id,
        case_number=case.case_number,
        generation_status=case.generation_status,
        ontology_status=case.ontology_status,
        legacy_score=legacy.get("score"),
        legacy_strict_pass=bool(legacy.get("strict_pass")),
        ontology_score=ontology.get("score"),
        ontology_strict_pass=bool(ontology.get("strict_pass")),
        primary_diagnosis=primary,
        manual_review=bool(legacy.get("manual_review") or ontology.get("manual_review")),
        duration_ms=case.duration_ms,
    ).model_dump(mode="json")


def _case_detail(case: EvaluationCase) -> dict[str, Any]:
    return EvaluationCaseDetail(
        **_case_summary(case),
        requirement=case.requirement,
        reference_sql=case.reference_sql,
        legacy_sql=case.legacy_sql,
        ontology_sql=case.ontology_sql,
        reference_structure=case.reference_structure,
        legacy_structure=case.legacy_structure,
        ontology_structure=case.ontology_structure,
        legacy_comparison=case.legacy_comparison,
        ontology_comparison=case.ontology_comparison,
        diagnosis_codes=case.diagnosis_codes,
        ontology_evidence=case.ontology_evidence,
        temporal_decisions=case.temporal_decisions,
        error_code=case.error_code,
    ).model_dump(mode="json")


async def _read_upload(file: UploadFile, max_bytes: int) -> bytes:
    content = bytearray()
    while chunk := await file.read(_UPLOAD_CHUNK_SIZE):
        content.extend(chunk)
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail={"code": "file_too_large", "message": "评测文件超过允许大小"},
            )
    return bytes(content)


def _launch_evaluation(run_id: int) -> None:
    thread = threading.Thread(
        target=EvaluationRunner(SessionLocal).run,
        args=(run_id,),
        daemon=True,
        name=f"evaluation-{run_id}",
    )
    thread.start()


@router.get("/template")
def download_template(user: User = Depends(get_current_user)) -> Response:
    return Response(
        content=build_evaluation_template(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="sql-evaluation-template.xlsx"'
        },
    )


@router.post("/import", status_code=201)
async def import_evaluation(
    name: str = Form(..., min_length=1, max_length=128),
    dialect: str = Form("hive"),
    system_time: date = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if Path(file.filename or "").suffix.casefold() != ".xlsx":
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_file_type", "message": "请选择 .xlsx 文件"},
        )
    if dialect.casefold() != "hive":
        raise HTTPException(
            status_code=400,
            detail={"code": "unsupported_dialect", "message": "首期仅支持 Hive SQL"},
        )
    try:
        cases = import_evaluation_workbook(
            await _read_upload(file, settings.ontology.max_upload_bytes),
            max_bytes=settings.ontology.max_upload_bytes,
        )
    except WorkbookValidationError as error:
        detail: dict[str, Any] = {"code": error.code, "message": error.message}
        if error.row_number is not None:
            detail["row_number"] = error.row_number
        raise HTTPException(status_code=400, detail=detail) from error

    run = EvaluationRun(
        user_id=user.id,
        name=name.strip(),
        dialect="hive",
        system_time=system_time,
        total_cases=len(cases),
    )
    run.cases = [
        EvaluationCase(
            case_number=index,
            source_row=item.row_number,
            requirement=item.requirement,
            reference_sql=item.reference_sql,
        )
        for index, item in enumerate(cases, start=1)
    ]
    db.add(run)
    db.commit()
    db.refresh(run)
    return _run_summary(run)


@router.get("")
def list_evaluations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    runs = (
        db.query(EvaluationRun)
        .filter(EvaluationRun.user_id == user.id)
        .order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc())
        .all()
    )
    return [_run_summary(run) for run in runs]


@router.get("/{run_id}")
def evaluation_detail(
    run_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return _run_summary(_owned_run(run_id, user, db))


@router.post("/{run_id}/run", status_code=202)
def start_evaluation(
    run_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    run = _owned_run(run_id, user, db)
    should_launch = run.status in {"pending", "failed"}
    if should_launch:
        run.status = "running"
        run.error_code = None
        db.commit()
        db.refresh(run)
        _launch_evaluation(run.id)
    return _run_summary(run)


@router.get("/{run_id}/cases")
def list_cases(
    run_id: int,
    path: str = Query("ontology", pattern="^(legacy|ontology)$"),
    strict_pass: bool | None = None,
    ontology_status: str | None = None,
    diagnosis_code: str | None = None,
    manual_review: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    run = _owned_run(run_id, user, db)
    items = list(run.cases)
    if ontology_status:
        items = [item for item in items if item.ontology_status == ontology_status]
    if strict_pass is not None:
        items = [
            item
            for item in items
            if bool(_comparison(item, path).get("strict_pass")) is strict_pass
        ]
    if manual_review is not None:
        items = [
            item
            for item in items
            if bool(_comparison(item, path).get("manual_review")) is manual_review
        ]
    if diagnosis_code:
        items = [
            item
            for item in items
            if diagnosis_code
            in ((item.diagnosis_codes or {}).get(path, []) if item.diagnosis_codes else [])
        ]
    total = len(items)
    start = (page - 1) * page_size
    return {
        "items": [_case_summary(item) for item in items[start : start + page_size]],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{run_id}/cases/{case_id}")
def case_detail(
    run_id: int,
    case_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return _case_detail(_owned_case(run_id, case_id, user, db))


@router.delete("/{run_id}", status_code=204)
def delete_evaluation(
    run_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    run = _owned_run(run_id, user, db)
    db.delete(run)
    db.commit()
    return Response(status_code=204)
