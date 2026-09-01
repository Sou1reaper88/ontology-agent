from __future__ import annotations

import pytest
import sqlglot

from ontology_core.errors import OntologyCompileError
from ontology_core.program_compiler import (
    HiveProgramCompiler,
    ProgramCompilerRegistry,
    ProgramTableNamer,
)
from ontology_core.program_models import (
    IntentSpec,
    ProgramStep,
    ProgramStepKind,
    ResultShapeSpec,
    SqlProgramPlan,
    StepSourceBinding,
    TimeIntentSpec,
)
from ontology_core.query_plan import BoundObject, BoundProperty, QueryPlan
from ontology_core.semantic_models import Concept, DataSource, PhysicalMapping, Property


def _query_plan(*, object_name: str = "customer") -> QueryPlan:
    concept = Concept(
        uri="https://example.invalid/Customer",
        short_name="Customer",
        label="客户",
        labels=(),
    )
    property_ = Property(
        uri="https://example.invalid/CustomerId",
        short_name="CustomerId",
        label="客户编号",
        labels=(),
        concept_uri=concept.uri,
        datatype_uri="http://www.w3.org/2001/XMLSchema#string",
    )
    source = DataSource(
        uri="https://example.invalid/Hive",
        short_name="Hive",
        label="Hive",
        labels=(),
        platform_type="hive",
        dialect="hive",
    )
    bound_object = BoundObject(
        alias="t0",
        semantic=concept,
        binding=PhysicalMapping(
            uri="https://example.invalid/CustomerTable",
            short_name="CustomerTable",
            label="客户表",
            labels=(),
            semantic_element_uri=concept.uri,
            data_source_uri=source.uri,
            physical_namespace="dm",
            object_name=object_name,
        ),
    )
    bound_property = BoundProperty(
        semantic=property_,
        binding=PhysicalMapping(
            uri="https://example.invalid/CustomerIdField",
            short_name="CustomerIdField",
            label="客户编号字段",
            labels=(),
            semantic_element_uri=property_.uri,
            data_source_uri=source.uri,
            field_name="customer_id",
        ),
        object_alias="t0",
    )
    return QueryPlan(
        concepts=(concept,),
        data_source=source,
        objects=(bound_object,),
        selections=(bound_property,),
        property_bindings=(bound_property,),
    )


def _intent() -> IntentSpec:
    return IntentSpec(
        normalized_request="生成客户结果",
        business_concepts=("Customer",),
        requested_properties=("CustomerId",),
        time_intent=TimeIntentSpec(),
        result_shape=ResultShapeSpec(),
    )


def _program_plan(
    *,
    program_id: str = "a1b2c3d4e5f6",
    object_name: str = "customer",
    two_steps: bool = True,
) -> SqlProgramPlan:
    query_plan = _query_plan(object_name=object_name)
    steps = []
    if two_steps:
        steps.append(
            ProgramStep(
                step_id="base",
                kind=ProgramStepKind.INTERMEDIATE,
                purpose="准备客户明细",
                source_objects=("Customer",),
                source_bindings=(StepSourceBinding(object_ref="Customer"),),
                query_plan=query_plan,
            )
        )
    steps.append(
        ProgramStep(
            step_id="result",
            kind=ProgramStepKind.RESULT,
            purpose="生成客户结果",
            source_objects=("Customer",),
            source_bindings=(
                StepSourceBinding(
                    object_ref="Customer",
                    source_step_id="base" if two_steps else None,
                ),
            ),
            query_plan=query_plan,
        )
    )
    return SqlProgramPlan(
        program_id=program_id,
        package_id="example.program",
        package_version="1.0.0",
        package_sha256="a" * 64,
        data_source_id=query_plan.data_source.uri,
        dialect="hive",
        intent=_intent(),
        steps=tuple(steps),
        result_step_id="result",
    )


def test_table_namer_is_deterministic_and_sanitizes_input() -> None:
    namer = ProgramTableNamer()

    assert namer.target_for("a1b2c3d4e5f6", 1, ProgramStepKind.INTERMEDIATE) == (
        "temp_oa_a1b2c3d4e5f6_01"
    )
    assert namer.target_for("a1b2c3d4e5f6", 2, ProgramStepKind.RESULT) == (
        "temp_oa_a1b2c3d4e5f6_result_table"
    )
    hostile = namer.target_for(
        "request; DROP TABLE source --",
        1,
        ProgramStepKind.INTERMEDIATE,
    )
    assert ";" not in hostile
    assert "--" not in hostile
    assert hostile.startswith("temp_oa_")


def test_compiler_emits_ordered_drop_create_pairs_and_dependency_override() -> None:
    compiler = HiveProgramCompiler()

    compiled = compiler.compile(_program_plan())

    assert tuple(item.target_table for item in compiled.statements) == (
        "temp_oa_a1b2c3d4e5f6_01",
        "temp_oa_a1b2c3d4e5f6_result_table",
    )
    assert compiled.sql.count("DROP TABLE IF EXISTS") == 2
    assert compiled.sql.count("CREATE TABLE") == 2
    assert 'FROM "dm"."customer"' in compiled.statements[0].create_sql
    assert 'FROM "temp_oa_a1b2c3d4e5f6_01"' in compiled.statements[1].create_sql
    assert not compiled.sql.rstrip().endswith(
        "DROP TABLE IF EXISTS temp_oa_a1b2c3d4e5f6_01;"
    )
    assert len(sqlglot.parse(compiled.sql, read="hive")) == 4


def test_compiler_output_is_stable_and_records_lineage() -> None:
    compiler = HiveProgramCompiler()
    plan = _program_plan()

    first = compiler.compile(plan)
    second = compiler.compile(plan)

    assert first == second
    assert first.intermediate_tables == ("temp_oa_a1b2c3d4e5f6_01",)
    assert first.result_table == "temp_oa_a1b2c3d4e5f6_result_table"
    assert first.evidence.source_tables == ("dm.customer",)
    assert {(item.source, item.target, item.kind) for item in first.lineage} == {
        ("dm.customer", "base", "ontology_source"),
        ("base", "result", "step"),
    }


def test_safety_validator_rejects_extra_or_forbidden_statement() -> None:
    compiler = HiveProgramCompiler()
    compiled = compiler.compile(_program_plan())
    tampered = compiled.model_copy(
        update={"sql": compiled.sql + "\nDROP TABLE dm.customer;"}
    )

    with pytest.raises(OntologyCompileError, match="语句"):
        compiler.validate_program(tampered)


def test_compiler_rejects_source_table_target_collision() -> None:
    target = "temp_oa_a1b2c3d4e5f6_result_table"
    plan = _program_plan(object_name=target, two_steps=False)

    with pytest.raises(OntologyCompileError, match="源表"):
        HiveProgramCompiler().compile(plan)


def test_program_compiler_registry_resolves_hive_and_rejects_unknown() -> None:
    registry = ProgramCompilerRegistry.default()

    assert isinstance(registry.get("HIVE"), HiveProgramCompiler)
    with pytest.raises(OntologyCompileError, match="方言"):
        registry.get("unknown")
