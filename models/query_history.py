"""取数历史表。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class QueryHistory(Base):
    """每次取数请求的记录（需求/SQL/执行状态/结果引用）。"""

    __tablename__ = "query_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    request_text: Mapped[str] = mapped_column(Text, nullable=False)
    ontology_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generated_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_status: Mapped[str] = mapped_column(
        String(16), default="pending"
    )  # pending/success/failed
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )

    user: Mapped["User"] = relationship()
