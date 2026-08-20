"""本体关系定义 + 逻辑定义 CRUD 接口（MySQL ontology 库）。

关系定义：表间 JOIN 关联；逻辑定义：业务口径。
均存储于 MySQL ontology 库（与业务 PG 库隔离）。
"""

from __future__ import annotations

import io
import re

import pymysql
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from openpyxl import load_workbook
from pydantic import BaseModel

from auth.jwt import get_current_user
from config.settings import settings
from models import User
from tools.ontology_client import clear_ontology_cache

router = APIRouter(prefix="/ontology", tags=["ontology"])

# 表名/字段名合法性校验（防 SQL 注入）
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# 本体元数据表（不作为对象定义展示）
_OBJECT_META_TABLES = {
    "ontology_relations",
    "ontology_logical_defs",
    "ontology_field_meta",
    "ontology_table_meta",
}


def _conn(database: str | None = None) -> pymysql.Connection:
    """MySQL 连接。默认连对象定义库 ontology；传 meta_database 连本体元数据库。"""
    return pymysql.connect(
        host=settings.mysql.host,
        port=settings.mysql.port,
        user=settings.mysql.user,
        password=settings.mysql.password,
        database=database or settings.mysql.database,
        charset="utf8mb4",
    )


# ---------------------------------------------------------------------------
# 关系定义
# ---------------------------------------------------------------------------

class RelationIn(BaseModel):
    source_table: str
    source_field: str
    target_table: str
    target_field: str
    relation_type: str | None = None
    relation_label: str | None = None


@router.get("/relations")
def list_relations(user: User = Depends(get_current_user)) -> list[dict]:
    conn = _conn(settings.mysql.meta_database)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, source_table, source_field, target_table, target_field, "
            "relation_type, relation_label FROM ontology_relations ORDER BY id"
        )
        cols = ["id", "source_table", "source_field", "target_table", "target_field",
                "relation_type", "relation_label"]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        return rows
    finally:
        conn.close()


@router.post("/relations", status_code=201)
def create_relation(payload: RelationIn, user: User = Depends(get_current_user)) -> dict:
    conn = _conn(settings.mysql.meta_database)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO ontology_relations "
            "(source_table, source_field, target_table, target_field, relation_type, relation_label) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (payload.source_table, payload.source_field, payload.target_table,
             payload.target_field, payload.relation_type, payload.relation_label),
        )
        conn.commit()
        return {"id": cur.lastrowid, **payload.model_dump()}
    finally:
        conn.close()


@router.delete("/relations/{relation_id}", status_code=204)
def delete_relation(relation_id: int, user: User = Depends(get_current_user)) -> None:
    conn = _conn(settings.mysql.meta_database)
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM ontology_relations WHERE id=%s", (relation_id,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 逻辑定义
# ---------------------------------------------------------------------------

class LogicalDefIn(BaseModel):
    def_name: str
    table_name: str
    def_desc: str
    def_condition: str | None = None


@router.get("/logical-defs")
def list_logical_defs(user: User = Depends(get_current_user)) -> list[dict]:
    conn = _conn(settings.mysql.meta_database)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, def_name, table_name, def_desc, def_condition "
            "FROM ontology_logical_defs ORDER BY id"
        )
        cols = ["id", "def_name", "table_name", "def_desc", "def_condition"]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        conn.close()


@router.post("/logical-defs", status_code=201)
def create_logical_def(payload: LogicalDefIn, user: User = Depends(get_current_user)) -> dict:
    conn = _conn(settings.mysql.meta_database)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO ontology_logical_defs (def_name, table_name, def_desc, def_condition) "
            "VALUES (%s, %s, %s, %s)",
            (payload.def_name, payload.table_name, payload.def_desc, payload.def_condition),
        )
        conn.commit()
        return {"id": cur.lastrowid, **payload.model_dump()}
    finally:
        conn.close()


