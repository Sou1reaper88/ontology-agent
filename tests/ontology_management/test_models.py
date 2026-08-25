from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ontology_core.management.models import (
    DiagnosticDisposition,
    DraftDataSource,
    DraftField,
    DraftObject,
    DraftRelation,
    DraftTemporalPolicy,
    ImportSession,
    UploadLimits,
    VersionSummary,
    WorkspaceDraft,
)
from ontology_core.semantic_models import TemporalDefaultStrategy, TemporalGrain


def synthetic_field(object_name: str, name: str) -> DraftField:
    return DraftField(
        id=f"field/{object_name.casefold()}/{name.casefold()}",
        physical_name=name,
        label=name,
        xsd_type="string",
    )


def synthetic_object(name: str, *, fields: tuple[DraftField, ...] | None = None) -> DraftObject:
    return DraftObject(
        id=f"object/{name.casefold()}",
        physical_name=name,
        label=name,
        fields=fields or (synthetic_field(name, "id"),),
    )


def synthetic_workspace(*, objects: tuple[DraftObject, ...] = ()) -> WorkspaceDraft:
    return WorkspaceDraft(
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
            physical_namespace="evaluation",
        ),
        objects=objects,
    )


def test_workspace_draft_serializes_objects_and_fields_deterministically() -> None:
    z_object = synthetic_object(
        "Z_TABLE",
        fields=(synthetic_field("Z_TABLE", "z_field"), synthetic_field("Z_TABLE", "a_field")),
    )
    draft = synthetic_workspace(objects=(z_object, synthetic_object("A_TABLE")))

    payload = draft.canonical_json()

    assert payload.index('"A_TABLE"') < payload.index('"Z_TABLE"')
    assert payload.index('"a_field"') < payload.index('"z_field"')
    assert WorkspaceDraft.model_validate_json(payload).revision == 0


def test_workspace_draft_rejects_negative_revision() -> None:
    with pytest.raises(ValidationError):
        WorkspaceDraft(
            **{**synthetic_workspace().model_dump(), "revision": -1},
        )


def test_relation_requires_distinct_existing_endpoint_ids_at_model_boundary() -> None:
    with pytest.raises(ValidationError):
        DraftRelation(
            id="relation/same",
            label="same",
            source_object_id="object/a",
            source_field_id="field/a/id",
            target_object_id="object/a",
            target_field_id="field/a/id",
            cardinality="many_to_one",
            confirmed=True,
        )


def test_workspace_draft_requires_unique_object_and_field_ids() -> None:
    duplicate = synthetic_object("A_TABLE")

    with pytest.raises(ValidationError):
        synthetic_workspace(objects=(duplicate, duplicate))

    with pytest.raises(ValidationError):
        synthetic_workspace(
            objects=(
                synthetic_object("A_TABLE"),
                synthetic_object(
                    "B_TABLE",
                    fields=(synthetic_field("A_TABLE", "id"),),
                ),
            )
        )


def test_workspace_draft_requires_relation_references_to_owned_existing_fields() -> None:
    source = synthetic_object("SOURCE")
    target = synthetic_object("TARGET")
    relation = DraftRelation(
        id="relation/source-target",
        label="source target",
        source_object_id=source.id,
        source_field_id=source.fields[0].id,
        target_object_id=target.id,
        target_field_id="field/missing/id",
        cardinality="many_to_one",
    )

    with pytest.raises(ValidationError):
        WorkspaceDraft(
            **{
                **synthetic_workspace(objects=(source, target)).model_dump(),
                "relations": (relation,),
            },
        )


@pytest.mark.parametrize(
    "statuses",
    (("active", "inactive"), ("inactive", "inactive")),
)
def test_workspace_draft_allows_at_most_one_temporal_policy_per_object(
    statuses: tuple[str, str],
) -> None:
    object_ = synthetic_object("ORDERS")
    policy = DraftTemporalPolicy(
        object_id=object_.id,
        partition_field_id=object_.fields[0].id,
        grain=TemporalGrain.DAY,
        default_strategy=TemporalDefaultStrategy.T_MINUS_2,
    )

    with pytest.raises(ValidationError):
        WorkspaceDraft(
            **{
                **synthetic_workspace(objects=(object_,)).model_dump(),
                "temporal_policies": tuple(
                    policy.model_copy(update={"status": status, "priority": 100 + index})
                    for index, status in enumerate(statuses)
                ),
            },
        )


def test_duplicate_temporal_policy_model_error_does_not_expose_object_id() -> None:
    object_ = synthetic_object("ORDERS").model_copy(
        update={"id": "object/fictional-secret-identifier"}
    )
    policy = DraftTemporalPolicy(
        object_id=object_.id,
        partition_field_id=object_.fields[0].id,
        grain=TemporalGrain.DAY,
        default_strategy=TemporalDefaultStrategy.T_MINUS_2,
        status="inactive",
    )

    with pytest.raises(ValidationError) as caught:
        WorkspaceDraft(
            **{
                **synthetic_workspace(objects=(object_,)).model_dump(),
                "temporal_policies": (policy, policy.model_copy(update={"priority": 200})),
            },
        )

    error = caught.value.errors(include_input=False)[0]
    assert "fictional-secret" not in error["msg"]


def test_temporal_policy_requires_matching_grain_and_default_strategy() -> None:
    with pytest.raises(ValidationError, match="时间分区粒度与默认策略不匹配"):
        DraftTemporalPolicy(
            object_id="object/orders",
            partition_field_id="field/orders/dt",
            grain=TemporalGrain.MONTH,
            default_strategy=TemporalDefaultStrategy.T_MINUS_2,
        )


def test_supporting_management_dtos_are_frozen_and_validate_bounds() -> None:
    disposition = DiagnosticDisposition(
        diagnostic_id="diagnostic/blank-description",
        status="resolved",
        note="Reviewed",
        actor="maintainer",
        resolved_at=datetime(2026, 8, 25, tzinfo=UTC),
    )
    session = ImportSession(
        token_hash="a" * 64,
        workspace_id="evaluation",
        expected_revision=0,
        content_digest="b" * 64,
        objects=(synthetic_object("ORDERS"),),
        diagnostics=(),
        created_at=datetime(2026, 8, 25, tzinfo=UTC),
        expires_at=datetime(2026, 8, 25, 0, 15, tzinfo=UTC),
    )
    version = VersionSummary(
        version="1.0.0",
        published_at=datetime(2026, 8, 25, tzinfo=UTC),
        actor="administrator",
        release_notes="Initial package",
    )

    assert disposition.status == "resolved"
    assert session.expected_revision == 0
    assert session.committed_revision is None
    assert version.version == "1.0.0"
    with pytest.raises(ValidationError):
        UploadLimits(max_upload_bytes=0, max_xlsx_uncompressed_bytes=1)
    with pytest.raises(ValidationError):
        session.workspace_id = "other"
