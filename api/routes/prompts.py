"""Shared prompt library. Every authenticated user can edit and delete."""

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from auth.jwt import get_current_user
from models import SavedPrompt, User
from models.base import get_db

router = APIRouter(prefix="/prompts", tags=["prompts"])


class PromptWrite(BaseModel):
    name: str
    content: str

    @field_validator("name", "content")
    @classmethod
    def non_empty(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        return value


def render(item):
    return {"id": item.id, "name": item.name, "content": item.content,
            "created_at": item.created_at.isoformat(), "updated_at": item.updated_at.isoformat()}


@router.get("")
def list_prompts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [render(item) for item in db.query(SavedPrompt).order_by(SavedPrompt.updated_at.desc()).all()]


@router.post("", status_code=201)
def create_prompt(payload: PromptWrite, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = SavedPrompt(name=payload.name, content=payload.content)
    db.add(item); db.commit(); db.refresh(item)
    return render(item)


@router.patch("/{prompt_id}")
def update_prompt(prompt_id: int, payload: PromptWrite, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.get(SavedPrompt, prompt_id)
    if item is None: raise HTTPException(404, "提示词不存在")
    item.name, item.content = payload.name, payload.content
    db.commit(); db.refresh(item)
    return render(item)


@router.delete("/{prompt_id}", status_code=204)
def delete_prompt(prompt_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.get(SavedPrompt, prompt_id)
    if item is None: raise HTTPException(404, "提示词不存在")
    db.delete(item); db.commit()
    return Response(status_code=204)
