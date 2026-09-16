"""Synthetic metadata and mocked provider; never a business accuracy evaluation."""
import json
from types import SimpleNamespace

import httpx
import pytest

from agent import conversation_agent as agent
from agent.program_generation import derive_program_id
from tests.test_sql_authoring import PID, catalog, script

CONVERSATION_PID = derive_program_id('synthetic')


def provider(monkeypatch, responses):
    requests = []
    def post(url, **kwargs):
        requests.append(json.loads(json.dumps(kwargs['json'])))
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'choices': [{'finish_reason': 'stop', 'message': responses.pop(0)}]})
    monkeypatch.setattr(agent.httpx, 'post', post)
    monkeypatch.setattr(agent, 'get_llm_client', lambda: SimpleNamespace(
        api_key='synthetic', base_url='https://example.invalid', model='test', timeout=1))
    return requests


def final(sql=None, **kwargs):
    return {'role': 'assistant', 'content': json.dumps({
        'reply': '已说明。', 'sql': sql, 'allow_cte': True, 'assumptions': [], **kwargs})}


def tool(name, arguments, ident='t1'):
    return {'id': ident, 'type': 'function', 'function': {
        'name': name, 'arguments': json.dumps(arguments)}}


def test_five_tools_and_no_generation_entry(monkeypatch):
    requests = provider(monkeypatch, [final()])
    output = agent.run_conversation_agent('为什么失败', assembled_context='已有SQL与诊断')
    assert output['success'] and output['sql'] is None
    assert {t['function']['name'] for t in requests[0]['tools']} == {
        'search_tables', 'read_fields', 'get_field_mappings', 'get_business_context', 'validate_sql'}
    assert requests[0]['messages'][-1]['content'] == '为什么失败'


def test_parallel_tools_then_same_model_authors_readonly(monkeypatch):
    from agent.conversation_tools import ConversationTools
    monkeypatch.setattr(ConversationTools, '_load_catalog', lambda self: catalog())
    requests = provider(monkeypatch, [
        {'role': 'assistant', 'content': None, 'reasoning_content': 'PRIVATE', 'tool_calls': [
            tool('get_business_context', {}, 'context'),
            tool('read_fields', {'object_refs': ['Test']}, 'fields')]},
        final("SELECT ID FROM dm.TEST_M WHERE P_MON='202607'", delivery_mode='query')])
    output = agent.run_conversation_agent('取用户', system_time='2026-08-24', request_id='synthetic')
    assert output['success'] and output['generation_mode'] == 'authored_query'
    assert not output['sql'].startswith('DROP')
    assert len(requests) == 2 and requests[1]['tool_choice'] == 'auto'
    assert [m['tool_call_id'] for m in requests[1]['messages'] if m['role'] == 'tool'] == ['context', 'fields']
    assert '20260822' in requests[1]['messages'][-2]['content']
    assert f'temp_oa_{CONVERSATION_PID}_result_table' in requests[0]['messages'][1]['content']
    assert 'PRIVATE' not in json.dumps(output)


def test_default_delivery_rejects_a_bare_query(monkeypatch):
    from agent.conversation_tools import ConversationTools
    monkeypatch.setattr(ConversationTools, '_load_catalog', lambda self: catalog())
    provider(monkeypatch, [final("SELECT ID FROM dm.TEST_M WHERE P_MON='202607'")])
    output = agent.run_conversation_agent('正式取数', request_id='synthetic')
    assert not output['success']
    assert output['generation_mode'] == 'authored_draft'
    assert '默认需要物化结果表' in output['errors'][0]


def test_explicit_query_delivery_accepts_a_bare_query(monkeypatch):
    from agent.conversation_tools import ConversationTools
    monkeypatch.setattr(ConversationTools, '_load_catalog', lambda self: catalog())
    provider(monkeypatch, [final(
        "SELECT ID FROM dm.TEST_M WHERE P_MON='202607'",
        delivery_mode='query',
    )])
    output = agent.run_conversation_agent('仅查询预览', request_id='synthetic')
    assert output['success']
    assert output['generation_mode'] == 'authored_query'


def test_table_delivery_requires_the_result_table(monkeypatch):
    from agent.conversation_tools import ConversationTools
    monkeypatch.setattr(ConversationTools, '_load_catalog', lambda self: catalog())
    sql = script("SELECT ID FROM dm.TEST_M WHERE P_MON='202607'",
                 target=f'temp_oa_{CONVERSATION_PID}_work')
    provider(monkeypatch, [final(sql, delivery_mode='table')])
    output = agent.run_conversation_agent('正式取数', request_id='synthetic')
    assert not output['success']
    assert 'result_table' in output['errors'][0]


