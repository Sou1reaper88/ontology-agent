"""Exact database-role dependencies for ontology package management."""

# ruff: noqa: B008

from __future__ import annotations

from fastapi import Depends, HTTPException, status

from auth.jwt import get_current_user
from config.settings import settings
from models import User


def _require_role(user: User, allowed: tuple[str, ...], code: str, message: str) -> User:
    """Authorize from the loaded user's current role, never JWT role claims."""
    role = user.role
    if role is None or role.name not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": code, "message": message, "details": {}},
        )
    return user


def require_ontology_maintainer(user: User = Depends(get_current_user)) -> User:
    """Allow only exact maintainer or administrator role names from the database."""
    return _require_role(
        user,
        settings.ontology.maintainer_roles,
        "ontology_maintainer_required",
        "需要本体维护者权限",
    )


def require_ontology_administrator(user: User = Depends(get_current_user)) -> User:
    """Allow only exact administrator role names from the database."""
    return _require_role(
        user,
        settings.ontology.administrator_roles,
        "ontology_administrator_required",
        "需要全省管理员权限",
    )
