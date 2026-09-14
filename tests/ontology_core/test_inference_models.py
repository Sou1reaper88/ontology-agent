from __future__ import annotations

import pytest
from pydantic import ValidationError

from ontology_core.inference_models import (
    CandidateContext,
    CandidateField,
    CandidateObject,
    CandidateTableFamily,
    CandidateTemporalPolicy,
    Confidence,
    InferenceEvidence,
    InferredFilterDraft,
    InferredJoinDraft,
    InferredProgramDraft,
    InferredAggregationDraft,
)


def _field(ref: str = "Customer.Mobile") -> CandidateField:
    return CandidateField(
        ref=ref,
        object_ref="Customer",
        label="手机号码",
        description="客户手机号码",
        datatype_uri="http://www.w3.org/2001/XMLSchema#string",
        physical_name="mobile_no",
        retrieval_score=90,
        matched_terms=("号码",),
    )


def _object() -> CandidateObject:
    return CandidateObject(
        ref="Customer",
        label="客户",
        description="客户主数据",
        data_source_ref="Hive",
        physical_namespace="dm",
        physical_name="customer_d",
        fields=(_field(),),
        temporal_policy=CandidateTemporalPolicy(
            ref="CustomerDayPolicy",
            partition_field_ref="Customer.PDay",
            grain="day",
            default_strategy="t_minus_2",
        ),
        retrieval_score=100,
        matched_terms=("客户",),
    )


def test_candidate_context_round_trip_preserves_stable_references() -> None:
    object_ = _object()
    family = CandidateTableFamily(
        ref="family.gsm.city.day",
        label="GSM 地市日表",
        member_refs=("GsmHu", "GsmHz"),
        varying_token_index=4,
    )
    context = CandidateContext(
        package_id="evaluation",
        package_version="1.0.0",
        package_sha256="a" * 64,
        objects=(object_,),
        families=(family,),
    )

    restored = CandidateContext.model_validate(context.model_dump(mode="json"))

    assert restored == context
    assert restored.objects[0].fields[0].ref == "Customer.Mobile"
    assert restored.families[0].member_refs == ("GsmHu", "GsmHz")


def test_inferred_program_round_trip_preserves_confidence_and_evidence() -> None:
    draft = InferredProgramDraft(
        selected_object_refs=("Customer", "Offer"),
        requested_field_refs=("Customer.Mobile",),
        joins=(
            InferredJoinDraft(
                left_object_ref="Customer",
                left_field_ref="Customer.Id",
                right_object_ref="Offer",
                right_field_ref="Offer.CustomerId",
                confidence=Confidence.MEDIUM,
                evidence=("字段中文名均表示客户编号",),
            ),
        ),
        filters=(
            InferredFilterDraft(
                field_ref="Offer.Status",
                operator="eq",
                values=("1",),
                confidence=Confidence.LOW,
                evidence=("需求明确要求有效状态 1",),
            ),
        ),
        unresolved_items=("请确认状态 1 是否代表有效",),
        ontology_suggestions=("补充客户与订购关系及关联键",),
    )

    restored = InferredProgramDraft.model_validate(draft.model_dump(mode="json"))

    assert restored == draft
    assert restored.joins[0].confidence is Confidence.MEDIUM


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("sql", "select * from dm.customer_d"),
        ("target_table", "user_result"),
        ("physical_table", "dm.customer_d"),
    ),
)
def test_llm_draft_rejects_sql_and_physical_identifier_fields(
    field_name: str,
    value: str,
) -> None:
    payload = {
        "selected_object_refs": ["Customer"],
        "requested_field_refs": ["Customer.Mobile"],
        field_name: value,
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        InferredProgramDraft.model_validate(payload)


@pytest.mark.parametrize("confidence", ("certain", "unknown", "0.8"))
def test_inference_rejects_unknown_confidence(confidence: str) -> None:
    with pytest.raises(ValidationError):
        InferredJoinDraft.model_validate(
            {
                "left_object_ref": "Customer",
                "left_field_ref": "Customer.Id",
                "right_object_ref": "Offer",
                "right_field_ref": "Offer.CustomerId",
                "confidence": confidence,
                "evidence": ["字段名称相同"],
            }
        )


def test_inference_requires_non_empty_evidence_for_hypotheses() -> None:
    with pytest.raises(ValidationError):
        InferredFilterDraft(
            field_ref="Customer.Status",
            operator="eq",
            values=("1",),
            confidence="low",
            evidence=(),
        )


@pytest.mark.parametrize(
    "payload",
    (
        {
            "selected_object_refs": ["Customer", "Customer"],
            "requested_field_refs": ["Customer.Mobile"],
        },
        {
            "selected_object_refs": ["Customer"],
            "requested_field_refs": ["Customer.Mobile", "Customer.Mobile"],
        },
        {
            "selected_object_refs": ["Customer"],
            "selected_family_refs": ["family.customer", "family.customer"],
            "requested_field_refs": ["Customer.Mobile"],
        },
    ),
)
def test_inferred_program_rejects_duplicate_references(payload: dict) -> None:
    with pytest.raises(ValidationError, match="引用必须唯一"):
        InferredProgramDraft.model_validate(payload)


def test_candidate_models_reject_llm_supplied_physical_metadata() -> None:
    payload = _object().model_dump(mode="json")
    payload["fields"][0]["sql_expression"] = "mobile_no; drop table customer_d"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CandidateObject.model_validate(payload)


def test_inference_evidence_requires_user_visible_basis() -> None:
    evidence = InferenceEvidence(
        overall_confidence="medium",
        reasons=("表描述与需求中的客户语义一致",),
        unresolved_items=("关联关系尚未写入本体",),
        ontology_suggestions=("新增客户到订购的一对多关系",),
    )

    assert evidence.overall_confidence is Confidence.MEDIUM
    with pytest.raises(ValidationError):
        InferenceEvidence(overall_confidence="low", reasons=())


def test_join_relation_source_defaults_to_model_and_accepts_user() -> None:
    payload = dict(
        left_object_ref="Customer",
        left_field_ref="Customer.Id",
        right_object_ref="Offer",
        right_field_ref="Offer.CustomerId",
        confidence="medium",
        evidence=("需求指定客户编号关联",),
    )
    assert InferredJoinDraft(**payload).relation_source == "model"
    assert InferredJoinDraft(**payload, relation_source="user").relation_source == "user"


def test_inferred_grouped_count_round_trips():
    draft = InferredProgramDraft(
        selected_object_refs=("Customer",),
        requested_field_refs=("Customer.Mobile",),
        group_by_field_refs=("Customer.Mobile",),
        aggregations=(
            InferredAggregationDraft(
                name="user_count",
                function="count",
                source_field_ref="Customer.Id",
                distinct=True,
            ),
        ),
    )
    assert InferredProgramDraft.model_validate_json(draft.model_dump_json()) == draft


@pytest.mark.parametrize(
    "payload",
    [
        dict(name="amount", function="sum"),
        dict(name="users", function="count", distinct=True),
    ],
)
def test_aggregation_requires_source_when_needed(payload):
    with pytest.raises(ValidationError, match="聚合"):
        InferredAggregationDraft(**payload)
