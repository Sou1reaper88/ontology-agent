"""查询结果表（<1 万行存 jsonb；≥1 万行存文件，result_ref 指向文件）。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class QueryResult(Base):
    """单次执行的结果数据（列定义 + 数据行）。"""

    __tablename__ = "query_results"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    query_history_id: Mapped[int] = mapped_column(
        ForeignKey("query_history.id"), nullable=False
    )
    columns: Mapped[list] = mapped_column(JSONB, nullable=False)
    rows: Mapped[list] = mapped_column(JSONB, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