@router.delete("/logical-defs/{def_id}", status_code=204)
def delete_logical_def(def_id: int, user: User = Depends(get_current_user)) -> None:
    conn = _conn(settings.mysql.meta_database)
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM ontology_logical_defs WHERE id=%s", (def_id,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 字段元数据（描述，版本化：更新不覆盖，旧记录失效新记录生效）
# ---------------------------------------------------------------------------

class FieldMetaIn(BaseModel):
    table_name: str
    field_name: str
    field_desc: str


@router.get("/field-meta")
def list_field_meta(table: str, user: User = Depends(get_current_user)) -> list[dict]:
    """返回指定表字段的当前生效描述（status=1）。"""
    conn = _conn(settings.mysql.meta_database)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, table_name, field_name, field_desc, status, updated_at "
            "FROM ontology_field_meta WHERE table_name=%s AND status=1 "
            "ORDER BY field_name",
            (table.strip(),),
        )
        cols = ["id", "table_name", "field_name", "field_desc", "status", "updated_at"]
        result = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            d["field_name"] = (d["field_name"] or "").upper()  # 与 /sql/columns 返回大写一致
            result.append(d)
        return result
    finally:
        conn.close()


@router.post("/field-meta", status_code=201)
def upsert_field_meta(payload: FieldMetaIn, user: User = Depends(get_current_user)) -> dict:
    """版本化更新字段描述：旧启用记录置失效，新增启用记录（不覆盖历史）。"""
    conn = _conn(settings.mysql.meta_database)
    try:
        cur = conn.cursor()
        table_name = payload.table_name.strip()
        field_name = payload.field_name.strip().lower()  # 统一存小写
        # 1. 旧生效记录置为失效
        cur.execute(
            "UPDATE ontology_field_meta SET status=0 "
            "WHERE table_name=%s AND field_name=%s AND status=1",
            (table_name, field_name),
        )
        # 2. 新增生效记录
        cur.execute(
            "INSERT INTO ontology_field_meta (table_name, field_name, field_desc, status) "
            "VALUES (%s, %s, %s, 1)",
            (table_name, field_name, payload.field_desc),
        )
        conn.commit()
        return {"id": cur.lastrowid, **payload.model_dump(), "status": 1}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 字段描述批量导入（TSV 粘贴 / Excel 上传）
# ---------------------------------------------------------------------------

def _parse_tsv(text: str) -> list[dict]:
    """解析 TSV（数智本体文档导出格式），列序：对象英文名/中文名/描述/状态/属性英文名/中文名/类型/描述。"""
    rows: list[dict] = []
    for line in text.strip().split("\n"):
        cols = line.split("\t")
        if len(cols) < 8:
            continue
        table_name = cols[0].strip().lower()
        if table_name == "对象英文名称":
            continue  # 跳过表头
        table_cn = cols[1].strip()
        table_desc = cols[2].strip() if len(cols) > 2 else ""
        field_name = cols[4].strip().lower()
        field_cn = cols[5].strip()
        field_desc = cols[7].strip()
        if not table_name or not field_name or not field_desc:
            continue
        rows.append(
            {
                "table_name": table_name,
                "table_cn": table_cn,
                "table_desc": table_desc,
                "field_name": field_name,
                "field_cn": field_cn,
                "field_desc": field_desc,
            }
        )
    return rows


def _parse_excel(file_bytes: bytes) -> list[dict]:
    """解析 Excel（数智本体文档），读「对象信息」sheet，按列名匹配。"""
    wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    sheet = wb["对象信息"] if "对象信息" in wb.sheetnames else wb[wb.sheetnames[0]]

    rows: list[dict] = []
    header: tuple | None = None
    for row in sheet.iter_rows(values_only=True):
        if header is None:
            if row and any(c and "对象英文名称" in str(c) for c in row):
                header = row
            continue
        if not row or not any(row):
            continue
        d = dict(zip(header, row))

        def _get(*keys: str) -> str:
            for k in keys:
                if k in d and d[k] is not None:
                    return str(d[k]).strip()
            return ""

        table_name = _get("对象英文名称").lower()
        field_name = _get("属性英文名").lower()
        field_desc = _get("属性描述")
        if not table_name or not field_name or not field_desc:
            continue
        rows.append(
            {
                "table_name": table_name,
                "table_cn": _get("对象中文名称"),
                "table_desc": _get("对象描述"),
                "field_name": field_name,
                "field_cn": _get("属性中文名"),
                "field_desc": field_desc,
            }
        )
    return rows


