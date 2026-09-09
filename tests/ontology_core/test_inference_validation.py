from __future__ import annotations

from datetime import UTC, datetime

from ontology_core.inference_models import (
    CandidateContext,
    CandidateField,
    CandidateObject,
    CandidateTableFamily,
    CandidateTemporalPolicy,
    InferredFilterDraft,
    InferredJoinDraft,
    InferredProgramDraft,
)
from ontology_core.inference_validation import MetadataInferenceValidator
from ontology_core.models import PackageInfo
from ontology_core.repository import OntologySnapshot
from ontology_core.semantic_models import DataSource, SemanticCatalog

XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"
XSD_INTEGER = "http://www.w3.org/2001/XMLSchema#integer"
SOURCE = "https://example.invalid/source/Hive"


def _field(
    object_ref: str,
    name: str,
    label: str,
    *,
    datatype: str = XSD_STRING,
    description: str | None = None,
) -> CandidateField:
    return CandidateField(
        ref=f"{object_ref}{name}",
        object_ref=object_ref,
        label=label,
        description=description,
        datatype_uri=datatype,
        physical_name=name.upper(),
    )


def _object(
    ref: str,
    *,
    source: str = SOURCE,
    customer_type: str = XSD_STRING,
) -> CandidateObject:
    fields = (
        _field(ref, "CustomerId", "客户编号", datatype=customer_type),
        _field(ref, "Mobile", "手机号码"),
        _field(ref, "Status", "用户状态", description="状态值 1 表示有效"),
        _field(ref, "PDay", "日分区"),
    )
    return CandidateObject(
        ref=ref,
        label=f"{ref}业务对象",
        description=f"{ref}客户业务数据",
        data_source_ref=source,
        physical_namespace="dm",
        physical_name=f"{ref.upper()}_D",
        fields=fields,
        temporal_policy=CandidateTemporalPolicy(
            ref=f"{ref}DayPolicy",
            partition_field_ref=f"{ref}PDay",
            grain="day",
            default_strategy="t_minus_2",
        ),
    )


def _snapshot(*sources: str) -> OntologySnapshot:
    data_sources = tuple(
        DataSource(
            uri=source,
            short_name=f"Hive{index}",
            label=f"Hive {index}",
            labels=(),
            platform_type="hive",
            dialect="hive",
        )
        for index, source in enumerate(sources or (SOURCE,), start=1)
    )
    return OntologySnapshot(
        info=PackageInfo(
            package_id="evaluation",
            version="1.0.0",
            sha256="a" * 64,
            loaded_at=datetime.now(UTC),
            source="fixture",
        ),
        catalog=SemanticCatalog(data_sources=data_sources),
        _data_nt="",
        _shapes_nt="",
    )


class _Catalog:
    def __init__(self, snapshot: OntologySnapshot) -> None:
        self.snapshot = snapshot


def _validate(
    draft: InferredProgramDraft,
    *objects: CandidateObject,
    families: tuple[CandidateTableFamily, ...] = (),
    request: str = "查询客户手机号码",
    snapshot: OntologySnapshot | None = None,
):
    snap = snapshot or _snapshot()
    context = CandidateContext(
        package_id=snap.info.package_id,
        package_version=snap.info.version,
        package_sha256=snap.info.sha256,
        objects=objects,
        families=families,
    )
    return MetadataInferenceValidator().validate(
        draft,
        candidates=context,
        catalog=_Catalog(snap),  # type: ignore[arg-type]
        system_time=datetime(2026, 8, 24),
        request=request,
    )


def test_single_table_plan_uses_published_t_minus_2_policy() -> None:
    customer = _object("Customer")
    result = _validate(
        InferredProgramDraft(
            selected_object_refs=("Customer",),
            requested_field_refs=("CustomerMobile",),
        ),
        customer,
    )

    assert result.plan is not None
    decision = result.plan.temporal_decisions[0]
    assert decision.partition_field.physical_name == "PDAY"
    assert decision.resolved_start == "20260822"
    assert decision.resolved_end == "20260822"
    assert decision.source == "default"


def test_candidate_time_expression_resolves_each_partition_grain() -> None:
    customer = _object("Customer")
    result = _validate(
        InferredProgramDraft(
            selected_object_refs=("Customer",),
            requested_field_refs=("CustomerMobile",),
            time_expression="2026年6月",
        ),
        customer,
        request="查询2026年6月数据，账期202606，开始日2026-06-01，结束日2026-06-30",
    )

    assert result.plan is not None
    decision = result.plan.temporal_decisions[0]
    assert (decision.resolved_start, decision.resolved_end) == ("20260601", "20260630")


def test_unknown_object_or_field_reference_is_rejected() -> None:
    result = _validate(
        InferredProgramDraft(
            selected_object_refs=("Unknown",),
            requested_field_refs=("UnknownMobile",),
        ),
        _object("Customer"),
    )

    assert result.plan is None
    assert result.diagnostics[0].code == "unknown_object_ref"
    assert result.missing_information


