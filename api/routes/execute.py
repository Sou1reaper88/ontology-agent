"""执行接口：POST /execute 提交、GET /execute/{query_id} 状态、GET /execute/result/{query_id} 结果。

执行状态以 query_history.execution_status 为权威（任务执行时已更新），
不依赖 Celery backend（eager 模式 / 异步模式均适用）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlglot import exp, parse
from sqlglot.errors import ParseError

from auth.jwt import get_current_user
from auth.permission import require_table_permissions
from executor.result_store import load_result
from executor.tasks import execute_query
from models import QueryHistory, User
from models.base import get_db

router = APIRouter(prefix="/execute", tags=["execute"])


class ExecuteRequest(BaseModel):
    query_id: int | None = None
    sql: str | None = None  # 直传 SQL（对话内编辑后执行）：自动建 query_history 再执行
    program_id: str | None = None


class ExecuteResponse(BaseModel):
    task_id: str
    query_id: int
    status: str


def _require_single_read_only_query(sql: str) -> None:
    try:
        statements = parse(sql, read="hive")
    except ParseError as exc:
        raise HTTPException(
            status_code=400,
            detail="执行接口仅支持单条只读查询；取数程序仅生成、不执行",
        ) from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        raise HTTPException(
            status_code=400,
            detail="执行接口仅支持单条只读查询；取数程序仅生成、不执行",
        )


@router.post("", response_model=ExecuteResponse)
def create_execute(
    payload: ExecuteRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExecuteResponse:
    """提交执行：query_id 或 sql 二选一。

    - query_id：执行已有取数记录（校验归属 + 表权限）
    - sql：直传编辑后的 SQL，先建 query_history 记录再执行
    """
    if payload.program_id is not None:
        raise HTTPException(status_code=400, detail="取数程序仅生成，不支持执行")

    if payload.query_id is not None:
        record = db.get(QueryHistory, payload.query_id)
        if not record or record.user_id != user.id:
            raise HTTPException(status_code=404, detail="取数记录不存在")
        sql = record.generated_sql or ""
        _require_single_read_only_query(sql)
        require_table_permissions(user, sql, db)
        record.execution_status = "pending"
        db.commit()
    elif payload.sql:
        sql = payload.sql.strip()
        if not sql:
            raise HTTPException(status_code=400, detail="SQL 不能为空")
        _require_single_read_only_query(sql)
        require_table_permissions(user, sql, db)
        record = QueryHistory(
            user_id=user.id,
            request_text="对话编辑SQL",
            generated_sql=sql,
            execution_status="pending",
        )
        db.add(record)
        db.commit()
    else:
        raise HTTPException(status_code=400, detail="必须提供 query_id 或 sql")

    task = execute_query.delay(record.id)
    db.refresh(record)  # eager 模式任务已同步更新状态
    return ExecuteResponse(
        task_id=task.id,
        query_id=record.id,
        status=record.execution_status,
    )


@router.get("/{query_id}")
def get_execute_status(
    query_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """查询执行状态（以 DB 为准）。"""
    record = db.get(QueryHistory, query_id)
    if not record or record.user_id != user.id:
        raise HTTPException(status_code=404, detail="取数记录不存在")
    return {
        "query_id": query_id,
        "status": record.execution_status,
        "row_count": record.row_count,
        "result_ref": record.result_ref,
    }


@router.get("/result/{query_id}")
def get_execute_result(
    query_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """拉取执行结果（校验归属）。"""
    record = db.get(QueryHistory, query_id)
    if not record or record.user_id != user.id:
        raise HTTPException(status_code=404, detail="取数记录不存在")
    if record.execution_status != "success":
        raise HTTPException(status_code=400, detail="记录未执行成功")
    data = load_result(record)
    return {"query_id": query_id, "status": "success", **data}
