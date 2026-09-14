from __future__ import annotations

from dataclasses import replace

import pytest
from pydantic import ValidationError

from ontology_core.inference_models import CandidateContext, Confidence, InferredJoinDraft
from ontology_core.metadata_candidates import MetadataCandidateCatalog
from ontology_core.relation_evidence import (
    RelationEvidenceGraph,
    RelationEvidenceSource,
    build_relation_evidence_graph,
)
from ontology_core.semantic_models import Relation
from tests.ontology_core.test_metadata_candidates import _snapshot


def _catalog(*, confirmed: bool | None = None, status: str = "active"):
    snapshot = _snapshot()
    if confirmed is not None:
        relation = Relation(
            uri="https://example.invalid/relation/users",
            short_name="UserLink",
            label="用户号码关联",
            labels=(),
            source_concept_uri="https://example.invalid/concept/GsmHu",
            target_concept_uri="https://example.invalid/concept/GsmHz",
            source_property_uri="https://example.invalid/property/GsmHuMobile",
            target_property_uri="https://example.invalid/property/GsmHzMobile",
            confirmed=confirmed,
            status=status,
        )
        snapshot = replace(
            snapshot, catalog=snapshot.catalog.model_copy(update={"relations": (relation,)})
        )
    catalog = MetadataCandidateCatalog.from_snapshot(snapshot)
    candidates = CandidateContext(
        package_id=snapshot.info.package_id,
        package_version=snapshot.info.version,
        package_sha256=snapshot.info.sha256,
        objects=tuple(obj for obj in catalog.objects if obj.ref in {"GsmHu", "GsmHz"}),
    )
    return candidates, catalog


def _join(**changes):
    payload = dict(
        left_object_ref="GsmHu",
        left_field_ref="GsmHuMobile",
        right_object_ref="GsmHz",
        right_field_ref="GsmHzMobile",
        confidence="high",
        evidence=("字段描述均表示移动电话号码",),
    )
    payload.update(changes)
    return InferredJoinDraft(**payload)


def test_graph_contains_confirmed_ontology_relation():
    graph = build_relation_evidence_graph(*_catalog(confirmed=True))
    assert len(graph.edges) == 1
    assert graph.edges[0].source is RelationEvidenceSource.ONTOLOGY
    assert graph.edges[0].confidence is Confidence.HIGH
    assert graph.edges[0].evidence == ("用户号码关联",)
    assert RelationEvidenceGraph.model_validate(graph.model_dump(mode="json")) == graph


@pytest.mark.parametrize(
    "confirmed,status", [(None, "active"), (False, "active"), (True, "inactive")]
)
def test_initial_graph_may_be_empty(confirmed, status):
    graph = build_relation_evidence_graph(*_catalog(confirmed=confirmed, status=status))
    assert graph.edges == ()


def test_model_can_propose_relation_without_any_ontology_relation():
    graph = build_relation_evidence_graph(*_catalog(), proposed_joins=(_join(), _join()))
    assert len(graph.edges) == 1
    assert graph.edges[0].source is RelationEvidenceSource.MODEL
    assert graph.edges[0].confidence is Confidence.MEDIUM
    assert graph.matching("GsmHzMobile", "GsmHuMobile") == graph.edges[0]


def test_user_relation_preserves_direction_and_does_not_claim_ontology_confirmation():
    graph = build_relation_evidence_graph(
        *_catalog(), proposed_joins=(_join(relation_source="user", join_type="left"),)
    )
    edge = graph.edges[0]
    assert edge.source is RelationEvidenceSource.USER
    assert edge.join_type == "left"
    assert edge.left_object_ref == "GsmHu"
    assert edge.confidence is Confidence.MEDIUM


def test_confirmed_evidence_is_preferred_over_model_duplicate():
    graph = build_relation_evidence_graph(*_catalog(confirmed=True), proposed_joins=(_join(),))
    assert len(graph.edges) == 1
    assert graph.edges[0].source is RelationEvidenceSource.ONTOLOGY


@pytest.mark.parametrize(
    "changes",
    [
        {"right_field_ref": "Missing"},
        {"left_field_ref": "GsmHzMobile"},
        {"right_object_ref": "Missing"},
        {"right_field_ref": "GsmHuMobile", "right_object_ref": "GsmHu"},
    ],
)
def test_graph_rejects_unknown_misowned_or_self_relation(changes):
    with pytest.raises(ValueError, match="关联字段"):
        build_relation_evidence_graph(*_catalog(), proposed_joins=(_join(**changes),))


def test_graph_rejects_incompatible_types_and_cross_source():
    candidates, catalog = _catalog()
    right = candidates.objects[1]
    numeric = right.model_copy(
        update={
            "fields": tuple(
                field.model_copy(
                    update={"datatype_uri": "http://www.w3.org/2001/XMLSchema#integer"}
                )
                if field.ref == "GsmHzMobile"
                else field
                for field in right.fields
            )
        }
    )
    with pytest.raises(ValueError, match="关联字段"):
        build_relation_evidence_graph(
            candidates.model_copy(update={"objects": (candidates.objects[0], numeric)}),
            catalog,
            proposed_joins=(_join(),),
        )
    with pytest.raises(ValueError, match="数据源"):
        build_relation_evidence_graph(
            candidates.model_copy(
                update={
                    "objects": (
                        candidates.objects[0],
                        right.model_copy(update={"data_source_ref": "other"}),
                    )
                }
            ),
            catalog,
            proposed_joins=(_join(),),
        )


def test_graph_rejects_snapshot_mismatch():
    candidates, catalog = _catalog()
    with pytest.raises(ValueError, match="版本"):
        build_relation_evidence_graph(
            candidates.model_copy(update={"package_sha256": "b" * 64}), catalog
        )


def test_graph_is_immutable_and_rejects_extra_fields():
    graph = build_relation_evidence_graph(*_catalog())
    with pytest.raises(ValidationError):
        graph.object_refs = ()
    with pytest.raises(ValidationError):
        RelationEvidenceGraph(**graph.model_dump(), sql="SELECT 1")
