"""对话表：一次多轮取数会话（含标题与常驻上下文配置）。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class Conversation(Base):
    """对话：用户可设置上下文（常驻补充信息），消息按时间顺序累积，支持继续追问。"""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(128), default="新对话")
    context: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )  # 上下文设置：常驻约束/补充信息，随每轮提问传给智能体
    status: Mapped[int] = mapped_column(SmallInteger, default=1)  # 1启用 0归档
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user: Mapped["User"] = relationship()
    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.id",
    )
