from __future__ import annotations

import pytest
import sqlglot

from ontology_core.errors import OntologyCompileError
from ontology_core.inference_compiler import HiveInferenceCompiler
from ontology_core.inference_models import (
    CandidateField,
    CandidateObject,
    CandidateTableFamily,
    CandidateTemporalPolicy,
    InferenceEvidence,
    ValidatedInferenceTemporalDecision,
    ValidatedInferredFilter,
    ValidatedInferredJoin,
    ValidatedInferredProgram,
)

XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"


def _field(object_ref: str, name: str, label: str) -> CandidateField:
    return CandidateField(
        ref=f"{object_ref}{name}",
        object_ref=object_ref,
        label=label,
        datatype_uri=XSD_STRING,
        physical_name=name.upper(),
    )


def _object(ref: str, physical_name: str | None = None) -> CandidateObject:
    return CandidateObject(
        ref=ref,
        label=ref,
        data_source_ref="Hive",
        physical_namespace="dm",
        physical_name=physical_name or f"{ref.upper()}_D",
        fields=(
            _field(ref, "CustomerId", "客户编号"),
            _field(ref, "Mobile", "手机号码"),
            _field(ref, "Status", "状态"),
            _field(ref, "PDay", "日分区"),
        ),
        temporal_policy=CandidateTemporalPolicy(
            ref=f"{ref}DayPolicy",
            partition_field_ref=f"{ref}PDay",
            grain="day",
            default_strategy="t_minus_2",
        ),
    )


def _field_from(object_: CandidateObject, suffix: str) -> CandidateField:
    return next(item for item in object_.fields if item.ref == f"{object_.ref}{suffix}")


def _decision(object_: CandidateObject) -> ValidatedInferenceTemporalDecision:
    return ValidatedInferenceTemporalDecision(
        object_ref=object_.ref,
        partition_field=_field_from(object_, "PDay"),
        grain="day",
        source="default",
        resolved_start="20260822",
        resolved_end="20260822",
        explanation="用户未指定日期，按本体策略取 T-2",
    )


def _plan(
    *objects: CandidateObject,
    requested_fields: tuple[CandidateField, ...] | None = None,
    joins: tuple[ValidatedInferredJoin, ...] = (),
    filters: tuple[ValidatedInferredFilter, ...] = (),
    families: tuple[CandidateTableFamily, ...] = (),
) -> ValidatedInferredProgram:
    return ValidatedInferredProgram(
        package_id="evaluation",
        package_version="1.0.0",
        package_sha256="a" * 64,
        data_source_ref="Hive",
        dialect="hive",
        objects=objects,
        families=families,
        requested_fields=requested_fields or (_field_from(objects[0], "Mobile"),),
        joins=joins,
        filters=filters,
        temporal_decisions=tuple(_decision(item) for item in objects),
        evidence=InferenceEvidence(
            overall_confidence="medium",
            reasons=("候选对象与字段元数据命中需求",),
            unresolved_items=("业务口径尚未确认",),
            ontology_suggestions=("补充业务口径规则",),
        ),
    )


def test_compiles_single_table_filter_and_bounded_partition() -> None:
    customer = _object("Customer")
    plan = _plan(
        customer,
        filters=(
            ValidatedInferredFilter(
                field=_field_from(customer, "Status"),
                operator="eq",
                values=("1",),
                confidence="low",
                evidence=("字段描述说明状态值 1",),
            ),
        ),
    )

    program = HiveInferenceCompiler().compile(plan, program_id="a1b2c3d4e5f6")

    assert len(program.statements) == 1
    assert 'FROM "dm"."CUSTOMER_D" AS "t0"' in program.sql
    assert '"t0"."STATUS" = \'1\'' in program.sql
    assert '"t0"."PDAY" = \'20260822\'' in program.sql
    assert program.sql.count("DROP TABLE IF EXISTS") == 1
    assert not program.sql.rstrip().endswith("DROP TABLE IF EXISTS")
    assert len(sqlglot.parse(program.sql, read="hive")) == 2
    assert program.evidence.inference == plan.evidence


def test_compiles_connected_candidate_join_without_cartesian_product() -> None:
    customer = _object("Customer")
    offer = _object("Offer")
    plan = _plan(
        customer,
        offer,
        joins=(
            ValidatedInferredJoin(
                left_object_ref="Customer",
                left_field=_field_from(customer, "CustomerId"),
                right_object_ref="Offer",
                right_field=_field_from(offer, "CustomerId"),
                confidence="medium",
                evidence=("字段均为客户编号",),
            ),
        ),
    )

    program = HiveInferenceCompiler().compile(plan, program_id="a1b2c3d4e5f6")

    assert 'INNER JOIN "dm"."OFFER_D" AS "t1"' in program.sql
    assert 'ON "t0"."CUSTOMERID" = "t1"."CUSTOMERID"' in program.sql
    assert program.evidence.source_tables == ("dm.CUSTOMER_D", "dm.OFFER_D")


def test_compiles_published_family_as_union_all_intermediate() -> None:
    hu = _object("GsmHu", "D_BBZX_DR_GSM_HU_D")
    hz = _object("GsmHz", "D_BBZX_DR_GSM_HZ_D")
    family = CandidateTableFamily(
        ref="family.gsm",
        label="GSM 地市日表",
        member_refs=("GsmHu", "GsmHz"),
        varying_token_index=4,
    )
    plan = _plan(hu, hz, families=(family,))

    program = HiveInferenceCompiler().compile(plan, program_id="a1b2c3d4e5f6")

    assert len(program.statements) == 2
    union_step, result_step = program.statements
    assert "UNION ALL" in union_step.create_sql
    assert 'FROM "dm"."D_BBZX_DR_GSM_HU_D"' in union_step.create_sql
    assert 'FROM "dm"."D_BBZX_DR_GSM_HZ_D"' in union_step.create_sql
    assert "NB" not in union_step.create_sql
    assert f'FROM "{union_step.target_table}" AS "t0"' in result_step.create_sql
    assert program.intermediate_tables == (union_step.target_table,)


def test_rejects_hostile_physical_identifier_even_when_plan_is_constructed_directly() -> None:
    customer = _object("Customer", "CUSTOMER_D; DROP TABLE source")

    with pytest.raises(OntologyCompileError, match="标识符"):
        HiveInferenceCompiler().compile(
            _plan(customer),
            program_id="a1b2c3d4e5f6",
        )


def test_rejects_unsupported_logical_filter_operator() -> None:
    customer = _object("Customer")
    plan = _plan(
        customer,
        filters=(
            ValidatedInferredFilter(
                field=_field_from(customer, "Status"),
                operator="all_of",
                values=("1",),
                confidence="low",
                evidence=("无效操作符测试",),
            ),
        ),
    )

    with pytest.raises(OntologyCompileError, match="操作符"):
        HiveInferenceCompiler().compile(plan, program_id="a1b2c3d4e5f6")

