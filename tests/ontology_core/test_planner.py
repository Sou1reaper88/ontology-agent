from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ontology_core.errors import (
    AmbiguousQueryConceptError,
    NoMatchingConceptError,
    UnsupportedQueryPlanError,
)
from ontology_core.models import PackageInfo
from ontology_core.planner import OntologyPlanner
from ontology_core.repository import OntologySnapshot
from ontology_core.resolver import OntologyResolver
from ontology_core.semantic_models import (
    Concept,
    DataSource,
    LocalizedText,
    PhysicalMapping,
    Property,
    SemanticCatalog,
)


def _text(value: str) -> tuple[LocalizedText, ...]:
    return (LocalizedText(value=value, language="zh-CN"),)


def _resolver(
    *, duplicate: bool = False, missing_property_mapping: bool = False
) -> OntologyResolver:
    customer = Concept(
        uri="https://example.invalid/ontology/Customer",
        short_name="Customer",
        label="客户",
        labels=_text("客户"),
    )
    concepts = [customer]
    if duplicate:
        concepts.append(
            Concept(
                uri="https://example.invalid/ontology/CustomerDuplicate",
                short_name="CustomerDuplicate",
                label="客户",
                labels=_text("客户"),
            )
        )
    customer_id = Property(
        uri="https://example.invalid/ontology/CustomerId",
        short_name="CustomerId",
        label="客户编号",
        labels=_text("客户编号"),
        concept_uri=customer.uri,
        datatype_uri="http://www.w3.org/2001/XMLSchema#string",
    )
    status = Property(
        uri="https://example.invalid/ontology/Status",
        short_name="Status",
        label="客户状态",
        labels=_text("客户状态"),
        concept_uri=customer.uri,
        datatype_uri="http://www.w3.org/2001/XMLSchema#string",
    )
    source = DataSource(
        uri="https://example.invalid/ontology/Warehouse",
        short_name="Warehouse",
        label="分析仓库",
        labels=_text("分析仓库"),
        platform_type="generic",
        dialect="generic",
    )
    mappings = [
        PhysicalMapping(
            uri="https://example.invalid/ontology/CustomerTable",
            short_name="CustomerTable",
            label="客户对象映射",
            labels=_text("客户对象映射"),
            semantic_element_uri=customer.uri,
            data_source_uri=source.uri,
            physical_namespace="analytics",
            object_name="customer_snapshot",
            priority=10,
        ),
        PhysicalMapping(
            uri="https://example.invalid/ontology/StatusField",
            short_name="StatusField",
            label="状态字段映射",
            labels=_text("状态字段映射"),
            semantic_element_uri=status.uri,
            data_source_uri=source.uri,
            field_name="status_code",
            priority=10,
        ),
    ]
    if not missing_property_mapping:
        mappings.append(
            PhysicalMapping(
                uri="https://example.invalid/ontology/CustomerIdField",
                short_name="CustomerIdField",
                label="客户编号字段映射",
                labels=_text("客户编号字段映射"),
                semantic_element_uri=customer_id.uri,
                data_source_uri=source.uri,
                field_name="customer_id",
                priority=20,
            )
        )
    snapshot = OntologySnapshot(
        info=PackageInfo(
            package_id="example.planner",
            version="1.0.0",
            sha256="0" * 64,
            loaded_at=datetime.now(UTC),
            source="https://example.invalid/package",
        ),
        catalog=SemanticCatalog(
            concepts=tuple(concepts),
            properties=(customer_id, status),
            data_sources=(source,),
            mappings=tuple(mappings),
        ),
        _data_nt="",
        _shapes_nt="",
    )
    return OntologyResolver(snapshot)


