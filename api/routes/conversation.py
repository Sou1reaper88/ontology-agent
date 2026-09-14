"""对话接口：多轮取数会话。

- POST /conversations            创建对话（可选标题/上下文）
- GET  /conversations            当前用户对话列表
- GET  /conversations/{id}       对话详情（含消息列表）
- PATCH /conversations/{id}      更新标题/上下文
- DELETE /conversations/{id}     删除对话（级联消息）
- POST /conversations/{id}/messages  发送消息：异步生成 SQL（202，轮询状态）
- GET  /conversations/messages/{id}/status  生成进度轮询（链路步骤实时返回）
"""

from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agent.context_engineering import (
    AssembledContext,
    ContextMessage,
    get_context_assembler,
)
from agent.conversation_agent import run_conversation_agent as run_agent, history_content
from agent.trace_store import (
    append_step,
    clear_trace,
    get_trace,
    new_trace,
    set_failed,
    set_output,
)
from auth.jwt import get_current_user
from auth.permission import require_table_permissions
from models import Conversation, ConversationMessage, QueryHistory, SavedPrompt, User
from models.base import SessionLocal, get_db

router = APIRouter(prefix="/conversations", tags=["conversation"])


class ConversationCreate(BaseModel):
    title: str | None = None
    context: str | None = None


class ConversationUpdate(BaseModel):
    title: str | None = None
    context: str | None = None


class MessageSend(BaseModel):
    content: str
    system_time: str | None = None
    ontology_id: str | None = None
    prompt_id: int | None = None




class BatchDeleteRequest(BaseModel):
    ids: list[int]


class ProgramStepSummary(BaseModel):
    step_id: str
    target_table: str
    drop_sql: str
    create_sql: str


class ProgramDiagnosticSummary(BaseModel):
    code: str
    message: str
    step_id: str | None = None
    location: str | None = None
    candidates: list[str] = []


class ProgramSummary(BaseModel):
    program_id: str
    platform: str
    mode: str
    steps: list[ProgramStepSummary]
    diagnostics: list[ProgramDiagnosticSummary] = []
    package: dict | None = None
    temporal_evidence: list[dict] = []
    inference_evidence: dict | None = None
    missing_information: list[str] = []


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    sql: str | None = None
    query_id: int | None = None
    trace: list[dict] | None = None
    ontology_shadow: dict | None = None
    program: ProgramSummary | None = None
    created_at: str


class ConversationOut(BaseModel):
    id: int
    title: str
    context: str | None = None
    created_at: str
    updated_at: str
    messages: list[MessageOut] = []


def _extract_ontology_shadow(trace: list[dict] | None) -> dict | None:
    return next(
        (
            item.get("payload")
            for item in reversed(trace or [])
            if item.get("node") == "ontology_shadow"
        ),
        None,
    )


def _extract_program(trace: list[dict] | None) -> ProgramSummary | None:
    payload = next(
        (
            item.get("payload")
            for item in reversed(trace or [])
            if item.get("node") == "program_generation"
            and (item.get("status") == "success"
                 or (item.get("payload") or {}).get("generation_mode") == "authored_draft")
        ),
        None,
    )
    if not isinstance(payload, dict) or not payload.get("program_id"):
        return None
    return ProgramSummary(
        program_id=payload["program_id"],
        platform=payload.get("platform") or "hive",
        mode=payload.get("generation_mode") or "program",
        steps=payload.get("program_steps") or [],
        diagnostics=payload.get("diagnostics") or [],
        package=payload.get("package"),
        temporal_evidence=payload.get("temporal_evidence") or [],
        inference_evidence=payload.get("inference_evidence"),
        missing_information=payload.get("missing_information") or [],
    )


def _own_conversation(conv_id: int, user: User, db: Session) -> Conversation:
    conv = db.get(Conversation, conv_id)
    if not conv or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="对话不存在")
    return conv


def _prepare_conversation_context(
    conversation: Conversation,
    history: list[ConversationMessage],
    current_input: str | None = None,
    turn_prompt: str | None = None,
) -> AssembledContext:
    """Assemble one bounded context and persist only a newly produced summary."""

    assembled = get_context_assembler().assemble(
        tuple(
            ContextMessage(
                message_id=item.id,
                role=item.role,
                content=history_content(item.content, getattr(item, "trace", None)),
                sql=item.sql,
            )
            for item in history
        ),
        persistent_prompt=turn_prompt,
        current_input=current_input,
        previous_summary=conversation.context_summary,
        previous_summary_through_message_id=(
            conversation.context_summary_through_message_id
        ),
    )
    if assembled.compressed:
        conversation.context_summary = assembled.summary
        conversation.context_summary_through_message_id = (
            assembled.compacted_through_message_id
        )
    return assembled


