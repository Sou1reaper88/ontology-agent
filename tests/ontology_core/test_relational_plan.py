from __future__ import annotations

import pytest
from pydantic import ValidationError

from ontology_core.inference_models import CandidateField, CandidateObject
from ontology_core.program_models import ProgramStepKind
from ontology_core.relational_plan import (
    AggregateColumn,
    AggregateNode,
    CanonicalRelationalPlan,
    DerivedColumn,
    FilterNode,
    FilterPredicate,
    JoinCondition,
    JoinNode,
    LogicalColumnRef,
    MaterializeNode,
    ProjectNode,
    ScanColumn,
    ScanNode,
    UnionAllNode,
    UnionColumn,
)

XSD_INTEGER = "http://www.w3.org/2001/XMLSchema#integer"
XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"


def _field(object_ref: str, name: str, datatype_uri: str = XSD_STRING) -> CandidateField:
    return CandidateField(
        ref=f"{object_ref}.{name}",
        object_ref=object_ref,
        label=name,
        datatype_uri=datatype_uri,
        physical_name=name,
    )


def _object(ref: str, *fields: tuple[str, str]) -> CandidateObject:
    return CandidateObject(
        ref=ref,
        label=ref,
        data_source_ref="warehouse.primary",
        physical_namespace="synthetic",
        physical_name=ref.casefold(),
        fields=tuple(_field(ref, name, datatype) for name, datatype in fields),
    )


def _valid_plan() -> CanonicalRelationalPlan:
    orders_a = _object(
        "OrdersA",
        ("customer_id", XSD_STRING),
        ("amount", XSD_INTEGER),
        ("status", XSD_STRING),
    )
    orders_b = _object(
        "OrdersB",
        ("customer_id", XSD_STRING),
        ("amount", XSD_INTEGER),
        ("status", XSD_STRING),
    )
    dimension = _object(
        "CustomerDimension",
        ("customer_id", XSD_STRING),
        ("segment", XSD_STRING),
    )
    scan_columns = (
        ScanColumn(name="customer_id", field_ref="OrdersA.customer_id"),
        ScanColumn(name="amount", field_ref="OrdersA.amount"),
        ScanColumn(name="status", field_ref="OrdersA.status"),
    )
    return CanonicalRelationalPlan(
        package_id="synthetic.package",
        package_version="1.0.0",
        package_sha256="a" * 64,
        data_source_ref="warehouse.primary",
        dialect="hive",
        objects=(orders_a, orders_b, dimension),
        nodes=(
            ScanNode(node_id="orders_a_scan", object_ref="OrdersA", columns=scan_columns),
            UnionAllNode(
                node_id="orders_a_twice",
                inputs=("orders_a_scan", "orders_a_scan"),
                columns=tuple(
                    UnionColumn(
                        name=column.name,
                        sources=(
                            LogicalColumnRef(node_id="orders_a_scan", column=column.name),
                            LogicalColumnRef(node_id="orders_a_scan", column=column.name),
                        ),
                    )
                    for column in scan_columns
                ),
            ),
            UnionAllNode(
                node_id="all_orders",
                inputs=("orders_a_scan", "orders_a_twice"),
                columns=tuple(
                    UnionColumn(
                        name=column.name,
                        sources=(
                            LogicalColumnRef(node_id="orders_a_scan", column=column.name),
                            LogicalColumnRef(node_id="orders_a_twice", column=column.name),
                        ),
                    )
                    for column in scan_columns
                ),
            ),
            ScanNode(
                node_id="dimension_scan",
                object_ref="CustomerDimension",
                columns=(
                    ScanColumn(
                        name="customer_id",
                        field_ref="CustomerDimension.customer_id",
                    ),
                    ScanColumn(name="segment", field_ref="CustomerDimension.segment"),
                ),
            ),
            JoinNode(
                node_id="orders_with_segment",
                left_input="all_orders",
                right_input="dimension_scan",
                join_type="left",
                conditions=(
                    JoinCondition(
                        left=LogicalColumnRef(node_id="all_orders", column="customer_id"),
                        right=LogicalColumnRef(
                            node_id="dimension_scan",
                            column="customer_id",
                        ),
                    ),
                ),
                match_filters=(
                    FilterPredicate(
                        column=LogicalColumnRef(node_id="dimension_scan", column="segment"),
                        operator="ne",
                        values=("inactive",),
                    ),
                ),
                columns=(
                    DerivedColumn(
                        name="customer_id",
                        source=LogicalColumnRef(node_id="all_orders", column="customer_id"),
                    ),
                    DerivedColumn(
                        name="amount",
                        source=LogicalColumnRef(node_id="all_orders", column="amount"),
                    ),
                    DerivedColumn(
                        name="status",
                        source=LogicalColumnRef(node_id="all_orders", column="status"),
                    ),
                    DerivedColumn(
                        name="segment",
                        source=LogicalColumnRef(node_id="dimension_scan", column="segment"),
                    ),
                ),
            ),
            FilterNode(
                node_id="active_orders",
                input="orders_with_segment",
                predicates=(
                    FilterPredicate(
                        column=LogicalColumnRef(
                            node_id="orders_with_segment",
                            column="status",
                        ),
                        operator="eq",
                        values=("active",),
                    ),
                ),
            ),
            ProjectNode(
                node_id="projected_orders",
                input="active_orders",
                columns=(
                    DerivedColumn(
                        name="customer_id",
                        source=LogicalColumnRef(node_id="active_orders", column="customer_id"),
                    ),
                    DerivedColumn(
                        name="amount",
                        source=LogicalColumnRef(node_id="active_orders", column="amount"),
                    ),
                    DerivedColumn(
                        name="segment",
                        source=LogicalColumnRef(node_id="active_orders", column="segment"),
                    ),
                ),
            ),
            AggregateNode(
                node_id="order_counts",
                input="projected_orders",
                group_by=(
                    DerivedColumn(
                        name="segment",
                        source=LogicalColumnRef(node_id="projected_orders", column="segment"),
                    ),
                ),
                aggregations=(
                    AggregateColumn(
                        name="customer_count",
                        function="count",
                        source=LogicalColumnRef(
                            node_id="projected_orders",
                            column="customer_id",
                        ),
                        distinct=True,
                    ),
                ),
            ),
            MaterializeNode(
                node_id="result",
                input="order_counts",
                step_kind=ProgramStepKind.RESULT,
            ),
        ),
        result_node_id="result",
    )


