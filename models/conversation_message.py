"""对话消息表：user 提问 / assistant 回复（含 SQL 与关联的取数记录）。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class ConversationMessage(Base):
    """单条对话消息。assistant 消息可携带 SQL，并关联 query_history 供执行。"""

    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user / assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)  # 消息文本
    sql: Mapped[str | None] = mapped_column(Text, nullable=True)  # assistant 的 SQL
    query_id: Mapped[int | None] = mapped_column(
        ForeignKey("query_history.id"), nullable=True
    )  # 关联取数记录（可执行）
    trace: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 生成链路步骤（全链路可视化）
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
