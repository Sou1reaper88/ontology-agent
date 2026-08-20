"""Celery 异步执行任务：执行 SQL → 结果分流存储 → 更新 query_history 状态。"""

from __future__ import annotations

import time

from executor.celery_app import celery_app
from executor.hive_executor import get_hive_executor
from executor.result_store import store_result
from models import QueryHistory
from models.base import SessionLocal
from monitoring.metrics import QUERY_EXECUTION_DURATION


@celery_app.task(name="execute_query")
def execute_query(query_history_id: int) -> dict:
    """执行指定取数记录的 SQL 并存储结果。"""
    start = time.time()
    db = SessionLocal()
    try:
        record = db.get(QueryHistory, query_history_id)
        if not record:
            raise ValueError(f"query_history {query_history_id} 不存在")

        record.execution_status = "running"
        db.commit()

        columns, rows = get_hive_executor().execute(record.generated_sql or "")

        result_ref = store_result(query_history_id, columns, rows)
        record.execution_status = "success"
        record.row_count = len(rows)
        record.result_ref = result_ref
        db.commit()

        from audit.utils import write_audit_log

        write_audit_log(
            user_id=record.user_id,
            action="sql_execute",
            detail={
                "query_id": query_history_id,
                "sql": record.generated_sql,
                "row_count": len(rows),
            },
            status="success",
            duration_ms=int((time.time() - start) * 1000),
        )
        return {
            "status": "success",
            "row_count": len(rows),
            "result_ref": result_ref,
        }
    except Exception as exc:
        db.rollback()
        record = db.get(QueryHistory, query_history_id)
        if record:
            record.execution_status = "failed"
            db.commit()
            from audit.utils import write_audit_log

            write_audit_log(
                user_id=record.user_id,
                action="sql_execute",
                detail={"query_id": query_history_id, "error": str(exc)},
                status="failed",
                duration_ms=int((time.time() - start) * 1000),
            )
        raise exc
    finally:
        QUERY_EXECUTION_DURATION.observe(time.time() - start)
        db.close()