@router.post("", status_code=201)
def create_conversation(
    payload: ConversationCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    conv = Conversation(
        user_id=user.id,
        title=(payload.title or "新对话").strip() or "新对话",
        context=payload.context,
    )
    db.add(conv)
    db.commit()
    return {"id": conv.id, "title": conv.title, "context": conv.context}


@router.get("")
def list_conversations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    convs = (
        db.query(Conversation)
        .filter(Conversation.user_id == user.id, Conversation.status == 1)
        .order_by(Conversation.updated_at.desc())
        .all()
    )
    out = []
    for c in convs:
        last = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == c.id)
            .order_by(ConversationMessage.id.desc())
            .first()
        )
        out.append(
            {
                "id": c.id,
                "title": c.title,
                "context": c.context,
                "last_message": last.content if last else None,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
            }
        )
    return out


@router.get("/{conv_id}")
def get_conversation(
    conv_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConversationOut:
    conv = _own_conversation(conv_id, user, db)
    messages = [
        MessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            sql=m.sql,
            query_id=m.query_id,
            trace=m.trace,
            ontology_shadow=_extract_ontology_shadow(m.trace),
            program=_extract_program(m.trace),
            created_at=m.created_at.isoformat(),
        )
        for m in conv.messages
    ]
    return ConversationOut(
        id=conv.id,
        title=conv.title,
        context=conv.context,
        created_at=conv.created_at.isoformat(),
        updated_at=conv.updated_at.isoformat(),
        messages=messages,
    )


