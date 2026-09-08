import sqlite3

import pytest
import sqlglot

from ontology_core.errors import OntologyCompileError
from ontology_core.inference_compiler import HiveInferenceCompiler
from ontology_core.inference_models import (
    InferredProgramDraft, InferredJoinDraft, ValidatedInferredJoin, ValidatedInferredFilter,
)
from tests.ontology_core.test_inference_compiler import _object, _field_from, _plan
from tests.ontology_core.test_inference_validation import _validate, _object as validation_object


def join(customer, offer, kind="anti", strategy="left_join"):
    return ValidatedInferredJoin(
        left_object_ref=customer.ref, left_field=_field_from(customer, "CustomerId"),
        right_object_ref=offer.ref, right_field=_field_from(offer, "CustomerId"),
        confidence="medium", evidence=("客户编号一致",), join_type=kind,
        anti_strategy=strategy,
    )


def status(offer):
    return ValidatedInferredFilter(field=_field_from(offer, "Status"), operator="eq",
        values=("1",), confidence="medium", evidence=("状态1",))


def execute_synthetic(plan):
    sql = HiveInferenceCompiler().compile(plan, program_id="a1b2c3d4e5f6").statements[-1].create_sql
    query = sqlglot.parse_one(sql).expression.sql(dialect="sqlite")
    with sqlite3.connect(":memory:") as db:
        db.execute("ATTACH DATABASE ':memory:' AS dm")
        for obj in plan.objects:
            db.execute(f'CREATE TABLE dm."{obj.physical_name}" (CUSTOMERID TEXT, MOBILE TEXT, STATUS TEXT, PDAY TEXT)')
        db.executemany("INSERT INTO dm.CUSTOMER_D VALUES (?, ?, '1', '20260822')",
                       [("1", "one"), ("2", "two"), ("3", "three"), ("4", "four"), (None, "null")])
        db.executemany("INSERT INTO dm.OFFER_D VALUES (?, NULL, ?, ?)",
                       [("1", "1", "20260822"), ("1", "1", "20260822"),
                        ("3", "0", "20260822"), ("4", "1", "20260821"), (None, "1", "20260822")])
        if len(plan.objects) > 2:
            db.execute("INSERT INTO dm.HISTORY_D VALUES ('2', NULL, '1', '20260822')")
        return sql, sorted(row[0] for row in db.execute(query))


@pytest.mark.parametrize("strategy", ["left_join", "not_exists"])
def test_excludes_matches_in_either_table_with_scoped_partitions(strategy):
    customer, offer, history = (_object(name) for name in ("Customer", "Offer", "History"))
    sql, rows = execute_synthetic(_plan(customer, offer, history,
        joins=(join(customer, offer, strategy=strategy), join(customer, history, strategy=strategy)),
        filters=(status(offer), status(history))))
    assert rows == ["four", "null", "three"]
    if strategy == "left_join":
        assert sql.count("LEFT JOIN") == 2
        assert sql.count("IS NULL") == 2
    else:
        assert sql.count("NOT EXISTS") == 2


def test_plain_left_join_preserves_unmatched_users():
    customer, offer = _object("Customer"), _object("Offer")
    _, rows = execute_synthetic(_plan(customer, offer,
        joins=(join(customer, offer, kind="left"),), filters=(status(offer),)))
    assert rows == ["four", "null", "one", "one", "three", "two"]


def test_anti_right_cannot_supply_output():
    customer, offer = _object("Customer"), _object("Offer")
    with pytest.raises(OntologyCompileError, match="排除"):
        HiveInferenceCompiler().compile(_plan(customer, offer,
            joins=(join(customer, offer),), requested_fields=(_field_from(offer, "Mobile"),)),
            program_id="a1b2c3d4e5f6")


def test_core_missing_operation_blocks_validation():
    result = _validate(InferredProgramDraft(selected_object_refs=("Customer",),
        requested_field_refs=("CustomerMobile",), blocking_issues=("无法表达排除操作",)),
        validation_object("Customer"))
    assert result.plan is None
    assert result.diagnostics[0].code == "incomplete_inferred_semantics"


def test_join_semantics_survive_validation():
    result = _validate(InferredProgramDraft(selected_object_refs=("Customer", "Offer"),
        requested_field_refs=("CustomerMobile",), joins=(InferredJoinDraft(
            left_object_ref="Customer", left_field_ref="CustomerCustomerId",
            right_object_ref="Offer", right_field_ref="OfferCustomerId",
            confidence="medium", evidence=("客户编号一致",), join_type="anti",
            anti_strategy="not_exists"),)), validation_object("Customer"), validation_object("Offer"))
    assert result.plan is not None
    assert result.plan.joins[0].join_type == "anti"
    assert result.plan.joins[0].anti_strategy == "not_exists"


def test_reordered_objects_do_not_reverse_left_join():
    customer, offer = _object("Customer"), _object("Offer")
    plan = _plan(offer, customer, joins=(join(customer, offer, kind="left"),),
                 requested_fields=(_field_from(customer, "Mobile"),))
    sql = HiveInferenceCompiler().compile(plan, program_id="a1b2c3d4e5f6").sql
    assert 'FROM "dm"."CUSTOMER_D" AS "t1" LEFT JOIN "dm"."OFFER_D" AS "t0"' in sql


def test_left_with_explicit_where_null_is_equivalent_exclusion():
    customer, offer = _object("Customer"), _object("Offer")
    null_filter = ValidatedInferredFilter(field=_field_from(offer, "CustomerId"),
        operator="is_null", confidence="medium", evidence=("排除匹配用户",), scope="where")
    _, rows = execute_synthetic(_plan(customer, offer,
        joins=(join(customer, offer, kind="left"),), filters=(status(offer), null_filter)))
    assert rows == ["four", "null", "three", "two"]


def test_anti_right_cannot_be_reused_as_join_source():
    customer, offer, history = (_object(name) for name in ("Customer", "Offer", "History"))
    with pytest.raises(OntologyCompileError, match="排除"):
        HiveInferenceCompiler().compile(_plan(customer, offer, history,
            joins=(join(customer, offer), join(offer, history, kind="inner"))),
            program_id="a1b2c3d4e5f6")


def test_anti_where_scope_is_rejected_instead_of_changing_semantics():
    customer, offer = _object("Customer"), _object("Offer")
    with pytest.raises(OntologyCompileError, match="WHERE"):
        HiveInferenceCompiler().compile(_plan(customer, offer, joins=(join(customer, offer),),
            filters=(status(offer).model_copy(update={"scope": "where"}),)),
            program_id="a1b2c3d4e5f6")
