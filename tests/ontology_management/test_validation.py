from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ontology_core.management.models import (
    DiagnosticDisposition,
    DraftDataSource,
    DraftField,
    DraftObject,
    DraftRelation,
    WorkspaceDraft,
)
from ontology_core.management.validation import DraftNotPublishableError, DraftValidator


def workspace(
    *,
    relation: DraftRelation | None = None,
    description: str = "described",
    source_xsd_type: str = "string",
) -> WorkspaceDraft:
    customer_field = DraftField(
        id="field/customer/id",
        physical_name="CUSTOMER_ID",
        description=description,
        xsd_type="integer",
    )
    order_field = DraftField(
        id="field/order/customer_id",
        physical_name="CUSTOMER_ID",
        description="customer",
        xsd_type=source_xsd_type,
    )
    alternate_order_field = DraftField(
        id="field/order/alternate_customer_id",
        physical_name="ALTERNATE_CUSTOMER_ID",
        description="alternate customer",
        xsd_type=source_xsd_type,
    )
    customer = DraftObject(
        id="object/customer",
        physical_name="CUSTOMER",
        description=description,
        fields=(customer_field,),
    )
    order = DraftObject(
        id="object/order",
        physical_name="ORDER",
        description="orders",
        fields=(order_field, alternate_order_field),
    )
    return WorkspaceDraft(
        workspace_id="evaluation",
        display_name="Evaluation",
        package_id="package/evaluation",
        base_uri="https://example.test/ontology/evaluation#",
        revision=0,
        updated_at=datetime(2026, 8, 25, tzinfo=UTC),
        data_source=DraftDataSource(
            id="source/evaluation", label="source", platform_type="generic_sql"
        ),
        objects=(customer, order),
        relations=() if relation is None else (relation,),
    )


def test_active_relation_requires_confirmation_and_type_compatibility() -> None:
    draft = workspace(
        relation=DraftRelation(
            id="relation/order-customer",
            source_object_id="object/order",
            source_field_id="field/order/customer_id",
            target_object_id="object/customer",
            target_field_id="field/customer/id",
            cardinality="many_to_one",
        )
    )

    diagnostics = DraftValidator().validate(draft)

    assert {(item.code, item.severity) for item in diagnostics} >= {
        ("relation_confirmation_required", "confirmation_required"),
        ("relation_incompatible_field_types", "error"),
    }
    with pytest.raises(DraftNotPublishableError) as exc_info:
        DraftValidator().assert_publishable(draft)
    assert {item.code for item in exc_info.value.diagnostics} == {
        "relation_confirmation_required",
        "relation_incompatible_field_types",
    }


def test_disposition_unblocks_only_the_same_stable_confirmation_diagnostic() -> None:
    relation = DraftRelation(
        id="relation/order-customer",
        source_object_id="object/order",
        source_field_id="field/order/customer_id",
        target_object_id="object/customer",
        target_field_id="field/customer/id",
        cardinality="many_to_one",
    )
    draft = workspace(relation=relation, source_xsd_type="integer")
    validator = DraftValidator()
    confirmation = next(
        item for item in validator.validate(draft) if item.code == "relation_confirmation_required"
    )
    resolved = draft.model_copy(
        update={
            "dispositions": (
                DiagnosticDisposition(
                    diagnostic_id=confirmation.id,
                    status="resolved",
                    note="reviewed by maintainer",
                    actor="maintainer",
                    resolved_at=datetime(2026, 8, 25, tzinfo=UTC),
                ),
            )
        }
    )

    blocking = validator.assert_publishable(resolved)

    assert "relation_confirmation_required" in {item.code for item in blocking}

    changed_relation = relation.model_copy(
        update={"source_field_id": "field/order/alternate_customer_id"}
    )
    changed = draft.model_copy(update={"relations": (changed_relation,)})
    changed_confirmation = next(
        item
        for item in validator.validate(changed)
        if item.code == "relation_confirmation_required"
    )
    assert changed_confirmation.id != confirmation.id


def test_error_diagnostics_remain_publish_blocking_despite_a_disposition() -> None:
    relation = DraftRelation(
        id="relation/order-customer",
        source_object_id="object/order",
        source_field_id="field/order/customer_id",
        target_object_id="object/customer",
        target_field_id="field/customer/id",
        cardinality="many_to_one",
    )
    draft = workspace(relation=relation)
    validator = DraftValidator()
    error = next(
        item
        for item in validator.validate(draft)
        if item.code == "relation_incompatible_field_types"
    )
    disposed = draft.model_copy(
        update={
            "dispositions": (
                DiagnosticDisposition(
                    diagnostic_id=error.id,
                    status="dismissed",
                    note="attempted dismissal",
                    actor="maintainer",
                    resolved_at=datetime(2026, 8, 25, tzinfo=UTC),
                ),
            )
        }
    )

    with pytest.raises(DraftNotPublishableError) as exc_info:
        validator.assert_publishable(disposed)

    assert error.id in {item.id for item in exc_info.value.diagnostics}


def test_diagnostic_ids_ignore_mutable_messages_and_report_description_warnings() -> None:
    validator = DraftValidator()
    first = workspace(description="")
    second = workspace(description=" ")

    first_diagnostic = next(
        item for item in validator.validate(first) if item.code == "blank_description"
    )
    second_diagnostic = next(
        item for item in validator.validate(second) if item.code == "blank_description"
    )

    assert first_diagnostic.id == second_diagnostic.id
    assert first_diagnostic.related_ids == ("object/customer",)
    assert first_diagnostic.severity == "warning"
