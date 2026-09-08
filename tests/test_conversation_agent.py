import json
from types import SimpleNamespace

import httpx

from agent import conversation_agent as agent


def provider(monkeypatch, messages):
    requests = []
    def post(url, **kwargs):
        requests.append(json.loads(json.dumps(kwargs['json'])))
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'choices': [{'finish_reason': 'stop', 'message': messages.pop(0)}]})
    monkeypatch.setattr(agent.httpx, 'post', post)
    monkeypatch.setattr(agent, 'get_llm_client', lambda: SimpleNamespace(
        api_key='synthetic', base_url='https://example.invalid', model='test', timeout=1))
    return requests


def call(requirement='按补充口径重新取数'):
    return {'role': 'assistant', 'content': None, 'reasoning_content': 'synthetic reasoning',
        'tool_calls': [{'id': 'tool1', 'type': 'function', 'function': {
            'name': 'generate_sql_program', 'arguments': json.dumps({'requirement': requirement})}}]}


def test_question_answers_without_sql_tool(monkeypatch):
    requests = provider(monkeypatch, [{'role': 'assistant', 'content': '因为上一轮缺少关联字段。'}])
    monkeypatch.setattr(agent, 'generate_sql_program', lambda *a, **k: (_ for _ in ()).throw(AssertionError('must not generate')))
    output = agent.run_conversation_agent('为什么失败？', assembled_context='历史SQL与诊断')
    assert output['success'] and output['sql'] is None
    assert len(requests) == 1
    assert '历史SQL与诊断' in requests[0]['messages'][1]['content']
    assert output['trace'][-1]['node'] == 'conversation_response'


def test_tool_result_is_explained_and_original_sql_preserved(monkeypatch):
    requests = provider(monkeypatch, [call('状态为1的用户'), {'role': 'assistant', 'content': '已按补充口径生成。'}])
    observed = []
    def generate(query, **kwargs):
        observed.append((query, kwargs))
        return {'success': True, 'sql': 'SELECT 1', 'trace': [], 'inferred_plan': {'private': 'huge'}}
    monkeypatch.setattr(agent, 'generate_sql_program', generate)
    output = agent.run_conversation_agent('状态指1', assembled_context='原需求', system_time='2026-08-24')
    assert len(observed) == 1
    assert '状态为1' in observed[0][0]
    assert observed[0][1]['assembled_context'] == '原需求'
    assert output['sql'] == 'SELECT 1'
    assert output['markdown'] == '已按补充口径生成。'
    assert requests[1]['tool_choice'] == 'none'
    assert requests[1]['messages'][-2]['reasoning_content'] == 'synthetic reasoning'
    result = json.loads(requests[1]['messages'][-1]['content'])
    assert result['sql'] == 'SELECT 1' and 'inferred_plan' not in result


def test_failure_diagnostics_are_explained_without_retry(monkeypatch):
    requests = provider(monkeypatch, [call(), {'role': 'assistant', 'content': '关联字段缺失，无法完成生成。'}])
    calls = []
    def generate(*a, **k):
        calls.append(1)
        return {'success': False, 'sql': None, 'diagnostics': [{'code': 'missing_join', 'message': '缺少关联'}], 'trace': []}
    monkeypatch.setattr(agent, 'generate_sql_program', generate)
    output = agent.run_conversation_agent('重新生成')
    assert len(calls) == 1 and not output['success']
    assert 'missing_join' in requests[1]['messages'][-1]['content']
    assert '关联字段' in output['markdown']


def test_unknown_tool_never_executes(monkeypatch):
    message = call()
    message['tool_calls'][0]['function']['name'] = 'execute_sql'
    provider(monkeypatch, [message])
    monkeypatch.setattr(agent, 'generate_sql_program', lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    assert not agent.run_conversation_agent('执行')['success']


def test_history_includes_diagnostics_without_full_snapshot():
    text = agent.history_content('未生成', [{'node': 'program_generation', 'payload': {
        'diagnostics': [{'code': 'missing_join', 'message': '关联缺失'}],
        'inferred_plan': {'large_snapshot': 'SECRET_SENTINEL'}}}])
    assert 'missing_join' in text
    assert 'SECRET_SENTINEL' not in text


def test_status_reads_database_after_memory_completion(monkeypatch):
    import api.routes.conversation as route
    from models import ConversationMessage
    values = dict(id=99, conversation_id=1, content='生成中…', trace=None, sql=None)
    class DB:
        def get(self, cls, ident):
            return SimpleNamespace(**values) if cls is ConversationMessage else SimpleNamespace(user_id=1)
    def trace(ident):
        values.update(content='自然回答', trace=[{'node': 'conversation_response',
            'status': 'success', 'payload': {'success': True}}])
        return None
    monkeypatch.setattr(route, 'get_trace', trace)
    output = route.message_status(99, user=SimpleNamespace(id=1), db=DB())
    assert output['status'] == 'success'


def test_failed_tool_is_not_success_in_live_status():
    from agent.trace_store import new_trace, set_output, get_trace, clear_trace
    new_trace(-123)
    try:
        set_output(-123, {'success': False, 'markdown': '关联缺失'})
        assert get_trace(-123)['status'] == 'failed'
    finally:
        clear_trace(-123)


def test_second_generation_is_refused_but_original_sql_is_kept(monkeypatch):
    provider(monkeypatch, [call(), call()])
    calls = []
    def generate(*a, **k):
        calls.append(1)
        return {'success': True, 'sql': 'SELECT 1', 'trace': []}
    monkeypatch.setattr(agent, 'generate_sql_program', generate)
    output = agent.run_conversation_agent('生成')
    assert calls == [1] and output['sql'] == 'SELECT 1'
    assert '解释暂不可用' in output['markdown']


def test_context_diagnostics_enter_existing_budget(monkeypatch):
    import api.routes.conversation as route
    captured = []
    class Assembler:
        def assemble(self, messages, **kwargs):
            captured.extend(messages)
            return SimpleNamespace(compressed=False)
    monkeypatch.setattr(route, 'get_context_assembler', lambda: Assembler())
    conv = SimpleNamespace(context=None, context_summary=None, context_summary_through_message_id=None)
    message = SimpleNamespace(id=1, role='assistant', content='未生成', sql='SELECT 1',
        trace=[{'node': 'program_generation', 'payload': {'diagnostics': [{'code': 'missing_join'}]}}])
    route._prepare_conversation_context(conv, [message])
    assert 'missing_join' in captured[0].content
    assert captured[0].sql == 'SELECT 1'


def test_public_action_summary_is_visible_but_private_reasoning_is_not(monkeypatch):
    message = call()
    message['tool_calls'][0]['function']['arguments'] = json.dumps({
        'requirement': '补充后需求', 'summary': '已理解补充口径，准备重新生成取数脚本。'})
    provider(monkeypatch, [message, {'role': 'assistant', 'content': '已生成。'}])
    monkeypatch.setattr(agent, 'generate_sql_program', lambda *a, **k: {
        'success': True, 'sql': 'SELECT 1', 'trace': []})
    steps = []
    output = agent.run_conversation_agent('请按新口径生成', on_step=steps.append)
    assert any('已理解补充口径' in s['summary'] for s in steps)
    assert 'synthetic reasoning' not in json.dumps(output)
