"""Synthetic SQL / mocked provider checks, not business accuracy measurements."""

import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from ontology_core.inference_models import CandidateContext, CandidateField, CandidateObject


PID = "a123456789abcdef"
TARGET = f"temp_oa_{PID}_result_table"


def catalog():
    fields = tuple(CandidateField(ref=f"Test{name}", object_ref="Test", label=name,
                                 physical_name=name, datatype_uri="string")
                   for name in ("ID", "VALUE", "P_MON"))
    obj = CandidateObject(ref="Test", label="synthetic", data_source_ref="Hive",
                          physical_namespace="dm", physical_name="TEST_M", fields=fields)
    ctx = CandidateContext(package_id="synthetic", package_version="1", package_sha256="a" * 64,
                           objects=(obj,))
    return SimpleNamespace(objects=(obj,), retrieve=lambda *a, **k: ctx,
                           field=lambda ref: next(f for f in fields if f.ref == ref))


def script(query, target=TARGET):
    return f"DROP TABLE IF EXISTS {target};\nCREATE TABLE {target} AS {query};"


def validate(sql, **kwargs):
    from ontology_core.authored_sql import validate_authored_program
    return validate_authored_program(sql, program_id=PID, catalog=catalog(), **kwargs)


def test_sql_is_not_rerendered_and_null_business_semantics_remain():
    sql = script("SELECT ID FROM dm.TEST_M WHERE P_MON='202607' AND COALESCE(VALUE,0)=0")
    program = validate(sql, assumptions=("该合成场景NULL表示无使用",))
    assert program.sql == sql
    assert "COALESCE" in program.sql
    assert program.evidence.inference.reasons == ("该合成场景NULL表示无使用",)


def test_cte_policy_is_enforced_on_ast_not_comments():
    sql = script("WITH t AS (SELECT ID FROM dm.TEST_M WHERE P_MON='202607') SELECT ID FROM t")
    assert validate(sql).sql == sql
    with pytest.raises(ValueError, match="CTE"):
        validate(sql, allow_cte=False)
    commented = script("SELECT ID /* WITH */ FROM dm.TEST_M WHERE P_MON='202607'")
    assert validate(commented, allow_cte=False).sql == commented


@pytest.mark.parametrize("query", [
    "SELECT INVENTED FROM dm.TEST_M WHERE P_MON='202607'",
    "SELECT ID FROM dm.TEST_M",
    "SELECT ID FROM dm.TEST_M WHERE P_MON >= '202607'",
    "SELECT ID FROM dm.TEST_M WHERE P_MON='202607' OR VALUE=0",
    "SELECT ID FROM dm.UNKNOWN_M WHERE P_MON='202607'",
    "SELECT ID FROM dm.TEST_M WHERE P_MON='202613'",
])
def test_invalid_sources_fields_or_unbounded_partitions_are_rejected(query):
    with pytest.raises(ValueError):
        validate(script(query))


def test_scoped_join_needs_no_registered_ontology_relation():
    sql = script("SELECT a.ID, COUNT(b.ID) AS cnt FROM dm.TEST_M a LEFT JOIN dm.TEST_M b "
                 "ON a.ID=b.ID AND b.P_MON='202607' WHERE a.P_MON='202607' "
                 "GROUP BY a.ID HAVING COUNT(b.ID)=0")
    assert validate(sql).sql == sql


def test_unsafe_ddl_and_trailing_cleanup_are_rejected():
    for sql in (script("SELECT ID FROM dm.TEST_M WHERE P_MON='202607'", target="dm.TEST_M"),
                script("SELECT ID FROM dm.TEST_M WHERE P_MON='202607'") + f"DROP TABLE {TARGET};"):
        with pytest.raises(ValueError):
            validate(sql)


def test_author_repair_is_bounded_and_receives_validation_errors(monkeypatch):
    from agent.sql_authoring import SqlAuthoringService
    from agent.program_generation import derive_program_id
    pid = derive_program_id("synthetic-request")
    target = f"temp_oa_{pid}_result_table"
    replies = [script("SELECT INVENTED FROM dm.TEST_M WHERE P_MON='202607'", target),
               script("SELECT ID FROM dm.TEST_M WHERE P_MON='202607'", target)]
    requests = []
    def generate(client, system, request, lookup, **kwargs):
        requests.append(json.loads(request))
        return json.dumps({"sql": replies.pop(0), "allow_cte": False, "assumptions": ["合成测试"]})
    monkeypatch.setattr("agent.sql_authoring.generate_with_field_lookup", generate)
    snapshot = SimpleNamespace(info=SimpleNamespace(sha256="a" * 64))
    service = SqlAuthoringService(client=SimpleNamespace(), runtime=SimpleNamespace(snapshot=lambda: snapshot),
                                  catalog_factory=lambda _: catalog())
    result = service.generate("合成需求禁止CTE", request_id="synthetic-request",
                              system_time=datetime(2026, 8, 24))
    assert result.mode.value == "authored_program"
    assert result.inferred_plan is None
    assert len(requests) == 2
    assert requests[1]["validation_errors"]
    assert requests[0]["default_partitions"] == {"P_DAY": "20260822", "P_MON": "202607"}
    assert result.sql == requests[1]["previous_sql"].replace("INVENTED", "ID")


def test_default_factory_uses_sql_author_not_relational_compiler():
    from agent.program_generation import get_program_generation_service
    assert type(get_program_generation_service()).__name__ == "SqlAuthoringService"


def test_multi_step_window_and_not_exists_are_preserved():
    intermediate = f"temp_oa_{PID}_01"
    first = script("SELECT ID, ROW_NUMBER() OVER(PARTITION BY ID ORDER BY VALUE) AS rn "
                   "FROM dm.TEST_M WHERE P_MON='202607'", intermediate)
    last = script(f"SELECT a.ID FROM {intermediate} a WHERE a.rn=1 AND NOT EXISTS "
                  "(SELECT 1 FROM dm.TEST_M b WHERE b.P_MON='202607' AND a.ID=b.ID)")
    sql = first + "\n" + last
    assert validate(sql).sql == sql


def test_explicit_external_table_is_allowed_but_not_claimed_verified():
    sql = script("SELECT ID FROM UPLOAD_LIST")
    program = validate(sql, request="使用外部表UPLOAD_LIST")
    assert program.evidence.inference.unresolved_items


def test_provider_failure_is_not_retried(monkeypatch):
    import httpx
    from agent.sql_authoring import SqlAuthoringService
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        raise httpx.ReadTimeout("synthetic")
    monkeypatch.setattr("agent.sql_authoring.generate_with_field_lookup", fail)
    snapshot = SimpleNamespace(info=SimpleNamespace(sha256="a" * 64))
    service = SqlAuthoringService(client=SimpleNamespace(), runtime=SimpleNamespace(snapshot=lambda: snapshot),
                                  catalog_factory=lambda _: catalog())
    result = service.generate("synthetic", request_id="test", system_time=datetime(2026, 8, 24))
    assert len(calls) == 1
    assert result.sql is None and result.diagnostics[0].code == "sql_author_timeout"
