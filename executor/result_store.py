"""结果存储：<1 万行存 query_results(jsonb)，≥1 万行存文件（result_ref 指向路径）。"""

from __future__ import annotations

import json
from pathlib import Path

from models import QueryHistory, QueryResult
from models.base import SessionLocal

RESULT_FILE_THRESHOLD = 10_000
RESULT_DIR = Path(__file__).resolve().parent.parent / "deploy" / "data" / "results"


def store_result(
    query_history_id: int, columns: list[str], rows: list[list]
) -> str:
    """存储结果，返回 result_ref（`db:{id}` 或文件路径）。"""
    row_count = len(rows)
    if row_count < RESULT_FILE_THRESHOLD:
        db = SessionLocal()
        try:
            result = QueryResult(
                query_history_id=query_history_id,
                columns=columns,
                rows=rows,
                row_count=row_count,
            )
            db.add(result)
            db.commit()
            result_id = result.id
        finally:
            db.close()
        return f"db:{result_id}"
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULT_DIR / f"{query_history_id}.json"
    path.write_text(
        json.dumps({"columns": columns, "rows": rows}, ensure_ascii=False),
        encoding="utf-8",
    )
    return str(path)


def load_result(query_history: QueryHistory) -> dict:
    """按 result_ref 加载结果。"""
    ref = query_history.result_ref or ""
    if ref.startswith("db:"):
        result_id = int(ref[3:])
        db = SessionLocal()
        try:
            result = db.get(QueryResult, result_id)
            if not result:
                raise FileNotFoundError("结果不存在")
            return {
                "columns": result.columns,
                "rows": result.rows,
                "row_count": result.row_count,
            }
        finally:
            db.close()
    path = Path(ref)
    if not path.exists():
        raise FileNotFoundError("结果文件不存在")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "columns": data["columns"],
        "rows": data["rows"],
        "row_count": len(data["rows"]),
    }