def _property_inference_resolver(*, shared_label: bool = False) -> OntologyResolver:
    user = Concept(
        uri="https://example.invalid/ontology/UserEntity",
        short_name="UserEntity",
        label="用户实体",
        labels=_text("用户实体"),
    )
    order = Concept(
        uri="https://example.invalid/ontology/OrderEntity",
        short_name="OrderEntity",
        label="订单实体",
        labels=_text("订单实体"),
    )
    user_code = Property(
        uri="https://example.invalid/ontology/UserCode",
        short_name="UserCode",
        label="客户编码",
        labels=_text("客户编码"),
        concept_uri=user.uri,
        datatype_uri="http://www.w3.org/2001/XMLSchema#string",
    )
    user_status = Property(
        uri="https://example.invalid/ontology/UserStatus",
        short_name="UserStatus",
        label="状态编码" if shared_label else "用户状态",
        labels=_text("状态编码" if shared_label else "用户状态"),
        concept_uri=user.uri,
        datatype_uri="http://www.w3.org/2001/XMLSchema#string",
    )
    order_code = Property(
        uri="https://example.invalid/ontology/OrderCode",
        short_name="OrderCode",
        label="状态编码" if shared_label else "订单编码",
        labels=_text("状态编码" if shared_label else "订单编码"),
        concept_uri=order.uri,
        datatype_uri="http://www.w3.org/2001/XMLSchema#string",
    )
    source = DataSource(
        uri="https://example.invalid/ontology/Warehouse",
        short_name="Warehouse",
        label="合成仓库",
        labels=_text("合成仓库"),
        platform_type="generic",
        dialect="generic",
    )
    mappings = []
    for concept, object_name in ((user, "user_entity"), (order, "order_entity")):
        mappings.append(
            PhysicalMapping(
                uri=f"{concept.uri}Mapping",
                short_name=f"{concept.short_name}Mapping",
                label=f"{concept.label}映射",
                labels=_text(f"{concept.label}映射"),
                semantic_element_uri=concept.uri,
                data_source_uri=source.uri,
                physical_namespace="synthetic",
                object_name=object_name,
            )
        )
    for property_, field_name in (
        (user_code, "user_code"),
        (user_status, "user_status"),
        (order_code, "order_code"),
    ):
        mappings.append(
            PhysicalMapping(
                uri=f"{property_.uri}Mapping",
                short_name=f"{property_.short_name}Mapping",
                label=f"{property_.label}映射",
                labels=_text(f"{property_.label}映射"),
                semantic_element_uri=property_.uri,
                data_source_uri=source.uri,
                field_name=field_name,
            )
        )
    snapshot = OntologySnapshot(
        info=PackageInfo(
            package_id="example.property-inference",
            version="1.0.0",
            sha256="1" * 64,
            loaded_at=datetime.now(UTC),
            source="https://example.invalid/package",
        ),
        catalog=SemanticCatalog(
            concepts=(user, order),
            properties=(user_code, user_status, order_code),
            data_sources=(source,),
            mappings=tuple(mappings),
        ),
        _data_nt="",
        _shapes_nt="",
    )
    return OntologyResolver(snapshot)


def test_planner_builds_single_concept_plan_from_labels_and_mappings() -> None:
    plan = OntologyPlanner(_resolver()).plan("查询客户编号")

    assert plan.concept.short_name == "Customer"
    assert plan.data_source.short_name == "Warehouse"
    assert plan.object_binding.object_name == "customer_snapshot"
    assert tuple(item.semantic.short_name for item in plan.selections) == ("CustomerId",)
    assert plan.selections[0].binding.field_name == "customer_id"


def test_planner_rejects_no_match_ambiguity_and_missing_mapping() -> None:
    with pytest.raises(NoMatchingConceptError):
        OntologyPlanner(_resolver()).plan("查询完全无关对象")
    with pytest.raises(AmbiguousQueryConceptError):
        OntologyPlanner(_resolver(duplicate=True)).plan("查询客户")
    with pytest.raises(UnsupportedQueryPlanError):
        OntologyPlanner(_resolver(missing_property_mapping=True)).plan("查询客户编号")


def test_planner_infers_unique_concept_from_multiple_property_labels() -> None:
    plan = OntologyPlanner(_property_inference_resolver()).plan("查询客户编码和用户状态")

    assert plan.concept.short_name == "UserEntity"
    assert tuple(item.semantic.short_name for item in plan.selections) == (
        "UserCode",
        "UserStatus",
    )


def test_planner_rejects_property_inference_tie_between_concepts() -> None:
    with pytest.raises(AmbiguousQueryConceptError) as exc_info:
        OntologyPlanner(_property_inference_resolver(shared_label=True)).plan("查询状态编码")

    assert exc_info.value.details == {"candidates": ("OrderEntity", "UserEntity")}


def test_planner_rejects_direct_concept_match_without_known_property() -> None:
    with pytest.raises(UnsupportedQueryPlanError, match="未匹配到查询属性"):
        OntologyPlanner(_resolver()).plan("查询客户的火星指标")
