"""表级权限表。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class TablePermission(Base):
    """角色可访问的物理表 / 本体对象权限（RBAC 表级）。"""

    __tablename__ = "table_permissions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    table_name: Mapped[str] = mapped_column(String(128), nullable=False)
    ontology_object: Mapped[str | None] = mapped_column(String(128), nullable=True)
    can_query: Mapped[bool] = mapped_column(Boolean, default=True)
    can_execute: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )

    role: Mapped["Role"] = relationship(back_populates="permissions")
