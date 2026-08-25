from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ontology_core.errors import OntologyError
from ontology_core.management.editor import DraftEditor
from ontology_core.management.models import (
    DraftDataSource,
    DraftField,
    DraftObject,
    DraftRelation,
    DraftTemporalPolicy,
    WorkspaceDraft,
)
from ontology_core.management.store import FileDraftStore
from ontology_core.semantic_models import TemporalDefaultStrategy, TemporalGrain


def field(object_name: str, name: str, *, xsd_type: str = "string") -> DraftField:
    return DraftField(
        id=f"field/{object_name.casefold()}/{name.casefold()}",
        physical_name=name,
        label=name,
        description=f"{name} description",
        xsd_type=xsd_type,
    )


def object_(name: str, *fields: DraftField) -> DraftObject:
    return DraftObject(
        id=f"object/{name.casefold()}",
        physical_name=name,
        label=name,
        description=f"{name} description",
        fields=fields,
    )


def initialized_editor(
    tmp_path: Path,
    *,
    published_object_ids: frozenset[str] = frozenset(),
    published_field_ids: frozenset[str] = frozenset(),
):
    customer = object_("CUSTOMER", field("CUSTOMER", "CUSTOMER_ID", xsd_type="integer"))
    order = object_(
        "ORDER",
        field("ORDER", "ORDER_ID", xsd_type="integer"),
        field("ORDER", "CUSTOMER_ID", xsd_type="integer"),
        field("ORDER", "ORDER_DATE", xsd_type="date"),
    )
    draft = WorkspaceDraft(
        workspace_id="evaluation",
        display_name="Evaluation",
        package_id="package/evaluation",
        base_uri="https://example.test/ontology/evaluation#",
        revision=0,
        updated_at=datetime(2026, 8, 25, tzinfo=UTC),
        data_source=DraftDataSource(
            id="source/evaluation",
            label="Evaluation source",
            platform_type="generic_sql",
        ),
        objects=(customer, order),
    )
    store = FileDraftStore(tmp_path)
    store.create_workspace(draft)
    return (
        DraftEditor(
            store,
            published_object_ids=published_object_ids,
            published_field_ids=published_field_ids,
        ),
        store,
    )


def draft_bytes(tmp_path: Path) -> bytes:
    return (tmp_path / "workspaces" / "evaluation" / "draft.json").read_bytes()


def test_editing_descriptions_preserves_stable_identity_and_uses_one_revision(
    tmp_path: Path,
) -> None:
    editor, store = initialized_editor(tmp_path)
    before = store.read("evaluation").objects[0]

    updated = editor.update_object(
        "evaluation",
        before.id,
        expected_revision=0,
        label="客户",
        description="客户主数据",
    )

    after = updated.objects[0]
    assert after.id == before.id
    assert after.physical_name == before.physical_name
    assert after.label == "客户"
    assert updated.revision == 1

    revised = editor.update_field(
        "evaluation",
        after.id,
        after.fields[0].id,
        expected_revision=1,
        description="客户稳定主键",
    )

    assert revised.objects[0].fields[0].id == after.fields[0].id
    assert revised.objects[0].fields[0].physical_name == after.fields[0].physical_name
    assert revised.revision == 2


def test_relation_and_temporal_policy_require_owned_endpoints_in_one_mutation(
    tmp_path: Path,
) -> None:
    editor, store = initialized_editor(tmp_path)
    customer, order = store.read("evaluation").objects
    relation = DraftRelation(
        id="relation/order-customer",
        source_object_id=order.id,
        source_field_id="field/order/missing",
        target_object_id=customer.id,
        target_field_id=customer.fields[0].id,
        cardinality="many_to_one",
    )

    with pytest.raises(ValueError, match="关系源属性不属于对象"):
        editor.upsert_relation("evaluation", relation, expected_revision=0)
    assert store.read("evaluation").revision == 0

    policy = DraftTemporalPolicy(
        object_id=order.id,
        partition_field_id=customer.fields[0].id,
        grain=TemporalGrain.DAY,
        default_strategy=TemporalDefaultStrategy.T_MINUS_2,
    )
    with pytest.raises(ValueError, match="时间策略属性不属于对象"):
        editor.upsert_temporal_policy("evaluation", policy, expected_revision=0)
    assert store.read("evaluation").revision == 0

    valid_relation = relation.model_copy(update={"source_field_id": order.fields[1].id})
    updated = editor.upsert_relation("evaluation", valid_relation, expected_revision=0)
    assert updated.revision == 1
    assert updated.relations == (valid_relation,)
    assert not updated.relations[0].confirmed


