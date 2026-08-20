"""表级权限 CRUD 接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models import TablePermission
from models.base import get_db
from schemas.table_permission import (
    TablePermissionCreate,
    TablePermissionRead,
    TablePermissionUpdate,
)

router = APIRouter(prefix="/permissions", tags=["permissions"])


@router.get("", response_model=list[TablePermissionRead])
def list_permissions(db: Session = Depends(get_db)) -> list[TablePermission]:
    return db.query(TablePermission).order_by(TablePermission.id).all()


@router.post("", response_model=TablePermissionRead, status_code=201)
def create_permission(
    payload: TablePermissionCreate, db: Session = Depends(get_db)
) -> TablePermission:
    perm = TablePermission(**payload.model_dump())
    db.add(perm)
    db.commit()
    db.refresh(perm)
    return perm


@router.put("/{perm_id}", response_model=TablePermissionRead)
def update_permission(
    perm_id: int, payload: TablePermissionUpdate, db: Session = Depends(get_db)
) -> TablePermission:
    perm = db.get(TablePermission, perm_id)
    if not perm:
        raise HTTPException(status_code=404, detail="权限记录不存在")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(perm, k, v)
    db.commit()
    db.refresh(perm)
    return perm


@router.delete("/{perm_id}", status_code=204)
def delete_permission(perm_id: int, db: Session = Depends(get_db)) -> None:
    perm = db.get(TablePermission, perm_id)
    if not perm:
        raise HTTPException(status_code=404, detail="权限记录不存在")
    db.delete(perm)
    db.commit()
