"""用户请求/响应模型。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserBase(BaseModel):
    username: str
    display_name: str
    role_id: int
    region: str | None = None


class UserCreate(UserBase):
    pass


class UserUpdate(BaseModel):
    display_name: str | None = None
    role_id: int | None = None
    region: str | None = None
    status: int | None = None


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: int
    created_at: datetime