def test_deletion_fails_closed_for_references_and_published_object_ids(tmp_path: Path) -> None:
    editor, store = initialized_editor(tmp_path)
    customer, order = store.read("evaluation").objects
    relation = DraftRelation(
        id="relation/order-customer",
        source_object_id=order.id,
        source_field_id=order.fields[1].id,
        target_object_id=customer.id,
        target_field_id=customer.fields[0].id,
        cardinality="many_to_one",
        confirmed=True,
    )
    editor.upsert_relation("evaluation", relation, expected_revision=0)

    with pytest.raises(ValueError, match="仍被引用"):
        editor.delete_draft_object("evaluation", customer.id, expected_revision=1)
    assert store.read("evaluation").revision == 1

    protected_editor, protected_store = initialized_editor(
        tmp_path / "published", published_object_ids=frozenset({customer.id})
    )
    with pytest.raises(ValueError, match="已发布"):
        protected_editor.delete_draft_object("evaluation", customer.id, expected_revision=0)
    assert protected_store.read("evaluation").revision == 0


def test_deleting_a_field_fails_closed_for_references_and_published_ids(tmp_path: Path) -> None:
    editor, store = initialized_editor(tmp_path)
    customer, order = store.read("evaluation").objects
    relation = DraftRelation(
        id="relation/order-customer",
        source_object_id=order.id,
        source_field_id=order.fields[1].id,
        target_object_id=customer.id,
        target_field_id=customer.fields[0].id,
        cardinality="many_to_one",
        confirmed=True,
    )
    editor.upsert_relation("evaluation", relation, expected_revision=0)
    before = draft_bytes(tmp_path)

    for object_id, field_id in (
        (relation.source_object_id, relation.source_field_id),
        (relation.target_object_id, relation.target_field_id),
    ):
        with pytest.raises(OntologyError) as exc_info:
            editor.delete_draft_field("evaluation", object_id, field_id, expected_revision=1)
        assert exc_info.value.code == "draft_edit_reference_conflict"
        assert draft_bytes(tmp_path) == before
        assert store.read("evaluation").revision == 1

    temporal_editor, temporal_store = initialized_editor(tmp_path / "temporal")
    temporal_order = temporal_store.read("evaluation").objects[1]
    policy = DraftTemporalPolicy(
        object_id=temporal_order.id,
        partition_field_id=temporal_order.fields[2].id,
        grain=TemporalGrain.DAY,
        default_strategy=TemporalDefaultStrategy.T_MINUS_2,
    )
    temporal_editor.upsert_temporal_policy("evaluation", policy, expected_revision=0)
    temporal_before = draft_bytes(tmp_path / "temporal")
    with pytest.raises(OntologyError) as exc_info:
        temporal_editor.delete_draft_field(
            "evaluation", temporal_order.id, policy.partition_field_id, expected_revision=1
        )
    assert exc_info.value.code == "draft_edit_reference_conflict"
    assert draft_bytes(tmp_path / "temporal") == temporal_before
    assert temporal_store.read("evaluation").revision == 1

    protected_editor, protected_store = initialized_editor(
        tmp_path / "published-field", published_field_ids=frozenset({order.fields[0].id})
    )
    protected_before = draft_bytes(tmp_path / "published-field")
    with pytest.raises(OntologyError) as exc_info:
        protected_editor.delete_draft_field(
            "evaluation", order.id, order.fields[0].id, expected_revision=0
        )
    assert exc_info.value.code == "draft_edit_published_identifier"
    assert draft_bytes(tmp_path / "published-field") == protected_before
    assert protected_store.read("evaluation").revision == 0


def test_deleting_an_unreferenced_unpublished_field_uses_one_revision(tmp_path: Path) -> None:
    editor, store = initialized_editor(tmp_path)
    order = store.read("evaluation").objects[1]
    unreferenced = next(field for field in order.fields if field.physical_name == "ORDER_ID")

    updated = editor.delete_draft_field(
        "evaluation", order.id, unreferenced.id, expected_revision=0
    )

    assert updated.revision == 1
    assert [field.id for field in updated.objects[1].fields] == [
        "field/order/customer_id",
        "field/order/order_date",
    ]