def test_default_delivery_accepts_the_result_table_program(monkeypatch):
    from agent.conversation_tools import ConversationTools
    monkeypatch.setattr(ConversationTools, '_load_catalog', lambda self: catalog())
    sql = script("SELECT ID FROM dm.TEST_M WHERE P_MON='202607'",
                 target=f'temp_oa_{CONVERSATION_PID}_result_table')
    provider(monkeypatch, [final(sql)])
    output = agent.run_conversation_agent('正式取数', request_id='synthetic')
    assert output['success']
    assert output['generation_mode'] == 'authored_program'


def test_query_delivery_rejects_a_materialized_program(monkeypatch):
    from agent.conversation_tools import ConversationTools
    monkeypatch.setattr(ConversationTools, '_load_catalog', lambda self: catalog())
    provider(monkeypatch, [final(
        script("SELECT ID FROM dm.TEST_M WHERE P_MON='202607'",
               target=f'temp_oa_{CONVERSATION_PID}_result_table'),
        delivery_mode='query',
    )])
    output = agent.run_conversation_agent('仅查询预览', request_id='synthetic')
    assert not output['success']
    assert '仅查询' in output['errors'][0]


def test_delivery_failure_retains_draft_without_model_retry(monkeypatch):
    requests = provider(monkeypatch, [final('DELETE FROM users')])
    output = agent.run_conversation_agent('生成')
    assert not output['success'] and output['sql'] == 'DELETE FROM users'
    assert output['generation_mode'] == 'authored_draft' and output['errors']
    assert len(requests) == 1


def test_sql_validation_queries_mixed_script_and_cte():
    from ontology_core.authored_sql import validate_authored_sql
    query = "SELECT ID FROM dm.TEST_M WHERE P_MON='202607'"
    assert validate_authored_sql(query, program_id=PID, catalog=catalog())['sql'] == query
    mixed = script(query) + f'\nSELECT ID FROM temp_oa_{PID}_result_table;'
    assert validate_authored_sql(mixed, program_id=PID, catalog=catalog())['sql'] == mixed
    with pytest.raises(ValueError, match='CTE'):
        validate_authored_sql('WITH t AS (SELECT 1 a) SELECT a FROM t',
                              program_id=PID, catalog=catalog(), allow_cte=False)


def test_cte_policy_cannot_be_relaxed_after_validation(monkeypatch):
    sql = 'WITH t AS (SELECT 1 a) SELECT a FROM t'
    requests = provider(monkeypatch, [
        {'role': 'assistant', 'tool_calls': [tool('validate_sql', {'sql': sql, 'allow_cte': False})]},
        final(sql, allow_cte=True)])
    output = agent.run_conversation_agent('不使用CTE')
    assert not output['success'] and any('CTE' in e for e in output['errors'])
    assert len(requests) == 2


def test_fact_tools_read_real_snapshot_without_an_inner_model(monkeypatch):
    from agent.conversation_tools import ConversationTools
    from ontology_core.metadata_candidates import MetadataCandidateCatalog
    from ontology_core.semantic_models import SemanticCatalog
    snapshot = SimpleNamespace(info=SimpleNamespace(package_id='synthetic', version='1', sha256='a' * 64),
                               catalog=SemanticCatalog())
    facts = MetadataCandidateCatalog(snapshot, catalog().objects, ())
    monkeypatch.setattr(ConversationTools, '_load_catalog', lambda self: facts)
    capabilities = ConversationTools(program_id=PID, request='合成需求', system_time='2026-08-24')
    fields, _ = capabilities.execute('read_fields', {'object_refs': ['dm.TEST_M'], 'field_refs': ['TestVALUE']})
    assert fields['fields'][0]['physical_name'] == 'VALUE' and fields['details_loaded']
    mappings, _ = capabilities.execute('get_field_mappings', {'object_refs': ['Test'], 'field_refs': ['TestVALUE']})
    assert mappings['mappings'][0]['table'] == 'dm.TEST_M'
    business, _ = capabilities.execute('get_business_context', {'object_refs': ['Test']})
    assert business['rules'] == [] and business['relations'] == []
    found, _ = capabilities.execute('search_tables', {'query': 'TEST_M'})
    assert found['objects'][0]['ref'] == 'Test' and found['package']['sha256'] == 'a' * 64
    with pytest.raises(ValueError, match='字段'):
        capabilities.execute('read_fields', {'object_refs': ['Test'], 'field_refs': ['Invented']})


