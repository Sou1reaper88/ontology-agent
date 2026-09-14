from __future__ import annotations

from datetime import UTC, datetime

from ontology_core.metadata_candidates import MetadataCandidateCatalog
from ontology_core.models import PackageInfo
from ontology_core.repository import OntologySnapshot
from ontology_core.semantic_models import (
    Concept,
    DataSource,
    PhysicalMapping,
    Property,
    SemanticCatalog,
    TemporalDefaultStrategy,
    TemporalGrain,
    TemporalPartitionPolicy,
)

XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"


def _concept(ref: str, label: str, description: str, physical: str) -> tuple:
    uri = f"https://example.invalid/concept/{ref}"
    mobile_uri = f"https://example.invalid/property/{ref}Mobile"
    day_uri = f"https://example.invalid/property/{ref}Day"
    source_uri = "https://example.invalid/source/Hive"
    concept = Concept(
        uri=uri,
        short_name=ref,
        label=label,
        labels=(),
        description=description,
    )
    fields = (
        Property(
            uri=mobile_uri,
            short_name=f"{ref}Mobile",
            label="手机号码",
            labels=(),
            description="用户的移动电话号码",
            concept_uri=uri,
            datatype_uri=XSD_STRING,
        ),
        Property(
            uri=day_uri,
            short_name=f"{ref}Day",
            label="日分区",
            labels=(),
            description="数据统计日期",
            concept_uri=uri,
            datatype_uri=XSD_STRING,
        ),
    )
    mappings = (
        PhysicalMapping(
            uri=f"https://example.invalid/mapping/{ref}",
            short_name=f"{ref}Mapping",
            label=f"{label}映射",
            labels=(),
            semantic_element_uri=uri,
            data_source_uri=source_uri,
            physical_namespace="bddwd_hive_db",
            object_name=physical,
        ),
        *(
            PhysicalMapping(
                uri=f"https://example.invalid/mapping/{field.short_name}",
                short_name=f"{field.short_name}Mapping",
                label=f"{field.label}映射",
                labels=(),
                semantic_element_uri=field.uri,
                data_source_uri=source_uri,
                field_name="MOBILE_NO" if field is fields[0] else "P_DAY",
            )
            for field in fields
        ),
    )
    temporal = TemporalPartitionPolicy(
        uri=f"https://example.invalid/policy/{ref}",
        short_name=f"{ref}DayPolicy",
        label=f"{label}日分区策略",
        labels=(),
        applies_to_uri=uri,
        partition_property_uri=day_uri,
        grain=TemporalGrain.DAY,
        default_strategy=TemporalDefaultStrategy.T_MINUS_2,
    )
    return concept, fields, mappings, temporal


def _snapshot() -> OntologySnapshot:
    source = DataSource(
        uri="https://example.invalid/source/Hive",
        short_name="Hive",
        label="数仓 Hive",
        labels=(),
        platform_type="hive",
        dialect="hive",
    )
    definitions = (
        _concept("GsmHz", "杭州 GSM 用户详单", "杭州 GSM 日级用户明细", "D_BBZX_DR_GSM_HZ_D"),
        _concept("GsmHu", "湖州 GSM 用户详单", "湖州 GSM 日级用户明细", "D_BBZX_DR_GSM_HU_D"),
        _concept("GsmLs", "丽水 GSM 用户详单", "丽水 GSM 日级用户明细", "D_BBZX_DR_GSM_LS_D"),
    )
    unmapped = Concept(
        uri="https://example.invalid/concept/Unmapped",
        short_name="Unmapped",
        label="未映射对象",
        labels=(),
    )
    return OntologySnapshot(
        info=PackageInfo(
            package_id="evaluation",
            version="1.0.0",
            sha256="a" * 64,
            loaded_at=datetime.now(UTC),
            source="fixture",
        ),
        catalog=SemanticCatalog(
            concepts=tuple(item[0] for item in reversed(definitions)) + (unmapped,),
            properties=tuple(field for item in definitions for field in item[1]),
            data_sources=(source,),
            mappings=tuple(mapping for item in definitions for mapping in item[2]),
            temporal_policies=tuple(item[3] for item in definitions),
        ),
        _data_nt="",
        _shapes_nt="",
    )


def test_explicit_tables_prioritize_without_excluding_related_tables() -> None:
    catalog = MetadataCandidateCatalog.from_snapshot(_snapshot())
    context = catalog.retrieve("D_BBZX_DR_GSM_HU_D 手机号码", object_limit=2)
    assert context.objects[0].ref == "GsmHu"
    assert len(context.objects) == 3
    assert len({obj.ref for obj in context.objects}) == 3