@router.post("/import-field-meta")
async def import_field_meta(
    text: str = Form(None),
    file: UploadFile = File(None),
    user: User = Depends(get_current_user),
) -> dict:
    """批量导入字段描述：粘贴 TSV 文本或上传 Excel，版本化导入 + 顺带更新表注释。"""
    if text:
        rows = _parse_tsv(text)
    elif file is not None:
        rows = _parse_excel(await file.read())
    else:
        raise HTTPException(status_code=400, detail="请提供粘贴文本或上传 Excel")
    if not rows:
        raise HTTPException(status_code=400, detail="未解析到任何字段描述")

    conn = _conn(settings.mysql.meta_database)
    try:
        cur = conn.cursor()
        # 已存在的表（用于安全更新表注释）
        cur.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE'",
            (settings.mysql.database,),
        )
        existing_tables = {r[0].lower() for r in cur.fetchall()}

        imported = 0
        for r in rows:
            cur.execute(
                "UPDATE ontology_field_meta SET status=0 "
                "WHERE table_name=%s AND field_name=%s AND status=1",
                (r["table_name"], r["field_name"]),
            )
            cur.execute(
                "INSERT INTO ontology_field_meta (table_name, field_name, field_desc, status) "
                "VALUES (%s, %s, %s, 1)",
                (r["table_name"], r["field_name"], r["field_desc"]),
            )
            imported += 1

        # 顺带更新表注释（对象中文名，去重，仅更新已存在的表）
        table_cn_map: dict[str, str] = {}
        for r in rows:
            if r["table_cn"] and r["table_name"] in existing_tables:
                table_cn_map.setdefault(r["table_name"], r["table_cn"])
        for tname, tcn in table_cn_map.items():
            cur.execute(
                f"ALTER TABLE `{settings.mysql.database}`.`{tname}` COMMENT=%s",
                (tcn,),
            )

        # 顺带写入表描述（对象描述列，独立存 ontology_table_meta，幂等 upsert）
        table_desc_map: dict[str, str] = {}
        for r in rows:
            if r.get("table_desc") and r["table_name"] in existing_tables:
                table_desc_map.setdefault(r["table_name"], r["table_desc"])
        for tname, tdesc in table_desc_map.items():
            cur.execute(
                "INSERT INTO ontology_table_meta (table_name, table_desc) VALUES (%s, %s) "
                "ON DUPLICATE KEY UPDATE table_desc=VALUES(table_desc)",
                (tname, tdesc),
            )

        conn.commit()
    finally:
        conn.close()
    return {
        "imported": imported,
        "tables": sorted({r["table_name"] for r in rows}),
        "table_comments_updated": len(table_cn_map),
        "table_descs_updated": len(table_desc_map),
    }


# ---------------------------------------------------------------------------
# 对象定义（表定义）：表注释/字段中文名维护（ALTER 物理表注释）
# ---------------------------------------------------------------------------

class ObjectCommentIn(BaseModel):
    table_comment: str | None = None


class ColumnCommentIn(BaseModel):
    column_comment: str | None = None


def _check_identifier(name: str) -> str:
    """校验表名/字段名格式，非法抛 400。"""
    if not _IDENTIFIER_RE.match(name):
        raise HTTPException(status_code=400, detail=f"非法标识符: {name}")
    return name.lower()


