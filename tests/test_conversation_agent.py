"""Conversation behavior with synthetic provider responses (no paid calls)."""
import json
from types import SimpleNamespace

import httpx

from agent import conversation_agent as agent
from tests.test_conversation_capabilities import provider, final, tool


def test_question_answers_without_sql_tool(monkeypatch):
    requests = provider(monkeypatch, [{'role': 'assistant', 'content': '因为上一轮缺少关联字段。'}])
    output = agent.run_conversation_agent('为什么失败？', assembled_context='历史SQL与诊断')
    assert output['success'] and output['sql'] is None and len(requests) == 1
    assert '历史SQL与诊断' in requests[0]['messages'][1]['content']
    assert not hasattr(agent, 'generate_sql_program')


def test_current_question_is_separate_from_pending_history(monkeypatch):
    requests = provider(monkeypatch, [final()])
    agent.run_conversation_agent('为什么不回答了', assembled_context='历史未完成取数请求')
    assert requests[0]['messages'][-1] == {'role': 'user', 'content': '为什么不回答了'}


def test_http_failure_is_specific_and_safe(monkeypatch):
    requests = provider(monkeypatch, [])
    def fail(url, **kwargs):
        requests.append(1)
        raise httpx.HTTPStatusError('SECRET', request=httpx.Request('POST', url),
            response=httpx.Response(402, request=httpx.Request('POST', url)))
    monkeypatch.setattr(agent.httpx, 'post', fail)
    output = agent.run_conversation_agent('解释')
    assert len(requests) == 1 and not output['success']
    assert output['diagnostics'][0]['code'] == 'conversation_provider_http_error'
    assert '402' in output['markdown'] and 'SECRET' not in json.dumps(output)


def test_unknown_and_removed_tools_never_execute(monkeypatch):
    for name in ('execute_sql', 'generate_sql_program'):
        provider(monkeypatch, [{'role': 'assistant', 'tool_calls': [tool(name, {})]}])
        assert not agent.run_conversation_agent('执行')['success']


def test_invalid_tool_arguments_return_to_model(monkeypatch):
    requests = provider(monkeypatch, [
        {'role': 'assistant', 'tool_calls': [tool('read_fields', {'object_refs': [], 'secret': 'SECRET'})]},
        final()])
    output = agent.run_conversation_agent('看字段')
    assert output['success'] and len(requests) == 2
    assert '工具参数格式' in requests[1]['messages'][-1]['content']
    assert 'SECRET' not in json.dumps(output)


def test_tool_budget_is_bounded(monkeypatch):
    calls = {'role': 'assistant', 'tool_calls': [tool('get_business_context', {}, str(i)) for i in range(17)]}
    requests = provider(monkeypatch, [calls])
    assert not agent.run_conversation_agent('取数')['success'] and len(requests) == 1


def test_history_includes_diagnostics_without_full_snapshot():
    text = agent.history_content('未生成', [{'node': 'program_generation', 'payload': {
        'diagnostics': [{'code': 'missing_join'}], 'inferred_plan': {'snapshot': 'SECRET'}}}])
    assert 'missing_join' in text and 'SECRET' not in text


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
    assert route.message_status(99, user=SimpleNamespace(id=1), db=DB())['status'] == 'success'


def test_failed_output_is_not_success_in_live_status():
    from agent.trace_store import new_trace, set_output, get_trace, clear_trace
    new_trace(-123)
    try:
        set_output(-123, {'success': False, 'markdown': '关联缺失'})
        assert get_trace(-123)['status'] == 'failed'
    finally:
        clear_trace(-123)


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
    assert 'missing_join' in captured[0].content and captured[0].sql == 'SELECT 1'
