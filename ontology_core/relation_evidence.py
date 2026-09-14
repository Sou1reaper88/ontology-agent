"""Read-only relationship evidence; an empty graph is a valid starting point."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from ontology_core.inference_models import (
    CandidateContext,
    Confidence,
    InferredJoinDraft,
    SemanticRef,
)
from ontology_core.metadata_candidates import MetadataCandidateCatalog
from ontology_core.models import FrozenModel
from ontology_core.normalization import datatype_group


class RelationEvidenceSource(StrEnum):
    ONTOLOGY = "ontology"
    USER = "user"
    MODEL = "model"


class RelationEvidenceEdge(FrozenModel):
    left_object_ref: SemanticRef
    left_field_ref: SemanticRef
    right_object_ref: SemanticRef
    right_field_ref: SemanticRef
    join_type: Literal["inner", "left", "anti"]
    source: RelationEvidenceSource
    confidence: Confidence
    evidence: tuple[str, ...] = Field(min_length=1)


class RelationEvidenceGraph(FrozenModel):
    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    object_refs: tuple[SemanticRef, ...]
    edges: tuple[RelationEvidenceEdge, ...] = ()

    def matching(self, left_field_ref: str, right_field_ref: str) -> RelationEvidenceEdge | None:
        """Match key evidence in either direction, not a license to reverse a LEFT JOIN."""
        return next(
            (
                edge
                for edge in self.edges
                if (edge.left_field_ref, edge.right_field_ref)
                in {
                    (left_field_ref, right_field_ref),
                    (right_field_ref, left_field_ref),
                }
            ),
            None,
        )


def build_relation_evidence_graph(
    candidates: CandidateContext,
    catalog: MetadataCandidateCatalog,
    *,
    proposed_joins: tuple[InferredJoinDraft, ...] = (),
) -> RelationEvidenceGraph:
    snapshot = catalog.snapshot
    if (candidates.package_id, candidates.package_version, candidates.package_sha256) != (
        snapshot.info.package_id,
        snapshot.info.version,
        snapshot.info.sha256,
    ):
        raise ValueError("关系证据与候选目录的本体版本不一致")
    objects = {obj.ref: obj for obj in candidates.objects}
    fields = {field.ref: field for obj in candidates.objects for field in obj.fields}
    concepts = {concept.uri: concept.short_name for concept in snapshot.catalog.concepts}
    properties = {prop.uri: prop.short_name for prop in snapshot.catalog.properties}
    edges: dict[tuple, RelationEvidenceEdge] = {}

    def add(left_obj, left_ref, right_obj, right_ref, join_type, source, confidence, evidence):
        left, right = fields.get(left_ref), fields.get(right_ref)
        if (
            left_obj not in objects
            or right_obj not in objects
            or left_obj == right_obj
            or left is None
            or right is None
            or left.object_ref != left_obj
            or right.object_ref != right_obj
        ):
            raise ValueError("关联字段不存在、对象归属错误或使用了不支持的自关联")
        if objects[left_obj].data_source_ref != objects[right_obj].data_source_ref:
            raise ValueError("关联字段不能跨数据源")
        if datatype_group(left.datatype_uri) != datatype_group(right.datatype_uri):
            raise ValueError("关联字段类型不兼容")
        # Only INNER joins are direction-independent. LEFT/ANTI proposals remain directed.
        key = (
            (join_type, *sorted((left_ref, right_ref)))
            if join_type == "inner"
            else (
                join_type,
                left_ref,
                right_ref,
            )
        )
        edge = RelationEvidenceEdge(
            left_object_ref=left_obj,
            left_field_ref=left_ref,
            right_object_ref=right_obj,
            right_field_ref=right_ref,
            join_type=join_type,
            source=source,
            confidence=confidence,
            evidence=evidence,
        )
        previous = edges.get(key)
        priority = {
            RelationEvidenceSource.ONTOLOGY: 0,
            RelationEvidenceSource.USER: 1,
            RelationEvidenceSource.MODEL: 2,
        }
        if previous is None or priority[edge.source] < priority[previous.source]:
            edges[key] = edge

    for relation in sorted(snapshot.catalog.relations, key=lambda item: (-item.priority, item.uri)):
        if relation.status != "active" or not relation.confirmed:
            continue
        left_obj, right_obj = (
            concepts.get(relation.source_concept_uri),
            concepts.get(relation.target_concept_uri),
        )
        left_ref, right_ref = (
            properties.get(relation.source_property_uri),
            properties.get(relation.target_property_uri),
        )
        if (
            left_obj not in objects
            or right_obj not in objects
            or left_ref not in fields
            or right_ref not in fields
        ):
            continue
        add(
            left_obj,
            left_ref,
            right_obj,
            right_ref,
            "inner",
            RelationEvidenceSource.ONTOLOGY,
            Confidence.HIGH,
            (relation.description or relation.label,),
        )

    for join in proposed_joins:
        add(
            join.left_object_ref,
            join.left_field_ref,
            join.right_object_ref,
            join.right_field_ref,
            join.join_type,
            RelationEvidenceSource(join.relation_source),
            Confidence.MEDIUM if join.confidence == Confidence.HIGH else join.confidence,
            join.evidence,
        )

    return RelationEvidenceGraph(
        package_sha256=candidates.package_sha256,
        object_refs=tuple(sorted(objects)),
        edges=tuple(edges.values()),
    )
