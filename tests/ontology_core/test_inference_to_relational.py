from __future__ import annotations

import sqlite3

import pytest

from ontology_core.errors import OntologyCompileError
from ontology_core.inference_models import (
    CandidateTableFamily,
    InferredAggregationDraft,
    InferredFilterDraft,
    InferredJoinDraft,
    InferredProgramDraft,
)
from ontology_core.inference_to_relational import InferenceRelationalAdapter
from ontology_core.relation_evidence import RelationEvidenceEdge, RelationEvidenceGraph
from ontology_core.relational_compiler import HiveRelationalCompiler
from ontology_core.relational_plan import (
    AggregateNode,
    JoinNode,
    MaterializeNode,
    ScanNode,
    UnionAllNode,
)
from tests.ontology_core.test_inference_validation import _object, _validate


def _join(left="Customer", right="Offer", **changes):
    return InferredJoinDraft(
        left_object_ref=left,
        left_field_ref=f"{left}CustomerId",
        right_object_ref=right,
        right_field_ref=f"{right}CustomerId",
        confidence="medium",
        evidence=("用户标识字段类型与描述一致",),
        **changes,
    )


def _graph(plan):
    return RelationEvidenceGraph(
        package_sha256=plan.package_sha256,
        object_refs=tuple(obj.ref for obj in plan.objects),
        edges=tuple(
            RelationEvidenceEdge(
                left_object_ref=join.left_object_ref,
                left_field_ref=join.left_field.ref,
                right_object_ref=join.right_object_ref,
                right_field_ref=join.right_field.ref,
                join_type=join.join_type,
                source="model",
                confidence=join.confidence,
                evidence=join.evidence,
            )
            for join in plan.joins
        ),
    )


def _convert(draft, *objects, families=()):
    result = _validate(draft, *objects, families=families)
    assert result.plan is not None, result.diagnostics
    return InferenceRelationalAdapter().convert(result.plan, _graph(result.plan))


def test_single_table_time_and_filter_become_canonical_nodes():
    plan = _convert(
        InferredProgramDraft(
            selected_object_refs=("Customer",),
            requested_field_refs=("CustomerMobile",),
            filters=(
                InferredFilterDraft(
                    field_ref="CustomerStatus",
                    operator="eq",
                    values=("1",),
                    confidence="medium",
                    evidence=("状态 1 表示有效",),
                ),
            ),
        ),
        _object("Customer"),
    )
    assert [node.kind for node in plan.nodes] == ["scan", "filter", "project", "materialize"]
    program = HiveRelationalCompiler().compile(plan, program_id="a" * 16)
    assert "20260822" in program.sql
    assert 'AS "MOBILE"' in program.sql
    assert program.sql.count("20260822") == 1


def test_family_is_union_then_intermediate_materialization_before_join():
    family = CandidateTableFamily(
        ref="family.gsm", label="同类来源", member_refs=("GsmHu", "GsmHz"), varying_token_index=4
    )
    plan = _convert(
        InferredProgramDraft(
            selected_object_refs=("GsmHu", "Customer"),
            selected_family_refs=("family.gsm",),
            requested_field_refs=("GsmHuMobile", "CustomerStatus"),
            joins=(_join("GsmHu", "Customer", join_type="left"),),
        ),
        _object("GsmHu"),
        _object("GsmHz"),
        _object("Customer"),
        families=(family,),
    )
    union_index = next(i for i, node in enumerate(plan.nodes) if isinstance(node, UnionAllNode))
    assert isinstance(plan.nodes[union_index + 1], MaterializeNode)
    assert plan.nodes[union_index + 1].step_kind == "intermediate"
    program = HiveRelationalCompiler().compile(plan, program_id="a" * 16)
    assert len(program.statements) == 2
    assert "UNION ALL" in program.statements[0].create_sql
    assert "LEFT JOIN" in program.statements[1].create_sql


def test_three_table_inner_joins_are_reoriented_without_changing_conditions():
    plan = _convert(
        InferredProgramDraft(
            selected_object_refs=("Customer", "Offer", "Events"),
            requested_field_refs=("CustomerMobile",),
            joins=(_join("Events", "Offer"), _join("Offer", "Customer")),
        ),
        _object("Customer"),
        _object("Offer"),
        _object("Events"),
    )
    joins = [node for node in plan.nodes if isinstance(node, JoinNode)]
    scans = {node.object_ref: node.node_id for node in plan.nodes if isinstance(node, ScanNode)}
    assert len(joins) == 2
    assert joins[0].right_input.startswith("filter_")
    assert joins[0].conditions[0].left.node_id == joins[0].left_input
    assert "Customer" in scans