def test_explicit_tables_are_preserved_when_over_budget() -> None:
    catalog = MetadataCandidateCatalog.from_snapshot(_snapshot())
    context = catalog.retrieve(
        "D_BBZX_DR_GSM_HU_D D_BBZX_DR_GSM_HZ_D 手机号码", object_limit=1
    )
    assert {obj.ref for obj in context.objects} == {"GsmHu", "GsmHz", "GsmLs"}


def test_catalog_uses_only_published_mappings_and_metadata() -> None:
    catalog = MetadataCandidateCatalog.from_snapshot(_snapshot())
    context = catalog.retrieve("查询湖州用户的手机号码", object_limit=1)

    assert context.objects[0].ref == "GsmHu"
    assert context.objects[0].description == "湖州 GSM 日级用户明细"
    assert context.objects[0].physical_name == "D_BBZX_DR_GSM_HU_D"
    assert context.objects[0].fields[0].label == "手机号码"
    assert context.objects[0].fields[0].description == "用户的移动电话号码"
    assert "Unmapped" not in {item.ref for item in catalog.objects}


def test_retrieval_is_stable_and_ranks_relevant_fields_first() -> None:
    catalog = MetadataCandidateCatalog.from_snapshot(_snapshot())

    first = catalog.retrieve("湖州手机号码", object_limit=2, field_limit_per_object=1)
    second = catalog.retrieve("湖州手机号码", object_limit=2, field_limit_per_object=1)

    assert first == second
    assert first.objects[0].ref == "GsmHu"
    assert first.objects[0].fields[0].physical_name == "MOBILE_NO"
    assert {item.physical_name for item in first.objects[0].fields} == {
        "MOBILE_NO",
        "P_DAY",
    }
    assert first.objects[0].matched_terms
    assert first.objects[0].fields[0].matched_terms


def test_same_schema_city_tables_form_one_family() -> None:
    catalog = MetadataCandidateCatalog.from_snapshot(_snapshot())

    assert len(catalog.families) == 1
    family = catalog.families[0]
    assert family.member_refs == ("GsmHu", "GsmHz", "GsmLs")
    assert family.varying_token_index == 4
    assert all(item.family_ref == family.ref for item in catalog.objects)


def test_province_request_expands_all_published_family_members_without_invention() -> None:
    catalog = MetadataCandidateCatalog.from_snapshot(_snapshot())
    context = catalog.retrieve("查询全省 GSM 用户手机号码", object_limit=1)

    refs = {item.ref for item in context.objects}
    physical = {item.physical_name for item in context.objects}
    assert refs == {"GsmHu", "GsmHz", "GsmLs"}
    assert "D_BBZX_DR_GSM_NB_D" not in physical
    assert context.families[0].member_refs == ("GsmHu", "GsmHz", "GsmLs")


def test_specific_city_anchor_can_choose_one_object_with_complete_family_candidates() -> None:
    catalog = MetadataCandidateCatalog.from_snapshot(_snapshot())
    context = catalog.retrieve("查询湖州 GSM 用户", object_limit=1)

    assert next(item for item in context.objects if item.ref == "GsmHu").retrieval_score > 0
    assert context.families
    assert set(context.families[0].member_refs).issubset({item.ref for item in context.objects})


def test_irrelevant_request_returns_an_empty_candidate_context() -> None:
    catalog = MetadataCandidateCatalog.from_snapshot(_snapshot())

    context = catalog.retrieve("介绍量子力学的历史")

    assert context.objects == ()
    assert context.families == ()


def test_field_detail_budget_never_hides_full_field_index() -> None:
    catalog = MetadataCandidateCatalog.from_snapshot(_snapshot())
    context = catalog.retrieve("湖州", object_limit=1, field_limit_per_object=0)
    fields = {f.physical_name: f for f in context.objects[0].fields}
    assert set(fields) == {"MOBILE_NO", "P_DAY"}
    assert fields["MOBILE_NO"].description is None
    assert fields["P_DAY"].description is not None


def test_explicit_field_keeps_details_even_when_budget_is_zero() -> None:
    catalog = MetadataCandidateCatalog.from_snapshot(_snapshot())
    context = catalog.retrieve(
        "D_BBZX_DR_GSM_HU_D 的 MOBILE_NO", object_limit=1, field_limit_per_object=0
    )
    assert context.objects[0].ref == "GsmHu"
    field = next(f for f in context.objects[0].fields if f.physical_name == "MOBILE_NO")
    assert field.description == "用户的移动电话号码"


def test_explicit_chinese_field_label_keeps_details() -> None:
    catalog = MetadataCandidateCatalog.from_snapshot(_snapshot())
    context = catalog.retrieve("查询湖州手机号码", object_limit=1, field_limit_per_object=0)
    assert next(f for f in context.objects[0].fields
                if f.physical_name == "MOBILE_NO").description is not None