@router.get("/objects")
def list_objects(user: User = Depends(get_current_user)) -> list[dict]:
    """返回本体库所有对象（表）定义：表名/注释 + 字段（名/类型/中文注释/分区标记）。"""
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT TABLE_NAME, TABLE_COMMENT FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME",
            (settings.mysql.database,),
        )
        tables = cur.fetchall()
        cur.execute(
            "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, COLUMN_COMMENT "
            "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s "
            "ORDER BY TABLE_NAME, ORDINAL_POSITION",
            (settings.mysql.database,),
        )
        cols = cur.fetchall()
        # 表描述（ontology_table_meta 独立库存储，物理表注释仅作中文名）
        cur.execute(
            f"SELECT table_name, table_desc FROM {settings.mysql.meta_database}.ontology_table_meta"
        )
        desc_rows = cur.fetchall()
    finally:
        conn.close()

    desc_map = {r[0].lower(): r[1] for r in desc_rows}
    by_table: dict[str, dict] = {}
    for tname, tcomment in tables:
        key = tname.lower()
        if key in _OBJECT_META_TABLES:
            continue
        by_table[key] = {
            "table_name": tname.upper(),
            "table_comment": tcomment or "",
            "table_desc": desc_map.get(key, ""),
            "columns": [],
        }
    for tname, cname, ctype, ccomment in cols:
        key = tname.lower()
        if key in by_table:
            by_table[key]["columns"].append(
                {
                    "name": cname.upper(),
                    "type": ctype,
                    "comment": ccomment or "",
                    "is_partition": "分区" in (ccomment or ""),
                }
            )
    return list(by_table.values())


@router.patch("/objects/{table_name}")
def update_object_comment(
    table_name: str,
    payload: ObjectCommentIn,
    user: User = Depends(get_current_user),
) -> dict:
    """更新表注释（对象中文名/业务描述）。"""
    table = _check_identifier(table_name)
    comment = (payload.table_comment or "").strip()
    if not comment:
        raise HTTPException(status_code=400, detail="表描述不能为空")
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(f"ALTER TABLE `{table}` COMMENT=%s", (comment,))
        conn.commit()
    finally:
        conn.close()
    clear_ontology_cache()  # 表结构缓存失效，立即生效
    return {"table_name": table_name.upper(), "table_comment": comment}


@router.patch("/objects/{table_name}/columns/{column}")
def update_column_comment(
    table_name: str,
    column: str,
    payload: ColumnCommentIn,
    user: User = Depends(get_current_user),
) -> dict:
    """更新字段中文名（字段注释）。需要原列类型拼 MODIFY 语句。"""
    table = _check_identifier(table_name)
    col = _check_identifier(column)
    comment = (payload.column_comment or "").strip()
    if not comment:
        raise HTTPException(status_code=400, detail="字段中文名不能为空")
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s",
            (settings.mysql.database, table, col),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"字段 {column} 不存在")
        col_type = row[0]
        # MODIFY COLUMN 的 column_definition 中 COMMENT 仅支持 '...' 写法（不支持 = 号）
        escaped = comment.replace("\\", "\\\\").replace("'", "\\'")
        cur.execute(
            f"ALTER TABLE `{table}` MODIFY COLUMN `{col}` {col_type} COMMENT '{escaped}'"
        )
        conn.commit()
    finally:
        conn.close()
    clear_ontology_cache()
    return {"table_name": table_name.upper(), "column": column.upper(), "column_comment": comment}


class ObjectDescIn(BaseModel):
    table_desc: str | None = None


@router.patch("/objects/{table_name}/desc")
def update_object_desc(
    table_name: str,
    payload: ObjectDescIn,
    user: User = Depends(get_current_user),
) -> dict:
    """更新表描述（独立于表中文名，存 ontology_table_meta，幂等 upsert）。"""
    table = _check_identifier(table_name)
    desc = (payload.table_desc or "").strip()
    conn = _conn(settings.mysql.meta_database)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO ontology_table_meta (table_name, table_desc) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE table_desc=VALUES(table_desc)",
            (table, desc),
        )
        conn.commit()
    finally:
        conn.close()
    clear_ontology_cache()
    return {"table_name": table_name.upper(), "table_desc": desc}
