"""SQL 消息反馈接口。"""

# ruff: noqa: B008

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session

from auth.jwt import get_current_user
from auth.ontology_roles import require_ontology_maintainer
from models import Conversation, ConversationMessage, MessageFeedback, User
from models.base import get_db

router = APIRouter(prefix="/feedback", tags=["feedback"])
FeedbackStatus = Literal["correct", "needs_revision"]


class FeedbackWrite(BaseModel):
    status: FeedbackStatus
    note: str | None = None
    final_sql: str | None = None

    @model_validator(mode="after")
    def require_revision_note(self):
        self.note = self.note.strip() if self.note else None
        if self.status == "needs_revision" and not self.note:
            raise ValueError("需要修改时必须填写问题说明或补充口径")
        return self


def _owned_sql_message(message_id: int, user: User, db: Session) -> ConversationMessage:
    message = (
        db.query(ConversationMessage)
        .join(Conversation)
        .filter(
            ConversationMessage.id == message_id,
            Conversation.user_id == user.id,
        )
        .one_or_none()
    )
    if message is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    if message.role != "assistant" or not (message.sql or "").strip():
        raise HTTPException(status_code=409, detail="仅支持对已完成的 SQL 回复反馈")
    return message


def _summary(feedback: MessageFeedback) -> dict:
    return {
        "id": feedback.id,
        "status": feedback.status,
        "note": feedback.note,
        "final_sql": feedback.final_sql,
        "created_at": feedback.created_at.isoformat(),
        "updated_at": feedback.updated_at.isoformat(),
    }


def _ontology_version(trace: list[dict] | None) -> str | None:
    for item in reversed(trace or []):
        payload = item.get("payload")
        package = payload.get("package") if isinstance(payload, dict) else None
        if isinstance(package, dict) and package.get("version") is not None:
            return str(package["version"])
    return None


@router.put("/messages/{message_id}")
def put_feedback(
    message_id: int,
    payload: FeedbackWrite,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    message = _owned_sql_message(message_id, user, db)
    feedback = (
        db.query(MessageFeedback)
        .filter(MessageFeedback.message_id == message.id)
        .one_or_none()
    )
    if feedback is None:
        feedback = MessageFeedback(message_id=message.id, user_id=user.id)
        db.add(feedback)

    feedback.user_id = user.id
    feedback.status = payload.status
    if payload.status == "correct":
        feedback.note = None
        feedback.final_sql = message.sql
    else:
        feedback.note = payload.note
        feedback.final_sql = payload.final_sql.strip() if payload.final_sql else None

    db.commit()
    db.refresh(feedback)
    return _summary(feedback)


@router.delete("/messages/{message_id}", status_code=204)
def delete_feedback(
    message_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    message = _owned_sql_message(message_id, user, db)
    feedback = (
        db.query(MessageFeedback)
        .filter(MessageFeedback.message_id == message.id)
        .one_or_none()
    )
    if feedback is not None:
        db.delete(feedback)
        db.commit()


@router.get("")
def list_feedback(
    status: FeedbackStatus | None = None,
    _: User = Depends(require_ontology_maintainer),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = (
        db.query(MessageFeedback, ConversationMessage, User)
        .join(ConversationMessage, MessageFeedback.message_id == ConversationMessage.id)
        .join(User, MessageFeedback.user_id == User.id)
    )
    if status is not None:
        query = query.filter(MessageFeedback.status == status)

    rows = []
    for feedback, message, owner in query.order_by(MessageFeedback.updated_at.desc()).all():
        request = (
            db.query(ConversationMessage)
            .filter(
                ConversationMessage.conversation_id == message.conversation_id,
                ConversationMessage.role == "user",
                ConversationMessage.id < message.id,
            )
            .order_by(ConversationMessage.id.desc())
            .first()
        )
        rows.append(
            {
                "id": feedback.id,
                "conversation_id": message.conversation_id,
                "message_id": message.id,
                "status": feedback.status,
                "request_text": request.content if request else None,
                "generated_sql": message.sql,
                "note": feedback.note,
                "final_sql": feedback.final_sql,
                "ontology_version": _ontology_version(message.trace),
                "username": owner.username,
                "created_at": feedback.created_at.isoformat(),
                "updated_at": feedback.updated_at.isoformat(),
            }
        )
    return rows
