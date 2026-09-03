"""Deterministic metadata retrieval over one immutable ontology snapshot."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from ontology_core.inference_models import (
    CandidateContext,
    CandidateField,
    CandidateObject,
    CandidateTableFamily,
    CandidateTemporalPolicy,
)
from ontology_core.normalization import normalize_text
from ontology_core.repository import OntologySnapshot
from ontology_core.semantic_models import PhysicalMapping, SemanticElement

_WORD = re.compile(r"[a-z0-9_]+")
_CJK = re.compile(r"[\u3400-\u9fff]+")
_BROAD_SCOPE_MARKERS = ("全省", "所有地市", "全部地市", "全量地市", "各地市")


def _terms(request: str) -> tuple[str, ...]:
    normalized = normalize_text(request)
    found: set[str] = set(_WORD.findall(normalized))
    for sequence in _CJK.findall(normalized):
        if len(sequence) >= 2:
            found.add(sequence)
        for width in range(2, min(4, len(sequence)) + 1):
            found.update(
                sequence[index : index + width]
                for index in range(len(sequence) - width + 1)
            )
    return tuple(sorted(found, key=lambda item: (-len(item), item)))


def _rank(
    terms: tuple[str, ...],
    weighted_values: tuple[tuple[str | None, int], ...],
) -> tuple[int, tuple[str, ...]]:
    matched: set[str] = set()
    score = 0
    for value, weight in weighted_values:
        normalized = normalize_text(value or "")
        if not normalized:
            continue
        for term in terms:
            if term and term in normalized:
                matched.add(term)
                score += weight + min(len(term), 8)
    return score, tuple(sorted(matched, key=lambda item: (-len(item), item)))


def _best_mapping(
    mappings: tuple[PhysicalMapping, ...],
    *,
    require_object: bool = False,
    require_field: bool = False,
) -> PhysicalMapping | None:
    candidates = tuple(
        item
        for item in mappings
        if item.enabled
        and (not require_object or item.object_name is not None)
        and (not require_field or item.field_name is not None)
    )
    return min(candidates, key=lambda item: (-item.priority, item.uri), default=None)


def _semantic_text(element: SemanticElement) -> tuple[str, ...]:
    return (
        element.short_name,
        element.label,
        element.description or "",
        *(item.value for item in element.labels),
    )


class MetadataCandidateCatalog:
    """A read-only physical candidate index derived from one published package."""

    def __init__(
        self,
        snapshot: OntologySnapshot,
        objects: tuple[CandidateObject, ...],
        families: tuple[CandidateTableFamily, ...],
    ) -> None:
        self._snapshot = snapshot
        self._objects = objects
        self._families = families
        self._objects_by_ref = {item.ref: item for item in objects}
        self._fields_by_ref = {
            field.ref: field for object_ in objects for field in object_.fields
        }
        self._families_by_ref = {item.ref: item for item in families}

    @property
    def snapshot(self) -> OntologySnapshot:
        return self._snapshot

    @property
    def objects(self) -> tuple[CandidateObject, ...]:
        return self._objects

    @property
    def families(self) -> tuple[CandidateTableFamily, ...]:
        return self._families

    @classmethod
    def from_snapshot(cls, snapshot: OntologySnapshot) -> MetadataCandidateCatalog:
        catalog = snapshot.catalog
        mappings_by_element: dict[str, list[PhysicalMapping]] = defaultdict(list)
        for mapping in catalog.mappings:
            mappings_by_element[mapping.semantic_element_uri].append(mapping)
        properties_by_concept = defaultdict(list)
        for property_ in catalog.properties:
            properties_by_concept[property_.concept_uri].append(property_)
        policies_by_concept = defaultdict(list)
        for policy in catalog.temporal_policies:
            if policy.status == "active":
                policies_by_concept[policy.applies_to_uri].append(policy)

        objects: list[CandidateObject] = []
        for concept in sorted(catalog.concepts, key=lambda item: (item.short_name, item.uri)):
            object_mapping = _best_mapping(
                tuple(mappings_by_element[concept.uri]),
                require_object=True,
            )
            if object_mapping is None or object_mapping.object_name is None:
                continue
            fields: list[CandidateField] = []
            for property_ in sorted(
                properties_by_concept[concept.uri],
                key=lambda item: (item.short_name, item.uri),
            ):
                field_mapping = _best_mapping(
                    tuple(
                        item
                        for item in mappings_by_element[property_.uri]
                        if item.data_source_uri == object_mapping.data_source_uri
                    ),
                    require_field=True,
                )
                if field_mapping is None or field_mapping.field_name is None:
                    continue
                fields.append(
                    CandidateField(
                        ref=property_.short_name,
                        object_ref=concept.short_name,
                        label=property_.label,
                        description=property_.description,
                        datatype_uri=property_.datatype_uri,
                        physical_name=field_mapping.field_name,
                    )
                )
            if not fields:
                continue
            policy = min(
                policies_by_concept[concept.uri],
                key=lambda item: (-item.priority, item.uri),
                default=None,
            )
            candidate_policy = None
            if policy is not None:
                partition = next(
                    (
                        item
                        for item in catalog.properties
                        if item.uri == policy.partition_property_uri
                    ),
                    None,
                )
                if partition is not None:
                    candidate_policy = CandidateTemporalPolicy(
                        ref=policy.short_name,
                        partition_field_ref=partition.short_name,
                        grain=policy.grain,
                        default_strategy=policy.default_strategy,
                        allow_query_override=policy.allow_query_override,
                    )
            objects.append(
                CandidateObject(
                    ref=concept.short_name,
                    label=concept.label,
                    description=concept.description,
                    data_source_ref=object_mapping.data_source_uri,
                    physical_namespace=object_mapping.physical_namespace,
                    physical_name=object_mapping.object_name,
                    fields=tuple(fields),
                    temporal_policy=candidate_policy,
                )
            )

        families = cls._build_families(tuple(objects))
        family_by_member = {
            member: family.ref for family in families for member in family.member_refs
        }
        bound_objects = tuple(
            item.model_copy(update={"family_ref": family_by_member.get(item.ref)})
            for item in objects
        )
        return cls(snapshot, bound_objects, families)

    @staticmethod
    def _build_families(
        objects: tuple[CandidateObject, ...],
    ) -> tuple[CandidateTableFamily, ...]:
        signature_groups: dict[tuple, list[CandidateObject]] = defaultdict(list)
        for object_ in objects:
            field_signature = tuple(
                sorted(
                    (item.physical_name.casefold(), item.datatype_uri)
                    for item in object_.fields
                )
            )
            policy = object_.temporal_policy
            temporal_signature = (
                policy.grain.value,
                policy.default_strategy.value,
                next(
                    (
                        field.physical_name.casefold()
                        for field in object_.fields
                        if field.ref == policy.partition_field_ref
                    ),
                    None,
                ),
            ) if policy is not None else None
            tokens = tuple(object_.physical_name.casefold().split("_"))
            signature_groups[
                (
                    object_.data_source_ref,
                    normalize_text(object_.physical_namespace or ""),
                    field_signature,
                    temporal_signature,
                    len(tokens),
                )
            ].append(object_)

        candidates: dict[tuple[str, ...], tuple[int, tuple[CandidateObject, ...]]] = {}
        for grouped in signature_groups.values():
            if len(grouped) < 2:
                continue
            by_template: dict[
                tuple[int, tuple[str, ...]], list[CandidateObject]
            ] = defaultdict(list)
            for object_ in grouped:
                tokens = tuple(object_.physical_name.casefold().split("_"))
                for index in range(len(tokens)):
                    template = (*tokens[:index], "*", *tokens[index + 1 :])
                    by_template[(index, template)].append(object_)
            for (index, _), members in by_template.items():
                values = {
                    item.physical_name.casefold().split("_")[index] for item in members
                }
                member_refs = tuple(sorted(item.ref for item in members))
                if len(values) >= 2 and len(member_refs) >= 2:
                    previous = candidates.get(member_refs)
                    ordered = tuple(sorted(members, key=lambda item: item.ref))
                    if previous is None or index < previous[0]:
                        candidates[member_refs] = (index, ordered)

        families: list[CandidateTableFamily] = []
        for member_refs, (index, members) in sorted(candidates.items()):
            digest = hashlib.sha256("\0".join(member_refs).encode("utf-8")).hexdigest()[:16]
            families.append(
                CandidateTableFamily(
                    ref=f"family.{digest}",
                    label=f"{members[0].label}等同构表",
                    member_refs=member_refs,
                    varying_token_index=index,
                )
            )
        return tuple(families)

    def retrieve(
        self,
        request: str,
        *,
        object_limit: int = 8,
        field_limit_per_object: int = 40,
    ) -> CandidateContext:
        terms = _terms(request)
        ranked: list[CandidateObject] = []
        for object_ in self._objects:
            fields: list[CandidateField] = []
            for field in object_.fields:
                score, matched = _rank(
                    terms,
                    (
                        (field.physical_name, 120),
                        (field.label, 100),
                        (field.description, 70),
                    ),
                )
                fields.append(
                    field.model_copy(
                        update={"retrieval_score": score, "matched_terms": matched}
                    )
                )
            fields.sort(key=lambda item: (-item.retrieval_score, item.ref))
            object_score, object_terms = _rank(
                terms,
                (
                    (object_.physical_name, 140),
                    (object_.label, 120),
                    (object_.description, 90),
                ),
            )
            field_score = fields[0].retrieval_score // 4 if fields else 0
            ranked.append(
                object_.model_copy(
                    update={
                        "fields": tuple(fields[:field_limit_per_object]),
                        "retrieval_score": object_score + field_score,
                        "matched_terms": object_terms,
                    }
                )
            )
        ranked.sort(key=lambda item: (-item.retrieval_score, item.ref))
        selected = [item for item in ranked if item.retrieval_score > 0][:object_limit]

        is_broad = any(marker in normalize_text(request) for marker in _BROAD_SCOPE_MARKERS)
        if is_broad:
            selected_refs = {item.ref for item in selected}
            matching_families = tuple(
                family
                for family in self._families
                if selected_refs.intersection(family.member_refs)
            )
            expanded_refs = {
                member for family in matching_families for member in family.member_refs
            }
            by_ref = {item.ref: item for item in ranked}
            selected = [by_ref[ref] for ref in sorted(selected_refs | expanded_refs)]

        selected_refs = {item.ref for item in selected}
        families = tuple(
            family
            for family in self._families
            if selected_refs.intersection(family.member_refs)
        )
        info = self._snapshot.info
        return CandidateContext(
            package_id=info.package_id,
            package_version=info.version,
            package_sha256=info.sha256,
            objects=tuple(selected),
            families=families,
        )

    def object(self, ref: str) -> CandidateObject:
        return self._objects_by_ref[ref]

    def field(self, ref: str) -> CandidateField:
        return self._fields_by_ref[ref]

    def family(self, ref: str) -> CandidateTableFamily:
        return self._families_by_ref[ref]
