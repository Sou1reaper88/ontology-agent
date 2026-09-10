from __future__ import annotations

import pytest
from pydantic import ValidationError

from ontology_core.errors import OntologyCompileError
from ontology_core.inference_models import CandidateField, CandidateObject
from ontology_core.program_compiler import HiveProgramCompiler
from ontology_core.program_models import ProgramStepKind
from ontology_core.relational_compiler import (
    HiveRelationalCompiler,
    RelationalCompilerRegistry,
)
from ontology_core.relational_plan import (
    AggregateColumn,
    AggregateNode,
    CanonicalRelationalPlan,
    DerivedColumn,
    FilterPredicate,
    JoinCondition,
    JoinNode,
    LogicalColumnRef,
    MaterializeNode,
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
        physical_name=name.upper(),
    )


def _object(ref: str, *fields: tuple[str, str]) -> CandidateObject:
    return CandidateObject(
        ref=ref,
        label=ref,
        data_source_ref="warehouse.primary",
        physical_namespace="synthetic",
        physical_name=f"{ref.upper()}_D",
        fields=tuple(_field(ref, name, datatype) for name, datatype in fields),
    )


def _union_join_plan(join_type: str = "left") -> CanonicalRelationalPlan:
    orders_a = _object(
        "OrdersA",
        ("customer_id", XSD_STRING),
        ("amount", XSD_INTEGER),
    )
    orders_b = _object(
        "OrdersB",
        ("customer_id", XSD_STRING),
        ("amount", XSD_INTEGER),
    )
    dimension = _object(
        "CustomerDimension",
        ("customer_id", XSD_STRING),
        ("segment", XSD_STRING),
    )
    join_columns = [
        DerivedColumn(
            name="customer_id",
            source=LogicalColumnRef(node_id="all_orders", column="customer_id"),
        ),
        DerivedColumn(
            name="amount",
            source=LogicalColumnRef(node_id="all_orders", column="amount"),
        ),
    ]
    if join_type != "anti":
        join_columns.append(
            DerivedColumn(
                name="segment",
                source=LogicalColumnRef(node_id="dimension_scan", column="segment"),
            )
        )
    return CanonicalRelationalPlan(
        package_id="synthetic.package",
        package_version="1.0.0",
        package_sha256="b" * 64,
        data_source_ref="warehouse.primary",
        dialect="hive",
        objects=(orders_a, orders_b, dimension),
        nodes=(
            ScanNode(
                node_id="orders_a_scan",
                object_ref="OrdersA",
                columns=(
                    ScanColumn(name="customer_id", field_ref="OrdersA.customer_id"),
                    ScanColumn(name="amount", field_ref="OrdersA.amount"),
                ),
            ),
            ScanNode(
                node_id="orders_b_scan",
                object_ref="OrdersB",
                columns=(
                    ScanColumn(name="customer_id", field_ref="OrdersB.customer_id"),
                    ScanColumn(name="amount", field_ref="OrdersB.amount"),
                ),
            ),
            UnionAllNode(
                node_id="all_orders",
                inputs=("orders_a_scan", "orders_b_scan"),
                columns=(
                    UnionColumn(
                        name="customer_id",
                        sources=(
                            LogicalColumnRef(
                                node_id="orders_a_scan",
                                column="customer_id",
                            ),
                            LogicalColumnRef(
                                node_id="orders_b_scan",
                                column="customer_id",
                            ),
                        ),
                    ),
                    UnionColumn(
                        name="amount",
                        sources=(
                            LogicalColumnRef(node_id="orders_a_scan", column="amount"),
                            LogicalColumnRef(node_id="orders_b_scan", column="amount"),
                        ),
                    ),
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
                node_id="joined",
                left_input="all_orders",
                right_input="dimension_scan",
                join_type=join_type,
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
                columns=tuple(join_columns),
            ),
            MaterializeNode(
                node_id="result",
                input="joined",
                step_kind=ProgramStepKind.RESULT,
            ),
        ),
        result_node_id="result",
    )


def _aggregate_plan() -> CanonicalRelationalPlan:
    orders = _object(
        "Orders",
        ("customer_id", XSD_STRING),
        ("segment", XSD_STRING),
    )
    return CanonicalRelationalPlan(
        package_id="synthetic.package",
        package_version="1.0.0",
        package_sha256="c" * 64,
        data_source_ref="warehouse.primary",
        dialect="hive",
        objects=(orders,),
        nodes=(
            ScanNode(
                node_id="orders_scan",
                object_ref="Orders",
                columns=(
                    ScanColumn(name="customer_id", field_ref="Orders.customer_id"),
                    ScanColumn(name="segment", field_ref="Orders.segment"),
                ),
            ),
            AggregateNode(
                node_id="counts",
                input="orders_scan",
                group_by=(
                    DerivedColumn(
                        name="segment",
                        source=LogicalColumnRef(node_id="orders_scan", column="segment"),
                    ),
                ),
                aggregations=(
                    AggregateColumn(
                        name="customer_count",
                        function="count",
                        source=LogicalColumnRef(
                            node_id="orders_scan",
                            column="customer_id",
                        ),
                        distinct=True,
                    ),
                ),
            ),
            MaterializeNode(
                node_id="result",
                input="counts",
                step_kind=ProgramStepKind.RESULT,
            ),
        ),
        result_node_id="result",
    )


def _materialized_pipeline_plan() -> CanonicalRelationalPlan:
    payload = _aggregate_plan().model_dump(mode="json")
    payload["nodes"].insert(
        1,
        {
            "kind": "materialize",
            "node_id": "staged",
            "input": "orders_scan",
            "step_kind": "intermediate",
        },
    )
    payload["nodes"][2]["input"] = "staged"
    payload["nodes"][2]["group_by"][0]["source"]["node_id"] = "staged"
    payload["nodes"][2]["aggregations"][0]["source"]["node_id"] = "staged"
    return CanonicalRelationalPlan.model_validate(payload)


def test_compiles_union_all_before_left_join_into_one_result_ctas() -> None:
    program = HiveRelationalCompiler().compile(
        _union_join_plan(),
        program_id="a1b2c3d4e5f6",
    )

    assert "UNION ALL" in program.sql
    assert "LEFT JOIN" in program.sql
    assert len(program.statements) == 1
    assert program.result_table == "temp_oa_a1b2c3d4e5f6_result_table"
    assert "DROP TABLE" not in program.statements[-1].create_sql
    HiveProgramCompiler().validate_program(program)


def test_compiles_anti_join_without_reversing_preserved_side() -> None:
    program = HiveRelationalCompiler().compile(
        _union_join_plan("anti"),
        program_id="a1b2c3d4e5f6",
    )

    assert "LEFT JOIN" in program.sql
    assert "IS NULL" in program.sql
    assert '"all_orders"."customer_id"' in program.statements[0].create_sql
    HiveProgramCompiler().validate_program(program)


def test_compiles_grouped_aggregation_from_logical_columns() -> None:
    program = HiveRelationalCompiler().compile(
        _aggregate_plan(),
        program_id="a1b2c3d4e5f6",
    )

    assert "COUNT(DISTINCT" in program.sql
    assert "GROUP BY" in program.sql
    HiveProgramCompiler().validate_program(program)


def test_compiler_rejects_non_hive_plan_and_user_physical_identifiers() -> None:
    payload = _union_join_plan().model_dump(mode="json")
    payload["dialect"] = "postgres"
    with pytest.raises(OntologyCompileError, match="方言"):
        HiveRelationalCompiler().compile(
            CanonicalRelationalPlan.model_validate(payload),
            program_id="a1b2c3d4e5f6",
        )

    injected = payload["nodes"][0]
    injected["sql"] = "DROP TABLE source_table"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CanonicalRelationalPlan.model_validate(payload)


def test_registry_resolves_hive_and_rejects_unknown_dialect() -> None:
    registry = RelationalCompilerRegistry.default()

    assert isinstance(registry.get("HIVE"), HiveRelationalCompiler)
    with pytest.raises(OntologyCompileError, match="方言"):
        registry.get("unknown")


def test_compiler_records_physical_evidence_and_node_lineage() -> None:
    program = HiveRelationalCompiler().compile(
        _union_join_plan(),
        program_id="a1b2c3d4e5f6",
    )

    assert program.evidence.source_tables == (
        "synthetic.CUSTOMERDIMENSION_D",
        "synthetic.ORDERSA_D",
        "synthetic.ORDERSB_D",
    )
    assert set(program.evidence.fields) == {"AMOUNT", "CUSTOMER_ID", "SEGMENT"}
    assert {(edge.source, edge.target, edge.kind) for edge in program.lineage} >= {
        ("synthetic.ORDERSA_D", "orders_a_scan", "ontology_source"),
        ("orders_a_scan", "all_orders", "step"),
        ("all_orders", "joined", "step"),
        ("joined", "result", "step"),
    }
    assert program.evidence.temporal_decisions == ()


def test_downstream_nodes_read_prior_materialization_target() -> None:
    program = HiveRelationalCompiler().compile(
        _materialized_pipeline_plan(),
        program_id="a1b2c3d4e5f6",
    )

    assert len(program.statements) == 2
    assert program.intermediate_tables == ("temp_oa_a1b2c3d4e5f6_01",)
    assert 'FROM "temp_oa_a1b2c3d4e5f6_01" AS "staged"' in program.statements[1].create_sql
    HiveProgramCompiler().validate_program(program)
