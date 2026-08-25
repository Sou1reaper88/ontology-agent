from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from rdflib import Literal
from rdflib.compare import to_isomorphic
from rdflib.namespace import RDFS

from ontology_core.errors import OntologyParseError
from ontology_core.management.builder import PackageBuilder
from ontology_core.management.models import (
    DraftDataSource,
    DraftField,
    DraftObject,
    DraftRelation,
    DraftTemporalPolicy,
    WorkspaceDraft,
)
from ontology_core.management.validation import DraftNotPublishableError
from ontology_core.semantic_models import TemporalDefaultStrategy, TemporalGrain


def _workspace(*, relation_confirmed: bool = True) -> WorkspaceDraft:
    malicious_label = '客户" ; oa:password "never-serialize'
    customer = DraftObject(
        id="object/customer_m",
        physical_name="CUSTOMER_M",
        label=malicious_label,
        description="Synthetic customers",
        fields=(
            DraftField(
                id="field/customer_m/customer_id",
                physical_name="CUSTOMER_ID",
                label="客户编码",
                description="Synthetic customer key",
                xsd_type="string",
                primary_key=True,
            ),
            DraftField(
                id="field/customer_m/p_mon",
                physical_name="P_MON",
                label="客户账期",
                description="Synthetic month partition",
                xsd_type="string",
            ),
        ),
    )
    order = DraftObject(
        id="object/order_d",
        physical_name="ORDER_D",
        label="订单日表",
        description="Synthetic orders",
        fields=(
            DraftField(
                id="field/order_d/customer_id",
                physical_name="CUSTOMER_ID",
                label="订单客户编码",
                description="Synthetic relation key",
                xsd_type="string",
            ),
            DraftField(
                id="field/order_d/p_day",
                physical_name="P_DAY",
                label="订单日期",
                description="Synthetic day partition",
                xsd_type="date",
            ),
        ),
    )
    product = DraftObject(
        id="object/product",
        physical_name="PRODUCT",
        label="商品",
        description="Synthetic products",
        fields=(
            DraftField(
                id="field/product/product_id",
                physical_name="PRODUCT_ID",
                label="商品编码",
                description="Synthetic product key",
                xsd_type="integer",
                primary_key=True,
            ),
        ),
    )
    return WorkspaceDraft(
        workspace_id="synthetic-workspace",
        display_name="Synthetic workspace",
        package_id="tests.multi-object",
        base_uri="https://example.invalid/tests/multi-object/",
        revision=7,
        updated_at=datetime(2026, 8, 25, tzinfo=UTC),
        data_source=DraftDataSource(
            id="source/synthetic",
            label="Synthetic source",
            platform_type="generic_sql",
            dialect="generic",
            physical_namespace="analytics",
        ),
        objects=(product, order, customer),
        relations=(
            DraftRelation(
                id="relation/customer-orders",
                label="客户订单",
                source_object_id=customer.id,
                source_field_id=customer.fields[0].id,
                target_object_id=order.id,
                target_field_id=order.fields[0].id,
                cardinality="one_to_many",
                priority=100,
                confirmed=relation_confirmed,
            ),
        ),
        temporal_policies=(
            DraftTemporalPolicy(
                object_id=order.id,
                partition_field_id=order.fields[1].id,
                grain=TemporalGrain.DAY,
                default_strategy=TemporalDefaultStrategy.T_MINUS_2,
            ),
            DraftTemporalPolicy(
                object_id=customer.id,
                partition_field_id=customer.fields[1].id,
                grain=TemporalGrain.MONTH,
                default_strategy=TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH,
            ),
        ),
    )


def test_builder_generates_deterministic_multi_object_six_file_package(
    tmp_path: Path,
) -> None:
    first_target = tmp_path / "first"
    second_target = tmp_path / "second"

    builder = PackageBuilder()
    first = builder.build(_workspace(), first_target, "1.2.3")
    second = builder.build(_workspace(), second_target, "1.2.3")

    expected_files = {
        "manifest.yaml",
        "core.ttl",
        "domain.ttl",
        "mappings.ttl",
        "rules.ttl",
        "shapes.ttl",
    }
    assert {item.name for item in first_target.iterdir()} == expected_files
    assert {item.name for item in second_target.iterdir()} == expected_files
    assert to_isomorphic(first.copy_data_graph()) == to_isomorphic(second.copy_data_graph())
    assert len(first.catalog.concepts) == 3
    assert len(first.catalog.properties) == 5
    assert len(first.catalog.data_sources) == 1
    assert len(first.catalog.mappings) == 8
    assert len(first.catalog.relations) == 1
    assert len(first.catalog.temporal_policies) == 2
    relation = first.catalog.relations[0]
    assert relation.cardinality == "one_to_many"
    assert relation.priority == 100
    assert relation.confirmed is True

    graph = first.copy_data_graph()
    assert Literal('客户" ; oa:password "never-serialize', lang="zh-CN") in set(
        graph.objects(None, RDFS.label)
    )
    credential_names = {"host", "port", "username", "password", "token", "secret"}
    assert not any(
        str(predicate).rsplit("#", 1)[-1].casefold() in credential_names
        for predicate in graph.predicates()
    )


def test_builder_validates_before_creating_target(tmp_path: Path) -> None:
    target = tmp_path / "blocked"

    with pytest.raises(DraftNotPublishableError):
        PackageBuilder().build(_workspace(relation_confirmed=False), target, "1.0.0")

    assert not target.exists()


def test_builder_refuses_non_empty_target(tmp_path: Path) -> None:
    target = tmp_path / "occupied"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(OntologyParseError, match="不存在或为空"):
        PackageBuilder().build(_workspace(), target, "1.0.0")

    assert marker.read_text(encoding="utf-8") == "keep"