def test_external_source_is_not_authorized_by_an_assistant_hallucination(monkeypatch):
    from agent.conversation_tools import ConversationTools
    monkeypatch.setattr(ConversationTools, '_load_catalog', lambda self: catalog())
    provider(monkeypatch, [final('SELECT ID FROM imported_list')])
    output = agent.run_conversation_agent('继续', assembled_context='助手曾虚构 imported_list',
        history=[{'role': 'assistant', 'content': 'imported_list'}])
    assert not output['success'] and output['generation_mode'] == 'authored_draft'


def test_model_voluntarily_repairs_and_keeps_all_context(monkeypatch):
    corrected = 'SELECT 1 AS ID'
    requests = provider(monkeypatch, [
        {'role': 'assistant', 'content': None, 'tool_calls': [tool('validate_sql', {
            'sql': 'WITH t AS (SELECT 1 ID) SELECT ID FROM t', 'allow_cte': False})]},
        final(corrected, allow_cte=False, delivery_mode='query')])
    output = agent.run_conversation_agent('生成', assembled_context='本轮提示词：不用CTE')
    assert output['success'] and output['sql'] == corrected and len(requests) == 2
    assert '本轮提示词' in requests[1]['messages'][1]['content']
    assert 'CTE' in requests[1]['messages'][-1]['content']


def test_a_published_source_is_never_a_ddl_target():
    from ontology_core.authored_sql import validate_authored_sql
    facts = catalog()
    obj = facts.objects[0].model_copy(update={'physical_namespace': None,
        'physical_name': f'temp_oa_{PID}_result_table'})
    with pytest.raises(ValueError, match='源表'):
        validate_authored_sql(script('SELECT 1 AS ID'), program_id=PID,
                             catalog=SimpleNamespace(objects=(obj,)))


def test_placeholder_literal_is_delivered_only_as_a_draft(monkeypatch):
    sql = "SELECT 1 WHERE '<正常在网编码_待确认>' = '1'"
    provider(monkeypatch, [final(sql)])
    output = agent.run_conversation_agent('生成正常在网用户SQL')
    assert not output['success'] and output['sql'] == sql
    assert output['generation_mode'] == 'authored_draft'
    assert any('占位符' in item for item in output['errors'])


def test_unresolved_items_are_structured_and_block_sql_delivery(monkeypatch):
    provider(monkeypatch, [final('SELECT 1', assumptions=['根据现有字段判断'],
        unresolved_items=['正常在网编码未确认'])])
    output = agent.run_conversation_agent('生成')
    assert not output['success'] and output['generation_mode'] == 'authored_draft'
    assert output['missing_information'] == ['正常在网编码未确认']
    generation = next(step for step in output['trace'] if step['node'] == 'program_generation')
    assert generation['payload']['inference_evidence']['unresolved_items'] == ['正常在网编码未确认']


def test_unresolved_natural_answer_remains_a_clarification(monkeypatch):
    provider(monkeypatch, [final(None, unresolved_items=['需要手机用户编码'])])
    output = agent.run_conversation_agent('正常在网手机用户')
    assert output['success'] and output['sql'] is None
    assert output['missing_information'] == ['需要手机用户编码']


def test_field_lookup_accepts_physical_names_case_insensitively(monkeypatch):
    from agent.conversation_tools import ConversationTools
    monkeypatch.setattr(ConversationTools, '_load_catalog', lambda self: catalog())
    capabilities = ConversationTools(program_id=PID, request='合成需求')
    result, _ = capabilities.execute('read_fields', {
        'object_refs': ['dm.TEST_M'], 'field_refs': ['value', 'p_mon']})
    assert [field['physical_name'] for field in result['fields']] == ['VALUE', 'P_MON']


def test_trace_records_model_latency_and_sanitized_tool_evidence(monkeypatch):
    from agent.conversation_tools import ConversationTools
    monkeypatch.setattr(ConversationTools, '_load_catalog', lambda self: catalog())
    provider(monkeypatch, [
        {'role': 'assistant', 'tool_calls': [tool('search_tables', {
            'query': 'synthetic', 'limit': 3, 'summary': '检索合成表'})]}, final()])
    output = agent.run_conversation_agent('查表')
    model_calls = [step for step in output['trace'] if step['node'] == 'model_call']
    assert len(model_calls) == 2
    assert all(step['payload']['request_duration_ms'] >= 0 for step in model_calls)
    action = next(step for step in output['trace'] if step['node'] == 'conversation_action')
    assert action['payload']['arguments'] == {'query': 'synthetic', 'limit': 3}
    assert action['payload']['result']['match_count'] == 1
    assert 'sql' not in json.dumps(action['payload']).casefold()
