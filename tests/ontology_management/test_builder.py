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
    DiagnosticDisposition,
    DraftDataSource,
    DraftField,
    DraftObject,
    DraftRelation,
    DraftTemporalPolicy,
    WorkspaceDraft,
)
from ontology_core.management.validation import (
    DraftNotPublishableError,
    DraftValidator,
    stable_diagnostic_id,
)
from ontology_core.semantic_models import TemporalDefaultStrategy, TemporalGrain
from ontology_core.vocabulary import OA


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
    assert relation.uri.endswith("/relation/relation%2Fcustomer-orders")
    assert relation.source_concept_uri.endswith("/concept/object%2Fcustomer_m")
    assert relation.target_concept_uri.endswith("/concept/object%2Forder_d")
    assert relation.source_property_uri is not None
    assert relation.source_property_uri.endswith("/property/field%2Fcustomer_m%2Fcustomer_id")
    assert relation.target_property_uri is not None
    assert relation.target_property_uri.endswith("/property/field%2Forder_d%2Fcustomer_id")
    assert relation.cardinality == "one_to_many"
    assert relation.status == "active"
    assert relation.priority == 100
    assert relation.confirmed is True

    mappings_by_element = {
        mapping.semantic_element_uri: mapping for mapping in first.catalog.mappings
    }
    source_mapping = mappings_by_element[relation.source_property_uri]
    target_mapping = mappings_by_element[relation.target_property_uri]
    assert source_mapping.uri.endswith("/mapping/field%2Ffield%2Fcustomer_m%2Fcustomer_id")
    assert target_mapping.uri.endswith("/mapping/field%2Ffield%2Forder_d%2Fcustomer_id")
    assert source_mapping.field_name == "CUSTOMER_ID"
    assert target_mapping.field_name == "CUSTOMER_ID"
    assert source_mapping.data_source_uri == target_mapping.data_source_uri

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


@pytest.mark.parametrize("disposition_status", ("resolved", "dismissed"))
def test_builder_publishes_exact_relation_disposition_as_effective_confirmation(
    tmp_path: Path,
    disposition_status: str,
) -> None:
    draft = _workspace(relation_confirmed=False)
    validator = DraftValidator()
    confirmation = next(
        item for item in validator.validate(draft) if item.code == "relation_confirmation_required"
    )
    draft = draft.model_copy(
        update={
            "dispositions": (
                DiagnosticDisposition(
                    diagnostic_id=confirmation.id,
                    status=disposition_status,
                    note="Relation endpoints reviewed",
                    actor="reviewer",
                    resolved_at=datetime(2026, 8, 25, tzinfo=UTC),
                ),
            )
        }
    )
    target = tmp_path / disposition_status

    snapshot = PackageBuilder(validator).build(draft, target, "1.0.0")

    assert snapshot.catalog.relations[0].confirmed is True
    assert Literal(True) in set(snapshot.copy_data_graph().objects(None, OA.confirmed))


def test_builder_does_not_treat_unrelated_disposition_as_relation_confirmation(
    tmp_path: Path,
) -> None:
    draft = _workspace(relation_confirmed=False).model_copy(
        update={
            "dispositions": (
                DiagnosticDisposition(
                    diagnostic_id="diagnostic/unrelated",
                    status="resolved",
                    note="Different diagnostic",
                    actor="reviewer",
                    resolved_at=datetime(2026, 8, 25, tzinfo=UTC),
                ),
            )
        }
    )
    target = tmp_path / "unrelated"

    with pytest.raises(DraftNotPublishableError):
        PackageBuilder().build(draft, target, "1.0.0")

    assert not target.exists()


@pytest.mark.parametrize(
    "colliding_ids",
    (
        ("object/CaseCollision", "object/casecollision"),
        ("object/punctuation/a/b", "object/punctuation/a?b"),
    ),
)
def test_builder_blocks_normalized_short_name_collisions_before_target_write(
    tmp_path: Path,
    colliding_ids: tuple[str, str],
) -> None:
    draft = _workspace()
    colliding_objects = tuple(
        DraftObject(
            id=object_id,
            physical_name=f"COLLISION_{index}",
            label=f"Collision {index}",
            description="Synthetic collision",
        )
        for index, object_id in enumerate(colliding_ids)
    )
    draft = draft.model_copy(update={"objects": (*draft.objects, *colliding_objects)})
    validator = DraftValidator()

    collisions = [
        item for item in validator.validate(draft) if item.code == "duplicate_managed_short_name"
    ]

    assert len(collisions) == 1
    collision = collisions[0]
    assert collision.severity == "error"
    assert collision.related_ids == tuple(sorted(colliding_ids))
    assert collision.id == stable_diagnostic_id("duplicate_managed_short_name", colliding_ids)
    target = tmp_path / "collision"
    with pytest.raises(DraftNotPublishableError) as caught:
        PackageBuilder(validator).build(draft, target, "1.0.0")
    assert collision.id in {item.id for item in caught.value.diagnostics}
    assert not target.exists()


def test_builder_refuses_non_empty_target(tmp_path: Path) -> None:
    target = tmp_path / "occupied"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(OntologyParseError, match="不存在或为空"):
        PackageBuilder().build(_workspace(), target, "1.0.0")

    assert marker.read_text(encoding="utf-8") == "keep"