def test_resolving_diagnostic_requires_confirmation_and_complete_audit_disposition(
    tmp_path: Path,
) -> None:
    editor, store = initialized_editor(tmp_path)
    customer, order = store.read("evaluation").objects
    relation = DraftRelation(
        id="relation/order-customer",
        source_object_id=order.id,
        source_field_id=order.fields[1].id,
        target_object_id=customer.id,
        target_field_id=customer.fields[0].id,
        cardinality="many_to_one",
    )
    updated = editor.upsert_relation("evaluation", relation, expected_revision=0)
    diagnostic = next(
        item
        for item in editor.validator.validate(updated)
        if item.code == "relation_confirmation_required"
    )

    with pytest.raises(ValueError, match="处置说明"):
        editor.resolve_diagnostic(
            "evaluation",
            diagnostic.id,
            expected_revision=1,
            actor="maintainer",
            explanation="",
            resolved_at=datetime(2026, 8, 25, tzinfo=UTC),
        )

    resolved = editor.resolve_diagnostic(
        "evaluation",
        diagnostic.id,
        expected_revision=1,
        actor="maintainer",
        explanation="描述已由业务方确认留空",
        resolved_at=datetime(2026, 8, 25, tzinfo=UTC),
    )
    assert resolved.revision == 2
    assert resolved.dispositions[0].diagnostic_id == diagnostic.id


def test_resolving_error_or_warning_diagnostics_is_rejected_without_mutation(
    tmp_path: Path,
) -> None:
    editor, store = initialized_editor(tmp_path)
    customer = store.read("evaluation").objects[0]
    updated = editor.update_object("evaluation", customer.id, expected_revision=0, description="")
    warning = next(
        item for item in editor.validator.validate(updated) if item.code == "blank_description"
    )
    before = draft_bytes(tmp_path)

    with pytest.raises(OntologyError) as exc_info:
        editor.resolve_diagnostic(
            "evaluation",
            warning.id,
            expected_revision=1,
            actor="maintainer",
            explanation="cannot dismiss warnings",
            resolved_at=datetime(2026, 8, 25, tzinfo=UTC),
        )

    assert exc_info.value.code == "draft_diagnostic_disposition_invalid"
    assert draft_bytes(tmp_path) == before
    assert store.read("evaluation").revision == 1

    error_editor, error_store = initialized_editor(tmp_path / "error")
    error_customer, error_order = error_store.read("evaluation").objects
    incompatible = DraftRelation(
        id="relation/date-customer",
        source_object_id=error_order.id,
        source_field_id=next(
            field.id for field in error_order.fields if field.physical_name == "ORDER_DATE"
        ),
        target_object_id=error_customer.id,
        target_field_id=error_customer.fields[0].id,
        cardinality="many_to_one",
        confirmed=True,
    )
    error_draft = error_editor.upsert_relation("evaluation", incompatible, expected_revision=0)
    error = next(
        item
        for item in error_editor.validator.validate(error_draft)
        if item.code == "relation_incompatible_field_types"
    )
    error_before = draft_bytes(tmp_path / "error")

    with pytest.raises(OntologyError) as exc_info:
        error_editor.resolve_diagnostic(
            "evaluation",
            error.id,
            expected_revision=1,
            actor="maintainer",
            explanation="cannot dismiss errors",
            resolved_at=datetime(2026, 8, 25, tzinfo=UTC),
        )

    assert exc_info.value.code == "draft_diagnostic_disposition_invalid"
    assert draft_bytes(tmp_path / "error") == error_before
    assert error_store.read("evaluation").revision == 1


@pytest.mark.parametrize("value", (1, [], {}))
def test_descriptive_edits_reject_non_string_values_without_mutation(
    tmp_path: Path, value: object
) -> None:
    editor, store = initialized_editor(tmp_path)
    customer = store.read("evaluation").objects[0]
    before = draft_bytes(tmp_path)

    for edit in (
        lambda: editor.update_object("evaluation", customer.id, expected_revision=0, label=value),
        lambda: editor.update_field(
            "evaluation", customer.id, customer.fields[0].id, expected_revision=0, description=value
        ),
    ):
        with pytest.raises(OntologyError) as exc_info:
            edit()
        assert exc_info.value.code == "draft_edit_validation_error"
        assert draft_bytes(tmp_path) == before
        assert store.read("evaluation").revision == 0
