import json
from types import SimpleNamespace

import pytest

from ontology_core.metadata_candidates import MetadataCandidateCatalog
from ontology_core.metadata_lookup import FieldDetailLookup
from tests.ontology_core.test_metadata_candidates import _snapshot
from tools.metadata_lookup import generate_with_field_lookup


def test_search_expands_validation_context_and_allows_details():
    catalog = MetadataCandidateCatalog.from_snapshot(_snapshot())
    initial = catalog.retrieve('湖州', object_limit=1)
    lookup = FieldDetailLookup(catalog, initial)
    result = lookup.search('杭州 手机号码')
    assert 'GsmHz' in {o['ref'] for o in result['objects']}
    assert 'GsmHz' in {o.ref for o in lookup.enriched().objects}
    assert lookup(['GsmHzMobile'])[0]['physical_name'] == 'MOBILE_NO'
    assert len(initial.objects) == 1
    assert lookup.enriched().package_sha256 == initial.package_sha256
    assert lookup.search('量子力学')['objects'] == []
    for query in ('', ' ' * 3, 'x' * 501, None):
        with pytest.raises(ValueError):
            lookup.search(query)


def test_model_can_search_then_read_details_then_finish(monkeypatch):
    catalog = MetadataCandidateCatalog.from_snapshot(_snapshot())
    lookup = FieldDetailLookup(catalog, catalog.retrieve('湖州', object_limit=1))
    steps = [('search_metadata', {'query': '杭州 手机号码'}),
             ('lookup_field_details', {'field_refs': ['GsmHzMobile']})]
    payloads = []

    def post(url, **kwargs):
        payloads.append(json.loads(json.dumps(kwargs['json'])))
        if steps:
            name, args = steps.pop(0)
            msg = {'role': 'assistant', 'content': None, 'tool_calls': [{
                'id': str(len(payloads)), 'type': 'function',
                'function': {'name': name, 'arguments': json.dumps(args)}}]}
        else:
            msg = {'role': 'assistant', 'content': '{"ok":true}'}
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
            'choices': [{'message': msg, 'finish_reason': 'stop'}]})

    monkeypatch.setattr('httpx.post', post)
    client = SimpleNamespace(api_key='synthetic', base_url='https://example.invalid',
                             model='test', temperature=0, max_tokens=None, timeout=1)
    assert generate_with_field_lookup(client, 'system', 'user', lookup) == '{"ok":true}'
    assert len(payloads) == 3
    assert {t['function']['name'] for t in payloads[0]['tools']} == {
        'search_metadata', 'lookup_field_details'}
    assert 'GsmHz' in {o.ref for o in lookup.enriched().objects}


def test_search_tool_round_budget_is_enforced(monkeypatch):
    catalog = MetadataCandidateCatalog.from_snapshot(_snapshot())
    lookup = FieldDetailLookup(catalog, catalog.retrieve('湖州', object_limit=1))
    choices = []

    def post(url, **kwargs):
        choices.append(kwargs['json']['tool_choice'])
        msg = {'role': 'assistant', 'tool_calls': [{
            'id': str(len(choices)), 'type': 'function', 'function': {
                'name': 'search_metadata', 'arguments': '{"query":"杭州"}'}}]}
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
            'choices': [{'message': msg, 'finish_reason': 'tool_calls'}]})

    monkeypatch.setattr('httpx.post', post)
    client = SimpleNamespace(api_key='synthetic', base_url='https://example.invalid',
                             model='test', temperature=0, max_tokens=None, timeout=1)
    with pytest.raises(ValueError):
        generate_with_field_lookup(client, 'system', 'user', lookup)
    assert choices == ['auto', 'auto', 'auto', 'none']
