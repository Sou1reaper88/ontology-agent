"""Stable, JSON-serializable contracts for SQL evaluation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

StructureStatus = Literal["parsed", "unparsed", "unsupported"]


class FrozenModel(BaseModel):
    """Base model for deterministic snapshots."""

    model_config = ConfigDict(frozen=True)


class JoinSignature(FrozenModel):
    join_type: str
    left: str
    right: str
    conditions: tuple[str, ...] = ()


class PredicateSignature(FrozenModel):
    field: str
    operator: str
    values: tuple[str, ...] = ()


class SqlStructure(FrozenModel):
    status: StructureStatus
    is_read_only: bool
    tables: tuple[str, ...] = ()
    projections: tuple[str, ...] = ()
    joins: tuple[JoinSignature, ...] = ()
    predicates: tuple[PredicateSignature, ...] = ()
    having: tuple[PredicateSignature, ...] = ()
    aggregates: tuple[str, ...] = ()
    group_by: tuple[str, ...] = ()
    distinct: bool = False
    order_by: tuple[str, ...] = ()
    limit: int | None = None
    has_star: bool = False
    has_cte: bool = False
    has_subquery: bool = False
    warnings: tuple[str, ...] = ()
