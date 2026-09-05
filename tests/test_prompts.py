from fastapi.testclient import TestClient

import api.routes.conversation as route
from tests.conftest import send_and_wait


def headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_shared_prompt_crud_is_available_to_every_user(client: TestClient, admin_token: str):
    created = client.post('/prompts', headers=headers(admin_token), json={
        'name': '只给建议', 'content': '讨论本体时只给建议，不修改。'} )
    assert created.status_code == 201
    prompt_id = created.json()['id']
    assert any(item['id'] == prompt_id for item in client.get('/prompts', headers=headers(admin_token)).json())
    updated = client.patch(f'/prompts/{prompt_id}', headers=headers(admin_token),
                           json={'name': '建议模式', 'content': '仅输出建议。'})
    assert updated.json()['content'] == '仅输出建议。'
    assert client.delete(f'/prompts/{prompt_id}', headers=headers(admin_token)).status_code == 204


def test_selected_prompt_is_snapshotted_for_one_turn_only(client, admin_token, monkeypatch):
    prompt = client.post('/prompts', headers=headers(admin_token), json={
        'name': '本轮格式', 'content': '本轮回答简洁。'}).json()
    captured = []
    def fake(query, **kwargs):
        captured.append(kwargs)
        return {'success': True, 'sql': None, 'markdown': 'ok', 'trace': [{
            'node': 'conversation_response', 'status': 'success', 'payload': {'success': True}}]}
    monkeypatch.setattr(route, 'run_agent', fake)
    conversation = client.post('/conversations', headers=headers(admin_token), json={}).json()
    send_and_wait(client, admin_token, conversation['id'], '第一轮', prompt_id=prompt['id'])
    send_and_wait(client, admin_token, conversation['id'], '第二轮')
    assert '本轮回答简洁' in captured[0]['assembled_context']
    assert captured[0]['conversation_context'] == '本轮回答简洁。'
    assert '本轮回答简洁' not in captured[1]['assembled_context']
    assert captured[1]['conversation_context'] is None
    client.delete(f"/prompts/{prompt['id']}", headers=headers(admin_token))


def test_legacy_conversation_context_is_not_a_persistent_prompt(client, admin_token, monkeypatch):
    captured = []
    monkeypatch.setattr(route, 'run_agent', lambda q, **kw: captured.append(kw) or {
        'success': True, 'sql': None, 'markdown': 'ok', 'trace': [{
            'node': 'conversation_response', 'status': 'success', 'payload': {'success': True}}]})
    conversation = client.post('/conversations', headers=headers(admin_token),
                               json={'context': '旧常驻内容'}).json()
    send_and_wait(client, admin_token, conversation['id'], '问题')
    assert '旧常驻内容' not in captured[0]['assembled_context']
    assert captured[0]['conversation_context'] is None