def test_plan_round_trip_preserves_union_join_and_materialization() -> None:
    plan = _valid_plan()

    restored = CanonicalRelationalPlan.model_validate(plan.model_dump(mode="json"))

    assert restored == plan


def test_plan_rejects_unknown_or_forward_node_reference() -> None:
    payload = _valid_plan().model_dump(mode="json")
    payload["nodes"][1]["inputs"][0] = "future_source"

    with pytest.raises(ValidationError, match="上游节点"):
        CanonicalRelationalPlan.model_validate(payload)


def test_union_requires_one_compatible_source_column_per_input() -> None:
    payload = _valid_plan().model_dump(mode="json")
    payload["nodes"][2]["columns"][0]["sources"].pop()

    with pytest.raises(ValidationError, match="并集"):
        CanonicalRelationalPlan.model_validate(payload)


def test_left_and_anti_join_conditions_preserve_declared_sides() -> None:
    payload = _valid_plan().model_dump(mode="json")
    payload["nodes"][4]["conditions"][0]["left"]["node_id"] = "dimension_scan"

    with pytest.raises(ValidationError, match="左右输入"):
        CanonicalRelationalPlan.model_validate(payload)


def test_plan_rejects_cross_snapshot_or_cross_datasource_objects() -> None:
    payload = _valid_plan().model_dump(mode="json")
    payload["objects"][1]["data_source_ref"] = "warehouse.secondary"

    with pytest.raises(ValidationError, match="同一数据源"):
        CanonicalRelationalPlan.model_validate(payload)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda payload: payload["nodes"].__setitem__(
                1,
                {**payload["nodes"][1], "node_id": "orders_a_scan"},
            ),
            "节点标识",
        ),
        (
            lambda payload: payload["nodes"][0]["columns"].append(
                payload["nodes"][0]["columns"][0]
            ),
            "输出列",
        ),
        (
            lambda payload: payload["nodes"][0]["columns"][0].__setitem__(
                "field_ref", "OrdersB.customer_id"
            ),
            "扫描字段",
        ),
        (
            lambda payload: payload["nodes"][2]["columns"][1]["sources"][0].__setitem__(
                "column", "customer_id"
            ),
            "并集",
        ),
        (
            lambda payload: payload["nodes"][5]["predicates"][0]["column"].__setitem__(
                "node_id", "all_orders"
            ),
            "直接输入",
        ),
        (
            lambda payload: payload["nodes"][6]["columns"][0]["source"].__setitem__(
                "column", "missing"
            ),
            "输出列",
        ),
    ],
)
def test_plan_rejects_invalid_node_contracts(mutate, message: str) -> None:
    payload = _valid_plan().model_dump(mode="json")
    mutate(payload)

    with pytest.raises(ValidationError, match=message):
        CanonicalRelationalPlan.model_validate(payload)


def test_anti_join_can_only_project_the_preserved_left_input() -> None:
    payload = _valid_plan().model_dump(mode="json")
    payload["nodes"][4]["join_type"] = "anti"

    with pytest.raises(ValidationError, match="排除连接"):
        CanonicalRelationalPlan.model_validate(payload)


def test_result_must_be_the_only_result_materialization() -> None:
    payload = _valid_plan().model_dump(mode="json")
    payload["nodes"].insert(
        -1,
        {
            "kind": "materialize",
            "node_id": "other_result",
            "input": "order_counts",
            "step_kind": "result",
        },
    )

    with pytest.raises(ValidationError, match="唯一.*RESULT"):
        CanonicalRelationalPlan.model_validate(payload)


def test_public_package_exports_relational_contracts_and_compiler() -> None:
    import ontology_core

    assert ontology_core.CanonicalRelationalPlan is CanonicalRelationalPlan
    assert ontology_core.ScanNode is ScanNode
    assert ontology_core.HiveRelationalCompiler.platform == "hive"
    assert isinstance(
        ontology_core.RelationalCompilerRegistry.default().get("hive"),
        ontology_core.HiveRelationalCompiler,
    )
