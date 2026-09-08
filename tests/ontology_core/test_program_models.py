from __future__ import annotations

import pytest
from pydantic import ValidationError

from ontology_core.program_models import (
    BusinessConstraintSpec,
    CompiledProgram,
    CompiledStatement,
    DraftProgramStep,
    DraftSqlProgramPlan,
    IntentSpec,
    LineageEdge,
    ProgramCompilationEvidence,
    ProgramStep,
    ProgramStepKind,
    ResultShapeSpec,
    SqlProgramPlan,
    StepSourceBinding,
    TimeIntentSpec,
)
from ontology_core.query_plan import BoundObject, BoundProperty, QueryPlan
from ontology_core.semantic_models import Concept, DataSource, PhysicalMapping, Property


def _intent() -> IntentSpec:
    return IntentSpec(
        normalized_request="查询客户编号",
        business_concepts=("Customer",),
        requested_properties=("CustomerId",),
        business_constraints=(),
        time_intent=TimeIntentSpec(source="default", requires_default=True),
        result_shape=ResultShapeSpec(),
    )


def _draft_step(
    step_id: str,
    *,
    kind: ProgramStepKind,
    source_step_id: str | None = None,
) -> DraftProgramStep:
    return DraftProgramStep(
        step_id=step_id,
        kind=kind,
        purpose="生成客户结果",
        source_objects=("Customer",),
        source_bindings=(
            StepSourceBinding(object_ref="Customer", source_step_id=source_step_id),
        ),
        requested_properties=("CustomerId",),
    )


def _query_plan() -> QueryPlan:
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
    object_mapping = PhysicalMapping(
        uri="https://example.invalid/CustomerMapping",
        short_name="CustomerMapping",
        label="客户表映射",
        labels=(),
        semantic_element_uri=concept.uri,
        data_source_uri=source.uri,
        physical_namespace="dm",
        object_name="customer",
    )
    property_mapping = PhysicalMapping(
        uri="https://example.invalid/CustomerIdMapping",
        short_name="CustomerIdMapping",
        label="客户编号映射",
        labels=(),
        semantic_element_uri=property_.uri,
        data_source_uri=source.uri,
        field_name="customer_id",
    )
    bound_object = BoundObject(alias="t0", semantic=concept, binding=object_mapping)
    bound_property = BoundProperty(
        semantic=property_,
        binding=property_mapping,
        object_alias="t0",
    )
    return QueryPlan(
        concepts=(concept,),
        data_source=source,
        objects=(bound_object,),
        selections=(bound_property,),
        property_bindings=(bound_property,),
    )


def test_draft_program_round_trip_preserves_structured_intent() -> None:
    plan = DraftSqlProgramPlan(
        intent=_intent(),
        steps=(_draft_step("result", kind=ProgramStepKind.RESULT),),
    )

    restored = DraftSqlProgramPlan.model_validate(plan.model_dump(mode="json"))

    assert restored == plan
    assert restored.intent.task_type == "data_extraction"
    assert restored.intent.output_mode == "materialized_table"


def test_draft_program_rejects_duplicate_step_ids() -> None:
    with pytest.raises(ValidationError, match="步骤标识必须唯一"):
        DraftSqlProgramPlan(
            intent=_intent(),
            steps=(
                _draft_step("duplicate", kind=ProgramStepKind.INTERMEDIATE),
                _draft_step("duplicate", kind=ProgramStepKind.RESULT),
            ),
        )


@pytest.mark.parametrize(
    "steps",
    (
        (_draft_step("only", kind=ProgramStepKind.INTERMEDIATE),),
        (
            _draft_step("first", kind=ProgramStepKind.RESULT),
            _draft_step("second", kind=ProgramStepKind.RESULT),
        ),
    ),
)
def test_draft_program_requires_exactly_one_result_step(
    steps: tuple[DraftProgramStep, ...],
) -> None:
    with pytest.raises(ValidationError, match="必须且只能包含一个结果步骤"):
        DraftSqlProgramPlan(intent=_intent(), steps=steps)


@pytest.mark.parametrize("dependency", ("result", "missing"))
def test_draft_program_rejects_self_or_unknown_dependencies(dependency: str) -> None:
    with pytest.raises(ValidationError, match="步骤依赖"):
        DraftSqlProgramPlan(
            intent=_intent(),
            steps=(
                _draft_step(
                    "result",
                    kind=ProgramStepKind.RESULT,
                    source_step_id=dependency,
                ),
            ),
        )


@pytest.mark.parametrize(
    ("extra_name", "extra_value"),
    (("target_table", "user_table"), ("sql", "DROP TABLE source_table")),
)
def test_draft_step_rejects_user_sql_and_target_fields(
    extra_name: str,
    extra_value: str,
) -> None:
    payload = _draft_step("result", kind=ProgramStepKind.RESULT).model_dump()
    payload[extra_name] = extra_value

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DraftProgramStep.model_validate(payload)


def test_sql_program_round_trip_preserves_package_identity() -> None:
    query_plan = _query_plan()
    plan = SqlProgramPlan(
        program_id="a1b2c3d4e5f6",
        package_id="example.package",
        package_version="1.0.0",
        package_sha256="a" * 64,
        data_source_id=query_plan.data_source.uri,
        dialect="hive",
        intent=_intent(),
        steps=(
            ProgramStep(
                step_id="result",
                kind=ProgramStepKind.RESULT,
                purpose="生成客户结果",
                source_objects=("Customer",),
                source_bindings=(StepSourceBinding(object_ref="Customer"),),
                query_plan=query_plan,
            ),
        ),
        result_step_id="result",
    )

    restored = SqlProgramPlan.model_validate(plan.model_dump(mode="json"))

    assert restored == plan
    assert restored.package_id == "example.package"
    assert restored.package_version == "1.0.0"
    assert restored.package_sha256 == "a" * 64


def test_compiled_program_round_trip_preserves_lineage_and_evidence() -> None:
    program = CompiledProgram(
        program_id="a1b2c3d4e5f6",
        dialect="hive",
        sql="DROP TABLE IF EXISTS temp_oa_a1b2c3d4e5f6_result_table;",
        statements=(
            CompiledStatement(
                step_id="result",
                target_table="temp_oa_a1b2c3d4e5f6_result_table",
                drop_sql="DROP TABLE IF EXISTS temp_oa_a1b2c3d4e5f6_result_table;",
                create_sql=(
                    "CREATE TABLE temp_oa_a1b2c3d4e5f6_result_table "
                    "AS SELECT customer_id FROM dm.customer;"
                ),
            ),
        ),
        intermediate_tables=(),
        result_table="temp_oa_a1b2c3d4e5f6_result_table",
        lineage=(LineageEdge(source="dm.customer", target="result", kind="ontology_source"),),
        evidence=ProgramCompilationEvidence(
            source_tables=("dm.customer",),
            fields=("customer_id",),
        ),
    )

    assert CompiledProgram.model_validate(program.model_dump(mode="json")) == program


def test_constraint_model_forbids_arbitrary_physical_identifier() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        BusinessConstraintSpec.model_validate(
            {
                "property_ref": "Status",
                "operator": "eq",
                "values": ["active"],
                "physical_field": "status_id",
            }
        )


@pytest.mark.parametrize(
    "payload",
    (
        {"aggregations": ["sum(amount); drop table source_table"]},
        {"group_by": ["customer_id; drop table source_table"]},
        {"order_by": ["customer_id desc; drop table source_table"]},
    ),
)
def test_result_shape_rejects_free_form_sql(payload: dict[str, list[str]]) -> None:
    with pytest.raises(ValidationError):
        ResultShapeSpec.model_validate(payload)