def test_multiple_sources_require_a_connected_join_graph() -> None:
    result = _validate(
        InferredProgramDraft(
            selected_object_refs=("Customer", "Offer"),
            requested_field_refs=("CustomerMobile",),
        ),
        _object("Customer"),
        _object("Offer"),
    )

    assert result.plan is None
    assert result.diagnostics[0].code == "missing_candidate_join"


def test_metadata_supported_join_passes_but_high_confidence_is_capped() -> None:
    customer = _object("Customer")
    offer = _object("Offer")
    result = _validate(
        InferredProgramDraft(
            selected_object_refs=("Customer", "Offer"),
            requested_field_refs=("CustomerMobile",),
            joins=(
                InferredJoinDraft(
                    left_object_ref="Customer",
                    left_field_ref="CustomerCustomerId",
                    right_object_ref="Offer",
                    right_field_ref="OfferCustomerId",
                    confidence="high",
                    evidence=("两个字段都表示客户编号",),
                ),
            ),
        ),
        customer,
        offer,
    )

    assert result.plan is not None
    assert result.plan.joins[0].confidence == "medium"
    assert "补充" in result.plan.evidence.ontology_suggestions[0]


def test_incompatible_join_types_are_rejected() -> None:
    result = _validate(
        InferredProgramDraft(
            selected_object_refs=("Customer", "Offer"),
            requested_field_refs=("CustomerMobile",),
            joins=(
                InferredJoinDraft(
                    left_object_ref="Customer",
                    left_field_ref="CustomerCustomerId",
                    right_object_ref="Offer",
                    right_field_ref="OfferCustomerId",
                    confidence="medium",
                    evidence=("字段名称相同",),
                ),
            ),
        ),
        _object("Customer", customer_type=XSD_STRING),
        _object("Offer", customer_type=XSD_INTEGER),
    )

    assert result.plan is None
    assert result.diagnostics[0].code == "incompatible_join_types"


def test_filter_value_must_come_from_request_or_field_metadata() -> None:
    customer = _object("Customer")
    accepted = _validate(
        InferredProgramDraft(
            selected_object_refs=("Customer",),
            requested_field_refs=("CustomerMobile",),
            filters=(
                InferredFilterDraft(
                    field_ref="CustomerStatus",
                    operator="eq",
                    values=("1",),
                    confidence="low",
                    evidence=("字段描述说明 1 表示有效",),
                ),
            ),
        ),
        customer,
        request="查询有效客户手机号码",
    )
    rejected = _validate(
        InferredProgramDraft(
            selected_object_refs=("Customer",),
            requested_field_refs=("CustomerMobile",),
            filters=(
                InferredFilterDraft(
                    field_ref="CustomerStatus",
                    operator="eq",
                    values=("9",),
                    confidence="low",
                    evidence=("模型认为 9 可能有效",),
                ),
            ),
        ),
        customer,
        request="查询有效客户手机号码",
    )

    assert accepted.plan is not None
    assert rejected.plan is None
    assert rejected.diagnostics[0].code == "unsupported_filter_value"


def test_cross_source_plan_and_conflicting_time_are_rejected() -> None:
    other_source = "https://example.invalid/source/OtherHive"
    cross_source = _validate(
        InferredProgramDraft(
            selected_object_refs=("Customer", "Offer"),
            requested_field_refs=("CustomerMobile",),
        ),
        _object("Customer"),
        _object("Offer", source=other_source),
        snapshot=_snapshot(SOURCE, other_source),
    )
    conflicting_time = _validate(
        InferredProgramDraft(
            selected_object_refs=("Customer",),
            requested_field_refs=("CustomerMobile",),
        ),
        _object("Customer"),
        request="查询 2026-08-20 和 2026-08-21 的客户",
    )

    assert cross_source.plan is None
    assert cross_source.diagnostics[0].code == "cross_source_candidate"
    assert conflicting_time.plan is None
    assert conflicting_time.diagnostics[0].code == "unsafe_candidate_time"


def test_family_is_one_logical_source_and_expands_only_declared_members() -> None:
    hu = _object("GsmHu")
    hz = _object("GsmHz")
    family = CandidateTableFamily(
        ref="family.gsm",
        label="GSM 地市日表",
        member_refs=("GsmHu", "GsmHz"),
        varying_token_index=4,
    )
    result = _validate(
        InferredProgramDraft(
            selected_object_refs=("GsmHu",),
            selected_family_refs=("family.gsm",),
            requested_field_refs=("GsmHuMobile",),
        ),
        hu,
        hz,
        families=(family,),
        request="查询全省 GSM 手机号码",
    )

    assert result.plan is not None
    assert {item.ref for item in result.plan.objects} == {"GsmHu", "GsmHz"}
    assert result.plan.families == (family,)
    assert result.plan.joins == ()

