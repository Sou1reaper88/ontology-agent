import sqlite3

import pytest
from pydantic import ValidationError

from ontology_core.inference_models import InferredFilterDraft, InferredProgramDraft
from ontology_core.relational_compiler import HiveRelationalCompiler
from tests.ontology_core.test_inference_to_relational import _convert, _join
from tests.ontology_core.test_inference_validation import _object, _validate


def leaf(ref, operator="eq", values=("1",), scope="match"):
    return dict(field_ref=ref, operator=operator, values=values, scope=scope,
                confidence="medium", evidence=("状态值 1 表示有效",))


def group(operator, *children, scope="match"):
    return InferredFilterDraft(operator=operator, children=children, scope=scope,
                               confidence="medium", evidence=("按需求保留布尔逻辑",))


def test_nested_boolean_filters_compile_and_preserve_null_semantics():
    predicate = group("all_of",
        group("any_of", leaf("CustomerStatus", "is_null", ()), leaf("CustomerStatus")),
        group("not", leaf("CustomerMobile", "is_null", ())),
    )
    plan = _convert(InferredProgramDraft(selected_object_refs=("Customer",),
                    requested_field_refs=("CustomerMobile",), filters=(predicate,)), _object("Customer"))
    program = HiveRelationalCompiler().compile(plan, program_id="a" * 16)
    assert " OR " in program.sql and "NOT (" in program.sql
    connection = sqlite3.connect(":memory:")
    connection.execute("ATTACH DATABASE ':memory:' AS dm")
    connection.execute("CREATE TABLE dm.CUSTOMER_D(CUSTOMERID TEXT, MOBILE TEXT, STATUS TEXT, PDAY TEXT)")
    connection.executemany("INSERT INTO dm.CUSTOMER_D VALUES(?,?,?,?)", [
        ("1", "null-status", None, "20260822"), ("2", "one", "1", "20260822"),
        ("3", "other", "2", "20260822"), ("4", None, "1", "20260822"),
        ("5", "old", "1", "20260821"),
    ])
    connection.executescript(program.sql)
    assert set(connection.execute(f'SELECT MOBILE FROM {program.result_table}')) == {("null-status",), ("one",)}
    connection.close()


def test_boolean_right_match_stays_inside_left_join_on():
    predicate = group("any_of", leaf("OfferStatus", "is_null", ()), leaf("OfferStatus"))
    plan = _convert(InferredProgramDraft(selected_object_refs=("Customer", "Offer"),
        requested_field_refs=("CustomerMobile",), joins=(_join(join_type="left"),),
        filters=(predicate,)), _object("Customer"), _object("Offer"))
    sql = HiveRelationalCompiler().compile(plan, program_id="a" * 16).sql
    assert " OR " in sql.split("LEFT JOIN", 1)[1].split("),", 1)[0]


def test_boolean_leaf_is_still_metadata_bound():
    predicate = group("any_of", leaf("MissingStatus"), leaf("CustomerStatus"))
    result = _validate(InferredProgramDraft(selected_object_refs=("Customer",),
        requested_field_refs=("CustomerMobile",), filters=(predicate,)), _object("Customer"))
    assert result.plan is None and result.diagnostics[0].code == "invalid_filter_reference"


@pytest.mark.parametrize("operator,children", [("any_of", ()), ("not", (leaf("CustomerStatus"), leaf("CustomerStatus")))])
def test_invalid_boolean_shape_rejected(operator, children):
    with pytest.raises(ValidationError):
        group(operator, *children)


def test_boolean_scopes_cannot_be_mixed():
    with pytest.raises(ValidationError):
        group("any_of", leaf("CustomerStatus"), leaf("CustomerStatus", scope="where"))


def test_cross_object_match_or_reports_scope_problem():
    predicate = group("any_of", leaf("CustomerStatus"), leaf("OfferStatus"))
    result = _validate(InferredProgramDraft(selected_object_refs=("Customer", "Offer"),
        requested_field_refs=("CustomerMobile",), joins=(_join(join_type="left"),), filters=(predicate,)),
        _object("Customer"), _object("Offer"))
    assert result.plan is None and result.diagnostics[0].code == "ambiguous_boolean_scope"


def test_cross_object_where_or_is_not_split_into_and():
    predicate = group("any_of", leaf("CustomerStatus", scope="where"),
        leaf("OfferStatus", "is_null", (), scope="where"), scope="where")
    plan = _convert(InferredProgramDraft(selected_object_refs=("Customer", "Offer"),
        requested_field_refs=("CustomerMobile",), joins=(_join(join_type="left"),), filters=(predicate,)),
        _object("Customer"), _object("Offer"))
    sql = HiveRelationalCompiler().compile(plan, program_id="a" * 16).sql
    assert " OR " in sql.split("LEFT JOIN", 1)[1].split("WHERE", 1)[1]
