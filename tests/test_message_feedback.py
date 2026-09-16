from __future__ import annotations

import pytest

from auth.jwt import create_access_token
from models import Conversation, ConversationMessage, MessageFeedback, Role, User
from models.base import SessionLocal

_seeded_conversation_ids: list[int] = []


@pytest.fixture(autouse=True)
def _cleanup_seeded_conversations():
    yield
    db = SessionLocal()
    try:
        if _seeded_conversation_ids:
            db.query(Conversation).filter(
                Conversation.id.in_(_seeded_conversation_ids)
            ).delete(synchronize_session=False)
        db.commit()
    finally:
        _seeded_conversation_ids.clear()
        db.close()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def seed_completed_sql_message(username: str) -> tuple[int, int, str]:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).one()
        conversation = Conversation(user_id=user.id, title="反馈测试")
        db.add(conversation)
        db.flush()
        db.add(
            ConversationMessage(
                conversation_id=conversation.id,
                role="user",
                content="查询测试用户",
            )
        )
        sql = (
            "DROP TABLE IF EXISTS temp_oa_test_result_table;\n"
            "CREATE TABLE temp_oa_test_result_table AS SELECT 1 AS user_id;"
        )
        answer = ConversationMessage(
            conversation_id=conversation.id,
            role="assistant",
            content="已生成取数脚本。",
            sql=sql,
            trace=[],
        )
        db.add(answer)
        db.commit()
        db.refresh(answer)
        _seeded_conversation_ids.append(conversation.id)
        return conversation.id, answer.id, sql
    finally:
        db.close()


def seed_assistant_message_without_sql(username: str) -> int:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).one()
        conversation = Conversation(user_id=user.id, title="普通问答测试")
        db.add(conversation)
        db.flush()
        answer = ConversationMessage(
            conversation_id=conversation.id,
            role="assistant",
            content="请补充取数范围。",
            sql=None,
            trace=[],
        )
        db.add(answer)
        db.commit()
        db.refresh(answer)
        _seeded_conversation_ids.append(conversation.id)
        return answer.id
    finally:
        db.close()


def test_correct_feedback_is_upserted_and_returned_with_history(client, admin_token):
    conversation_id, message_id, sql = seed_completed_sql_message("admin")
    response = client.put(
        f"/feedback/messages/{message_id}",
        json={"status": "correct"},
        headers=auth(admin_token),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "correct"
    assert response.json()["final_sql"] == sql

    updated = client.put(
        f"/feedback/messages/{message_id}",
        json={
            "status": "needs_revision",
            "note": "有效用户还要排除测试号码",
            "final_sql": sql + "\n-- corrected",
        },
        headers=auth(admin_token),
    )
    assert updated.status_code == 200
    assert updated.json()["id"] == response.json()["id"]

    history = client.get(f"/conversations/{conversation_id}", headers=auth(admin_token))
    answer = next(item for item in history.json()["messages"] if item["id"] == message_id)
    assert answer["feedback"]["status"] == "needs_revision"

    assert client.delete(
        f"/feedback/messages/{message_id}", headers=auth(admin_token)
    ).status_code == 204
    assert client.delete(
        f"/feedback/messages/{message_id}", headers=auth(admin_token)
    ).status_code == 204


def test_revision_feedback_requires_note_and_sql_message_ownership(client, admin_token):
    _, message_id, _ = seed_completed_sql_message("admin")
    missing_note = client.put(
        f"/feedback/messages/{message_id}",
        json={"status": "needs_revision", "note": "   "},
        headers=auth(admin_token),
    )
    assert missing_note.status_code == 422

    no_sql_id = seed_assistant_message_without_sql("admin")
    no_sql = client.put(
        f"/feedback/messages/{no_sql_id}",
        json={"status": "correct"},
        headers=auth(admin_token),
    )
    assert no_sql.status_code == 409


def test_feedback_list_is_maintainer_only_and_conversation_delete_cascades(
    client, admin_token
):
    conversation_id, message_id, _ = seed_completed_sql_message("admin")
    saved = client.put(
        f"/feedback/messages/{message_id}",
        json={"status": "correct"},
        headers=auth(admin_token),
    )
    feedback_id = saved.json()["id"]

    listing = client.get("/feedback?status=correct", headers=auth(admin_token))
    assert listing.status_code == 200
    row = next(item for item in listing.json() if item["id"] == feedback_id)
    assert row["conversation_id"] == conversation_id
    assert row["message_id"] == message_id
    assert row["request_text"] == "查询测试用户"
    assert row["ontology_version"] in {None, "test-version"}

    assert (
        client.delete(
            f"/conversations/{conversation_id}", headers=auth(admin_token)
        ).status_code
        == 204
    )
    assert not any(
        item["id"] == feedback_id
        for item in client.get("/feedback", headers=auth(admin_token)).json()
    )


def test_ordinary_user_cannot_list_or_write_another_users_feedback(client, admin_token):
    _, message_id, _ = seed_completed_sql_message("admin")
    db = SessionLocal()
    user_id = None
    try:
        role = db.query(Role).filter(Role.name == "地市生产岗").one()
        user = User(
            username=f"feedback_ordinary_{message_id}",
            display_name="反馈越权测试用户",
            role_id=role.id,
            password_hash="",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id
        token = create_access_token(user.id, user.username, user.role_id)

        assert client.get("/feedback", headers=auth(token)).status_code == 403
        response = client.put(
            f"/feedback/messages/{message_id}",
            json={"status": "correct"},
            headers=auth(token),
        )
        assert response.status_code == 404
    finally:
        if user_id is not None:
            db.expire_all()
            user = db.get(User, user_id)
            if user:
                db.delete(user)
                db.commit()
        db.close()


def test_feedback_model_is_imported():
    assert MessageFeedback.__tablename__ == "message_feedback"