@pytest.mark.parametrize("strategy", ["left_join", "not_exists"])
def test_anti_join_retains_direction_match_filters_and_strategy(strategy):
    plan = _convert(
        InferredProgramDraft(
            selected_object_refs=("Customer", "Offer"),
            requested_field_refs=("CustomerMobile",),
            joins=(_join(join_type="anti", anti_strategy=strategy),),
            filters=(
                InferredFilterDraft(
                    field_ref="OfferStatus",
                    operator="eq",
                    values=("1",),
                    confidence="medium",
                    evidence=("状态 1 表示有效",),
                ),
            ),
        ),
        _object("Customer"),
        _object("Offer"),
    )
    join = next(node for node in plan.nodes if isinstance(node, JoinNode))
    assert join.join_type == "anti"
    assert join.anti_strategy == strategy
    assert len(join.match_filters) == 2
    program = HiveRelationalCompiler().compile(plan, program_id="a" * 16)
    db = sqlite3.connect(":memory:")
    db.execute("ATTACH DATABASE ':memory:' AS dm")
    for table in ("CUSTOMER_D", "OFFER_D"):
        db.execute(f"CREATE TABLE dm.{table}(CUSTOMERID TEXT, MOBILE TEXT, STATUS TEXT, PDAY TEXT)")
    db.executemany(
        "INSERT INTO dm.CUSTOMER_D VALUES (?,?,?,?)",
        [
            ("1", "one", "1", "20260822"),
            ("2", "two", "1", "20260822"),
            ("3", "three", "1", "20260822"),
        ],
    )
    db.executemany(
        "INSERT INTO dm.OFFER_D VALUES (?,?,?,?)",
        [
            ("1", "one", "1", "20260822"),
            ("2", "two", "9", "20260822"),
            ("3", "three", "1", "20260821"),
        ],
    )
    db.executescript(program.sql)
    assert db.execute(f"SELECT MOBILE FROM {program.result_table} ORDER BY MOBILE").fetchall() == [
        ("three",),
        ("two",),
    ]
    db.close()


def test_left_right_where_remains_post_join():
    plan = _convert(
        InferredProgramDraft(
            selected_object_refs=("Customer", "Offer"),
            requested_field_refs=("CustomerMobile",),
            joins=(_join(join_type="left"),),
            filters=(
                InferredFilterDraft(
                    field_ref="OfferCustomerId",
                    operator="is_null",
                    scope="where",
                    confidence="medium",
                    evidence=("排查不匹配用户",),
                ),
            ),
        ),
        _object("Customer"),
        _object("Offer"),
    )
    join_index = next(i for i, node in enumerate(plan.nodes) if isinstance(node, JoinNode))
    assert plan.nodes[join_index + 1].kind == "filter"
    assert plan.nodes[join_index + 1].predicates[0].column.node_id == plan.nodes[join_index].node_id


def test_grouped_count_becomes_aggregate_node():
    plan = _convert(
        InferredProgramDraft(
            selected_object_refs=("Customer",),
            requested_field_refs=("CustomerStatus",),
            group_by_field_refs=("CustomerStatus",),
            aggregations=(
                InferredAggregationDraft(
                    name="user_count",
                    function="count",
                    source_field_ref="CustomerCustomerId",
                    distinct=True,
                ),
            ),
        ),
        _object("Customer"),
    )
    assert any(isinstance(node, AggregateNode) for node in plan.nodes)
    assert "COUNT(DISTINCT" in HiveRelationalCompiler().compile(plan, program_id="a" * 16).sql


def test_adapter_rejects_missing_evidence_and_changed_snapshot():
    result = _validate(
        InferredProgramDraft(
            selected_object_refs=("Customer", "Offer"),
            requested_field_refs=("CustomerMobile",),
            joins=(_join(),),
        ),
        _object("Customer"),
        _object("Offer"),
    )
    graph = _graph(result.plan)
    for changed in (
        graph.model_copy(update={"edges": ()}),
        graph.model_copy(update={"package_sha256": "b" * 64}),
    ):
        with pytest.raises(OntologyCompileError):
            InferenceRelationalAdapter().convert(result.plan, changed)
