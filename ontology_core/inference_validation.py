"""Validate LLM candidate plans against published metadata without guessing SQL."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import Field

from ontology_core.errors import TemporalIntentError
from ontology_core.inference_join_semantics import join_semantics_error
from ontology_core.inference_models import (
    CandidateContext,
    CandidateField,
    Confidence,
    InferenceEvidence,
    InferredProgramDraft,
    ValidatedInferenceTemporalDecision,
    ValidatedInferredFilter,
    ValidatedInferredJoin,
    ValidatedInferredProgram,
    ValidatedInferredAggregation,
)
from ontology_core.metadata_candidates import MetadataCandidateCatalog
from ontology_core.models import FrozenModel
from ontology_core.normalization import datatype_group as _datatype_group, normalize_text
from ontology_core.program_models import ProgramDiagnostic
from ontology_core.relation_evidence import RelationEvidenceGraph, RelationEvidenceSource
from ontology_core.semantic_models import RuleOperator
from ontology_core.temporal import TemporalTarget, parse_temporal_intents

_TOKEN = re.compile(r"[a-z0-9]+|[\u3400-\u9fff]{2,}")


class InferenceValidationResult(FrozenModel):
    plan: ValidatedInferredProgram | None = None
    diagnostics: tuple[ProgramDiagnostic, ...] = ()
    missing_information: tuple[str, ...] = Field(default=())


def _failure(code: str, message: str, missing: str) -> InferenceValidationResult:
    return InferenceValidationResult(
        diagnostics=(ProgramDiagnostic(code=code, message=message),),
        missing_information=(missing,),
    )


def _field_words(field: CandidateField) -> set[str]:
    text = normalize_text(" ".join((field.physical_name, field.label, field.description or "")))
    words = set(_TOKEN.findall(text))
    for word in tuple(words):
        if "\u3400" <= word[:1] <= "\u9fff":
            words.update(word[index : index + 2] for index in range(max(0, len(word) - 1)))
    return {item for item in words if len(item) >= 2}


def _join_has_metadata_basis(left: CandidateField, right: CandidateField) -> bool:
    if normalize_text(left.physical_name) == normalize_text(right.physical_name):
        return True
    if normalize_text(left.label) == normalize_text(right.label):
        return True
    return bool(_field_words(left) & _field_words(right))


def _value_has_basis(value: str, request: str, field: CandidateField) -> bool:
    normalized = normalize_text(value)
    if not normalized:
        return False
    sources = (
        normalize_text(request),
        normalize_text(field.label),
        normalize_text(field.description or ""),
    )
    return any(normalized in source for source in sources)


def _valid_value_count(operator: RuleOperator, values: tuple[str, ...]) -> bool:
    if operator == RuleOperator.IS_NULL:
        return not values
    if operator == RuleOperator.BETWEEN:
        return len(values) == 2
    if operator == RuleOperator.IN:
        return bool(values)
    return len(values) == 1


class MetadataInferenceValidator:
    def validate(
        self,
        draft: InferredProgramDraft,
        *,
        candidates: CandidateContext,
        catalog: MetadataCandidateCatalog,
        system_time: datetime,
        request: str,
        relation_graph: RelationEvidenceGraph | None = None,
    ) -> InferenceValidationResult:
        if draft.blocking_issues:
            return _failure(
                "incomplete_inferred_semantics",
                "候选计划存在未实现的核心业务语义",
                "；".join(draft.blocking_issues),
            )
        snapshot = catalog.snapshot
        if (
            candidates.package_id,
            candidates.package_version,
            candidates.package_sha256,
        ) != (
            snapshot.info.package_id,
            snapshot.info.version,
            snapshot.info.sha256,
        ):
            return _failure(
                "candidate_snapshot_changed",
                "候选目录与当前本体版本不一致",
                "请基于当前活动本体版本重新生成候选计划",
            )

        objects_by_ref = {item.ref: item for item in candidates.objects}
        if relation_graph is not None and (
            relation_graph.package_sha256 != candidates.package_sha256
            or not set(draft.selected_object_refs).issubset(relation_graph.object_refs)
        ):
            return _failure(
                "candidate_snapshot_changed", "关系证据与候选快照不一致", "请重新生成候选计划"
            )
        fields_by_ref = {
            field.ref: field for object_ in candidates.objects for field in object_.fields
        }
        families_by_ref = {item.ref: item for item in candidates.families}
        unknown_objects = set(draft.selected_object_refs) - set(objects_by_ref)
        if unknown_objects:
            return _failure(
                "unknown_object_ref",
                "候选计划引用了目录外对象",
                "请补充或发布需求所需的表元数据",
            )
        unknown_families = set(draft.selected_family_refs) - set(families_by_ref)
        if unknown_families:
            return _failure(
                "unknown_family_ref",
                "候选计划引用了目录外表族",
                "请确认分表范围或补充同构表元数据",
            )

        selected_families = tuple(families_by_ref[ref] for ref in draft.selected_family_refs)
        expanded_refs = set(draft.selected_object_refs)
        for family in selected_families:
            missing_members = set(family.member_refs) - set(objects_by_ref)
            if missing_members:
                return _failure(
                    "incomplete_candidate_family",
                    "候选表族成员不完整",
                    "请重新召回当前活动版本中的完整表族",
                )
            expanded_refs.update(family.member_refs)
        selected_objects = tuple(objects_by_ref[ref] for ref in sorted(expanded_refs))
        source_refs = {item.data_source_ref for item in selected_objects}
        if len(source_refs) != 1:
            return _failure(
                "cross_source_candidate",
                "候选计划跨越多个数据源",
                "请补充跨数据源处理方式或将需求拆分",
            )
        source_ref = next(iter(source_refs))
        data_source = next(
            (item for item in snapshot.catalog.data_sources if item.uri == source_ref),
            None,
        )
        if data_source is None:
            return _failure(
                "candidate_source_unavailable",
                "候选对象的数据源在活动本体中不存在",
                "请修复对象到数据源的映射",
            )

        requested_fields: list[CandidateField] = []
        for ref in draft.requested_field_refs:
            field = fields_by_ref.get(ref)
            if field is None:
                return _failure(
                    "unknown_field_ref",
                    "候选计划引用了目录外字段",
                    "请补充或发布需求所需的字段元数据",
                )
            if field.object_ref not in expanded_refs:
                return _failure(
                    "field_ownership_mismatch",
                    "候选输出字段不属于已选对象",
                    "请确认输出字段所属表",
                )
            requested_fields.append(field)

        member_family = {
            member: family.ref for family in selected_families for member in family.member_refs
        }

        def logical_node(object_ref: str) -> str:
            return member_family.get(object_ref, object_ref)

        logical_nodes = {
            *(family.ref for family in selected_families),
            *(ref for ref in draft.selected_object_refs if ref not in member_family),
        }
        validated_joins: list[ValidatedInferredJoin] = []
        edges: set[frozenset[str]] = set()
        for join in draft.joins:
            left_object = objects_by_ref.get(join.left_object_ref)
            right_object = objects_by_ref.get(join.right_object_ref)
            left = fields_by_ref.get(join.left_field_ref)
            right = fields_by_ref.get(join.right_field_ref)
            if (
                left_object is None
                or right_object is None
                or join.left_object_ref not in expanded_refs
                or join.right_object_ref not in expanded_refs
                or left is None
                or right is None
                or left.object_ref != join.left_object_ref
                or right.object_ref != join.right_object_ref
            ):
                return _failure(
                    "invalid_join_reference",
                    "候选关联键与对象归属不一致",
                    "请确认两张表及各自关联字段",
                )
            if _datatype_group(left.datatype_uri) != _datatype_group(right.datatype_uri):
                return _failure(
                    "incompatible_join_types",
                    "候选关联字段类型不兼容",
                    "请提供类型兼容的关联键或明确转换口径",
                )
            edge = (
                relation_graph.matching(left.ref, right.ref) if relation_graph is not None else None
            )
            if (relation_graph is not None and edge is None) or (
                relation_graph is None and not _join_has_metadata_basis(left, right)
            ):
                return _failure(
                    "unsupported_join_evidence",
                    "字段元数据不足以支持候选关联",
                    "请补充表关系、关联键或更明确的字段描述",
                )
            left_node = logical_node(join.left_object_ref)
            right_node = logical_node(join.right_object_ref)
            if left_node != right_node:
                edges.add(frozenset((left_node, right_node)))
            confidence = (
                edge.confidence
                if edge is not None
                else Confidence.MEDIUM
                if join.confidence == Confidence.HIGH
                else join.confidence
            )
            validated_joins.append(
                ValidatedInferredJoin(
                    join_type=join.join_type,
                    anti_strategy=join.anti_strategy,
                    left_object_ref=join.left_object_ref,
                    left_field=left,
                    right_object_ref=join.right_object_ref,
                    right_field=right,
                    confidence=confidence,
                    evidence=edge.evidence if edge is not None else join.evidence,
                )
            )
        semantic_error = join_semantics_error(validated_joins, requested_fields, member_family)
        if semantic_error:
            return _failure(
                "unsupported_join_semantics", semantic_error, "请调整关联方向或排除集合"
            )
        if len(logical_nodes) > 1 and not self._connected(logical_nodes, edges):
            return _failure(
                "missing_candidate_join",
                "多表候选计划缺少完整关联路径",
                "请补充表关系和关联键，避免笛卡尔积",
            )

        validated_filters: list[ValidatedInferredFilter] = []
        for filter_ in draft.filters:
            field = fields_by_ref.get(filter_.field_ref)
            if field is None or field.object_ref not in expanded_refs:
                return _failure(
                    "invalid_filter_reference",
                    "候选过滤字段不属于已选对象",
                    "请确认过滤条件对应的表字段",
                )
            if not _valid_value_count(filter_.operator, filter_.values):
                return _failure(
                    "invalid_filter_shape",
                    "候选过滤条件的值数量无效",
                    "请确认过滤运算符及对应值",
                )
            if any(not _value_has_basis(value, request, field) for value in filter_.values):
                return _failure(
                    "unsupported_filter_value",
                    "候选过滤值缺少用户需求或字段元数据依据",
                    f"请确认字段“{field.label}”的业务取值口径",
                )
            validated_filters.append(
                ValidatedInferredFilter(
                    scope=filter_.scope,
                    field=field,
                    operator=filter_.operator,
                    values=filter_.values,
                    confidence=filter_.confidence,
                    evidence=filter_.evidence,
                )
            )

        group_by_fields: list[CandidateField] = []
        for ref in draft.group_by_field_refs:
            field = fields_by_ref.get(ref)
            if field is None or field.object_ref not in expanded_refs:
                return _failure(
                    "invalid_group_reference", "候选分组字段不属于已选对象", "请确认分组字段所属表"
                )
            group_by_fields.append(field)
        aggregations: list[ValidatedInferredAggregation] = []
        for aggregation in draft.aggregations:
            field = fields_by_ref.get(aggregation.source_field_ref)
            if aggregation.source_field_ref is not None and (
                field is None or field.object_ref not in expanded_refs
            ):
                return _failure(
                    "invalid_aggregation_reference",
                    "候选聚合字段不属于已选对象",
                    "请确认聚合字段所属表",
                )
            if (
                aggregation.function in {"sum", "avg"}
                and field is not None
                and _datatype_group(field.datatype_uri) != "numeric"
            ):
                return _failure(
                    "incompatible_aggregation_type",
                    "求和与平均聚合需要数值字段",
                    "请提供数值字段或明确转换口径",
                )
            aggregations.append(
                ValidatedInferredAggregation(
                    name=aggregation.name,
                    function=aggregation.function,
                    source_field=field,
                    distinct=aggregation.distinct,
                )
            )
        if aggregations and not set(draft.requested_field_refs).issubset(draft.group_by_field_refs):
            return _failure(
                "invalid_aggregate_projection",
                "聚合输出包含未分组的明细字段",
                "请确认分组粒度与输出字段",
            )

        temporal_decisions: list[ValidatedInferenceTemporalDecision] = []
        for object_ in selected_objects:
            policy = object_.temporal_policy
            if policy is None:
                return _failure(
                    "missing_temporal_policy",
                    "候选对象缺少安全的时间分区策略",
                    f"请检查对象“{object_.label}”的表名后缀与分区字段："
                    "_D 对应 P_DAY，_M 对应 P_MON",
                )
            partition_field = next(
                (item for item in object_.fields if item.ref == policy.partition_field_ref),
                None,
            )
            if partition_field is None:
                return _failure(
                    "missing_partition_field",
                    "时间策略的分区字段不在候选目录中",
                    f"请补充对象“{object_.label}”的分区字段映射",
                )
            target = TemporalTarget(
                property_uri=partition_field.ref,
                aliases=(partition_field.label, partition_field.physical_name),
                datatype_uri=partition_field.datatype_uri,
            )
            try:
                parsed = parse_temporal_intents(
                    draft.time_expression or request,
                    system_date=system_time.date(),
                    grain=policy.grain,
                    default_strategy=policy.default_strategy,
                    partition_target=target,
                )
            except TemporalIntentError:
                return _failure(
                    "unsafe_candidate_time",
                    "候选账期冲突、无界或无法安全解析",
                    "请明确一个有限的业务账期",
                )
            temporal_decisions.append(
                ValidatedInferenceTemporalDecision(
                    object_ref=object_.ref,
                    partition_field=partition_field,
                    grain=policy.grain,
                    source=(
                        "default" if parsed.partition.source.value == "ontology_default" else "user"
                    ),
                    resolved_start=parsed.partition.start,
                    resolved_end=parsed.partition.end,
                    explanation=parsed.partition.explanation,
                )
            )

        inferred_confidences = (
            *(item.confidence for item in validated_joins),
            *(item.confidence for item in validated_filters),
        )
        overall = Confidence.LOW if Confidence.LOW in inferred_confidences else Confidence.MEDIUM
        automatic_unresolved = tuple(
            f"关系 {item.left_object_ref} → {item.right_object_ref} 尚未写入本体"
            for item in validated_joins
            if relation_graph is None
            or relation_graph.matching(item.left_field.ref, item.right_field.ref).source
            != RelationEvidenceSource.ONTOLOGY
        )
        automatic_suggestions = tuple(
            "补充关系："
            f"{item.left_object_ref}.{item.left_field.ref} = "
            f"{item.right_object_ref}.{item.right_field.ref}"
            for item in validated_joins
            if relation_graph is None
            or relation_graph.matching(item.left_field.ref, item.right_field.ref).source
            != RelationEvidenceSource.ONTOLOGY
        )
        reasons = (
            f"已从活动本体版本选择 {len(selected_objects)} 个真实对象",
            *(reason for item in validated_joins for reason in item.evidence),
            *(reason for item in validated_filters for reason in item.evidence),
        )
        return InferenceValidationResult(
            plan=ValidatedInferredProgram(
                package_id=snapshot.info.package_id,
                package_version=snapshot.info.version,
                package_sha256=snapshot.info.sha256,
                data_source_ref=source_ref,
                dialect=data_source.dialect or data_source.platform_type,
                objects=selected_objects,
                families=selected_families,
                requested_fields=tuple(requested_fields),
                joins=tuple(validated_joins),
                filters=tuple(validated_filters),
                group_by_fields=tuple(group_by_fields),
                aggregations=tuple(aggregations),
                temporal_decisions=tuple(temporal_decisions),
                evidence=InferenceEvidence(
                    overall_confidence=overall,
                    reasons=reasons,
                    unresolved_items=tuple(
                        dict.fromkeys((*draft.unresolved_items, *automatic_unresolved))
                    ),
                    ontology_suggestions=tuple(
                        dict.fromkeys((*draft.ontology_suggestions, *automatic_suggestions))
                    ),
                ),
            )
        )

    @staticmethod
    def _connected(
        nodes: set[str],
        edges: set[frozenset[str]],
    ) -> bool:
        if len(nodes) <= 1:
            return True
        visited = {next(iter(nodes))}
        changed = True
        while changed:
            changed = False
            for edge in edges:
                if edge & visited and not edge <= visited:
                    visited.update(edge)
                    changed = True
        return visited == nodes
