"""表级权限请求/响应模型。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TablePermissionBase(BaseModel):
    role_id: int
    table_name: str
    ontology_object: str | None = None
    can_query: bool = True
    can_execute: bool = False


class TablePermissionCreate(TablePermissionBase):
    pass


class TablePermissionUpdate(BaseModel):
    ontology_object: str | None = None
    can_query: bool | None = None
    can_execute: bool | None = None


class TablePermissionRead(TablePermissionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