@router.patch("/{conv_id}")
def update_conversation(
    conv_id: int,
    payload: ConversationUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    conv = _own_conversation(conv_id, user, db)
    if payload.title is not None:
        conv.title = payload.title.strip() or conv.title
    if payload.context is not None:
        conv.context = payload.context
    db.commit()
    return {"id": conv.id, "title": conv.title, "context": conv.context}


@router.delete("/{conv_id}", status_code=204)
def delete_conversation(
    conv_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    conv = _own_conversation(conv_id, user, db)
    db.delete(conv)  # cascade 删除消息
    db.commit()


@router.post("/batch-delete")
def batch_delete_conversations(
    payload: BatchDeleteRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """批量删除对话（仅限当前用户，级联删除消息）。"""
    ids = list(dict.fromkeys(payload.ids))  # 去重保序
    if not ids:
        return {"deleted": 0, "ids": []}
    convs = (
        db.query(Conversation)
        .filter(Conversation.user_id == user.id, Conversation.id.in_(ids))
        .all()
    )
    deleted_ids = [c.id for c in convs]
    for c in convs:
        db.delete(c)  # cascade 删除消息
    db.commit()
    return {"deleted": len(deleted_ids), "ids": deleted_ids}


@router.post("/clear-all")
def clear_all_conversations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """清空当前用户全部对话（级联删除消息）。"""
    convs = db.query(Conversation).filter(Conversation.user_id == user.id).all()
    count = len(convs)
    for c in convs:
        db.delete(c)  # cascade 删除消息
    db.commit()
    return {"deleted": count}


@router.get("/messages/{msg_id}/status")
def message_status(
    msg_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """生成进度轮询：返回状态 + 已完成的链路步骤（实时可视化）。"""
    # Read memory first: a missing trace means completion was already committed.
    # Loading the row first can retain the placeholder across that commit.
    tr = get_trace(msg_id)
    msg = db.get(ConversationMessage, msg_id)
    if not msg:
        raise HTTPException(status_code=404, detail="消息不存在")
    conv = db.get(Conversation, msg.conversation_id)
    if not conv or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="消息不存在")

    if tr is not None:
        return {
            "message_id": msg_id,
            "status": tr["status"],
            "steps": tr["steps"],
            "error": tr["error"],
            "ontology_shadow": _extract_ontology_shadow(tr["steps"]),
            "program": _extract_program(tr["steps"]),
        }
    # 进程重启后内存 trace 丢失：从 DB 读最终态
    completion = next((step for step in reversed(msg.trace or [])
                       if step.get("node") == "conversation_response"), None)
    if completion is not None:
        succeeded = (completion.get("payload") or {}).get("success", False)
        return {"message_id": msg_id, "status": "success" if succeeded else "failed",
                "steps": msg.trace, "error": None if succeeded else msg.content,
                "ontology_shadow": _extract_ontology_shadow(msg.trace),
                "program": _extract_program(msg.trace)}
    if msg.sql or msg.trace:
        # 有 SQL 或完整链路 trace → 生成流程已完成（含无关问题提示等无 SQL 场景）
        return {
            "message_id": msg_id,
            "status": "success",
            "steps": msg.trace or [],
            "error": None,
            "ontology_shadow": _extract_ontology_shadow(msg.trace),
            "program": _extract_program(msg.trace),
        }
    if msg.content and msg.content != "生成中…":
        return {
            "message_id": msg_id,
            "status": "failed",
            "steps": msg.trace or [],
            "error": msg.content,
            "ontology_shadow": _extract_ontology_shadow(msg.trace),
            "program": _extract_program(msg.trace),
        }
    return {
        "message_id": msg_id,
        "status": "failed",
        "steps": [],
        "error": "服务重启，生成中断",
        "ontology_shadow": None,
        "program": None,
    }


def _generate_async(
    conv_id: int,
    msg_id: int,
    user_msg_id: int,
    user_id: int,
    content: str,
    ontology_id: str | None,
    system_time: str | None,
    conversation_context: str | None,
    turn_prompt: str | None,
) -> None:
    """后台线程：执行编排 → trace 逐步写入 store → 完成后落库消息/审计/取数记录。"""
    db = SessionLocal()
    try:
        conv = db.get(Conversation, conv_id)
        if conv is None:
            set_failed(msg_id, "对话不存在")
            return
        history_messages = [
            m
            for m in conv.messages
            if m.role in ("user", "assistant") and m.id not in (msg_id, user_msg_id)
        ]
        assembled = _prepare_conversation_context(
            conv,
            history_messages,
            current_input=content,
            turn_prompt=turn_prompt,
        )
        if assembled.compressed:
            db.commit()
        history = [
            {"role": m.role, "content": m.content, "sql": m.sql}
            for m in assembled.messages
        ]
        output = run_agent(
            content,
            ontology_id=ontology_id,
            system_time=system_time,
            history=history,
            conversation_context=turn_prompt,
            assembled_context=assembled.render(),
            on_step=lambda s: append_step(msg_id, s),
            request_id=f"conversation:{conv_id}:message:{msg_id}",
        )

        sql = output.get("sql") if (output.get("success") or output.get("generation_mode") == "authored_draft") else None
        program = _extract_program(output.get("trace"))
        query_id: int | None = None
        if sql and program is None:
            user = db.get(User, user_id)
            if user is not None:
                require_table_permissions(user, sql, db)
            record = QueryHistory(
                user_id=user_id,
                request_text=content,
                ontology_id=ontology_id,
                generated_sql=sql,
                execution_status="pending",
            )
            db.add(record)
            db.flush()
            query_id = record.id

        from audit.utils import write_audit_log

        write_audit_log(
            user_id=user_id,
            action="query_request",
            detail={
                "request_text": content,
                "conversation_id": conv_id,
                "success": bool(output.get("success")),
                "sql": sql if output.get("success") and program is None else None,
            },
            status="success" if output.get("success") else "failed",
        )

        reply_text = output.get("markdown") or (
            "生成失败：" + "；".join(output.get("errors") or ["未知错误"])
        )
        msg = db.get(ConversationMessage, msg_id)
        if msg is not None:
            msg.content = reply_text
            msg.sql = sql
            msg.query_id = query_id
            msg.trace = output.get("trace") or []
        db.commit()
        set_output(msg_id, output)
    except Exception as exc:
        db.rollback()
        set_failed(msg_id, str(exc))
        msg = db.get(ConversationMessage, msg_id)
        if msg is not None:
            msg.content = f"生成失败：{exc}"
            db.commit()
    finally:
        db.close()
        clear_trace(msg_id)  # 生成结束，内存态清理（历史走 DB）


@router.post("/{conv_id}/messages", status_code=202)
def send_message(
    conv_id: int,
    payload: MessageSend,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """发送一条提问：立即返回（202），后台异步生成 SQL，前端轮询消息状态。"""
    conv = _own_conversation(conv_id, user, db)
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="消息内容不能为空")
    turn_prompt = None
    if payload.prompt_id is not None:
        saved_prompt = db.get(SavedPrompt, payload.prompt_id)
        if saved_prompt is None:
            raise HTTPException(status_code=404, detail="提示词不存在或已被删除")
        turn_prompt = saved_prompt.content

    # 用户消息落库
    user_msg = ConversationMessage(conversation_id=conv.id, role="user", content=content)
    db.add(user_msg)

    # 预创建 assistant 消息（生成中占位）
    assistant_msg = ConversationMessage(
        conversation_id=conv.id, role="assistant", content="生成中…"
    )
    db.add(assistant_msg)
    conv.title = conv.title if conv.title != "新对话" else content[:20]
    db.commit()
    db.refresh(user_msg)
    db.refresh(assistant_msg)
    msg_id = assistant_msg.id

    new_trace(msg_id)
    thread = threading.Thread(
        target=_generate_async,
        args=(
            conv.id,
            msg_id,
            user_msg.id,
            user.id,
            content,
            payload.ontology_id,
            payload.system_time,
            None,
            turn_prompt,
        ),
        daemon=True,
    )
    thread.start()
    return {"message_id": msg_id, "status": "generating"}
