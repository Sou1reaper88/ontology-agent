"""用户表。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class User(Base):
    """生产人员账号。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(
        String(256), nullable=False, server_default="", default=""
    )
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    region: Mapped[str | None] = mapped_column(String(16), nullable=True)  # 地市，预留
    status: Mapped[int] = mapped_column(SmallInteger, default=1)  # 1启用 0禁用
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )

    role: Mapped["Role"] = relationship(back_populates="users")
