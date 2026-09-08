"""Deterministic draft diagnostics and the publishability gate."""

from __future__ import annotations

import hashlib
import re
from collections import Counter

from ontology_core.errors import OntologyError
from ontology_core.management.models import DraftDiagnostic, DraftRelation, WorkspaceDraft
from ontology_core.metadata_package import _semantic_short_name
from ontology_core.normalization import normalize_text
from ontology_core.semantic_models import TemporalDefaultStrategy, TemporalGrain

_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_XSD_TYPES = frozenset({"string", "integer", "decimal", "boolean", "date", "dateTime"})


class DraftNotPublishableError(OntologyError):
    """Raised when unresolved draft diagnostics prevent publication."""

    code = "draft_not_publishable"
    status_code = 422

    def __init__(self, *, diagnostics: tuple[DraftDiagnostic, ...]) -> None:
        super().__init__("草稿尚未满足发布条件")
        self.diagnostics = diagnostics


class DraftValidator:
    """Validate a draft without relying on rendered diagnostic text for identity."""

    def validate(self, draft: WorkspaceDraft) -> tuple[DraftDiagnostic, ...]:
        """Return deterministic diagnostics for the draft's current semantic IDs."""
        diagnostics: list[DraftDiagnostic] = []
        diagnostics.extend(self._identity_diagnostics(draft))
        diagnostics.extend(self._managed_short_name_diagnostics(draft))
        fields_by_id = self._fields_by_id(draft)
        diagnostics.extend(self._relation_diagnostics(draft, fields_by_id))
        diagnostics.extend(self._temporal_diagnostics(draft, fields_by_id))
        return tuple(sorted(diagnostics, key=lambda item: item.id))

    def assert_publishable(self, draft: WorkspaceDraft) -> tuple[DraftDiagnostic, ...]:
        """Return diagnostics or raise when errors remain unresolved."""
        diagnostics = self.validate(draft)
        blocking = tuple(
            item
            for item in diagnostics
            if item.severity == "error"
            or (item.severity == "confirmation_required" and not self._is_resolved(draft, item))
        )
        if blocking:
            raise DraftNotPublishableError(diagnostics=blocking)
        return diagnostics

    def relation_is_effectively_confirmed(
        self, draft: WorkspaceDraft, relation: DraftRelation
    ) -> bool:
        """Return whether an active relation has direct or exact disposed confirmation."""
        if relation.confirmed:
            return True
        if relation.status != "active":
            return False
        return self._is_resolved(draft, _relation_confirmation_diagnostic(relation))

    def _identity_diagnostics(self, draft: WorkspaceDraft) -> list[DraftDiagnostic]:
        diagnostics: list[DraftDiagnostic] = []
        diagnostics.extend(
            self._duplicates("duplicate_object_id", (item.id for item in draft.objects))
        )
        fields = tuple(field for object_ in draft.objects for field in object_.fields)
        diagnostics.extend(self._duplicates("duplicate_field_id", (item.id for item in fields)))
        diagnostics.extend(
            self._duplicates("duplicate_relation_id", (item.id for item in draft.relations))
        )
        for object_ in draft.objects:
            if not _IDENTIFIER.fullmatch(object_.physical_name):
                diagnostics.append(
                    _diagnostic(
                        "invalid_object_identifier",
                        "对象物理标识符无效",
                        "error",
                        (object_.id,),
                    )
                )
            for field in object_.fields:
                if not _IDENTIFIER.fullmatch(field.physical_name):
                    diagnostics.append(
                        _diagnostic(
                            "invalid_field_identifier",
                            "属性物理标识符无效",
                            "error",
                            (field.id,),
                        )
                    )
                if field.xsd_type not in _XSD_TYPES:
                    diagnostics.append(
                        _diagnostic(
                            "invalid_field_type",
                            "属性类型未配置或不受支持",
                            "error",
                            (field.id,),
                        )
                    )
        return diagnostics

    @staticmethod
    def _managed_short_name_diagnostics(draft: WorkspaceDraft) -> list[DraftDiagnostic]:
        derived: list[tuple[str, tuple[str, str], tuple[str, ...]]] = []

        def add(
            kind: str,
            stable_id: str,
            subject_key: tuple[str, str],
            related_ids: tuple[str, ...],
        ) -> None:
            derived.append(
                (normalize_text(managed_short_name(kind, stable_id)), subject_key, related_ids)
            )

        add(
            "DataSource",
            draft.data_source.id,
            ("source", draft.data_source.id),
            (draft.data_source.id,),
        )
        for object_ in draft.objects:
            add("Concept", object_.id, ("concept", object_.id), (object_.id,))
            add(
                "ObjectMapping",
                object_.id,
                ("mapping", f"object/{object_.id}"),
                (object_.id,),
            )
            for field in object_.fields:
                add("Property", field.id, ("property", field.id), (field.id,))
                add(
                    "FieldMapping",
                    field.id,
                    ("mapping", f"field/{field.id}"),
                    (field.id,),
                )
        for relation in draft.relations:
            add("Relation", relation.id, ("relation", relation.id), (relation.id,))
        for policy in draft.temporal_policies:
            policy_id = f"{policy.object_id}/{policy.partition_field_id}"
            add(
                "TemporalPolicy",
                policy_id,
                ("policy", policy_id),
                (policy.object_id, policy.partition_field_id),
            )

        groups: dict[str, dict[tuple[str, str], set[str]]] = {}
        for normalized_name, subject_key, related_ids in derived:
            groups.setdefault(normalized_name, {}).setdefault(subject_key, set()).update(
                related_ids
            )
        diagnostics: dict[str, DraftDiagnostic] = {}
        for subjects in groups.values():
            if len(subjects) <= 1:
                continue
            diagnostic = _diagnostic(
                "duplicate_managed_short_name",
                "派生语义短名称冲突",
                "error",
                tuple(
                    related_id for related_ids in subjects.values() for related_id in related_ids
                ),
            )
            diagnostics[diagnostic.id] = diagnostic
        return list(diagnostics.values())

    def _relation_diagnostics(
        self, draft: WorkspaceDraft, fields_by_id: dict[str, str]
    ) -> list[DraftDiagnostic]:
        diagnostics: list[DraftDiagnostic] = []
        object_ids = {item.id for item in draft.objects}
        fields = {
            field.id: field
            for object_ in draft.objects
            for field in object_.fields
            if fields_by_id.get(field.id) == object_.id
        }
        for relation in draft.relations:
            endpoint_ids = (
                relation.source_object_id,
                relation.source_field_id,
                relation.target_object_id,
                relation.target_field_id,
            )
            source_owned = (
                relation.source_object_id in object_ids
                and fields_by_id.get(relation.source_field_id) == relation.source_object_id
            )
            target_owned = (
                relation.target_object_id in object_ids
                and fields_by_id.get(relation.target_field_id) == relation.target_object_id
            )
            if not source_owned or not target_owned:
                diagnostics.append(
                    _diagnostic(
                        "relation_endpoint_not_owned",
                        "关系端点必须引用所属对象的属性",
                        "error",
                        (relation.id, *endpoint_ids),
                    )
                )
                continue
            if relation.status != "active":
                continue
            if not relation.confirmed:
                diagnostics.append(_relation_confirmation_diagnostic(relation))
            if (
                fields[relation.source_field_id].xsd_type
                != fields[relation.target_field_id].xsd_type
            ):
                diagnostics.append(
                    _diagnostic(
                        "relation_incompatible_field_types",
                        "关系两端属性类型不兼容",
                        "error",
                        (relation.id, relation.source_field_id, relation.target_field_id),
                    )
                )
        return diagnostics

    def _temporal_diagnostics(
        self, draft: WorkspaceDraft, fields_by_id: dict[str, str]
    ) -> list[DraftDiagnostic]:
        diagnostics: list[DraftDiagnostic] = []
        from ontology_core.temporal_conventions import partition_convention

        for object_ in draft.objects:
            convention = partition_convention(object_.physical_name)
            if convention is None or object_.status != "active":
                continue
            partition_name = convention[0]
            matches = [
                field
                for field in object_.fields
                if field.physical_name.upper() == partition_name and field.status == "active"
            ]
            if len(matches) != 1:
                diagnostics.append(
                    _diagnostic(
                        "automatic_partition_field_missing",
                        f"对象 {object_.physical_name} 需要唯一启用的 {partition_name} 分区字段",
                        "error",
                        (object_.id,),
                    )
                )
        object_ids = {item.id for item in draft.objects}
        policy_counts = Counter(policy.object_id for policy in draft.temporal_policies)
        for object_id, count in policy_counts.items():
            if count > 1:
                diagnostics.append(
                    _diagnostic(
                        "multiple_temporal_policies_for_object",
                        "对象存在多个时间策略",
                        "error",
                        (object_id,),
                    )
                )
        expected_strategies = {
            TemporalGrain.DAY: TemporalDefaultStrategy.T_MINUS_2,
            TemporalGrain.MONTH: TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH,
        }
        for policy in draft.temporal_policies:
            if (
                policy.object_id not in object_ids
                or fields_by_id.get(policy.partition_field_id) != policy.object_id
            ):
                diagnostics.append(
                    _diagnostic(
                        "temporal_partition_field_not_owned",
                        "时间策略必须映射对象所属属性",
                        "error",
                        (policy.object_id, policy.partition_field_id),
                    )
                )
            if policy.default_strategy != expected_strategies.get(policy.grain):
                diagnostics.append(
                    _diagnostic(
                        "temporal_strategy_grain_mismatch",
                        "时间策略与粒度不匹配",
                        "error",
                        (policy.object_id, policy.partition_field_id),
                    )
                )
        return diagnostics

    @staticmethod
    def _fields_by_id(draft: WorkspaceDraft) -> dict[str, str]:
        fields_by_id: dict[str, str] = {}
        for object_ in draft.objects:
            for field in object_.fields:
                fields_by_id.setdefault(field.id, object_.id)
        return fields_by_id

    @staticmethod
    def _duplicates(code: str, ids: object) -> list[DraftDiagnostic]:
        counts = Counter(ids)
        return [
            _diagnostic(code, "草稿包含重复稳定标识", "error", (identifier,))
            for identifier, count in counts.items()
            if count > 1
        ]

    @staticmethod
    def _is_resolved(draft: WorkspaceDraft, diagnostic: DraftDiagnostic) -> bool:
        return any(
            disposition.diagnostic_id == diagnostic.id
            and disposition.status in {"resolved", "dismissed"}
            and _has_text(disposition.actor)
            and _has_text(disposition.note)
            for disposition in draft.dispositions
        )


def stable_diagnostic_id(code: str, related_ids: tuple[str, ...]) -> str:
    """Return a message-independent stable diagnostic ID."""
    identity = "\x00".join((code, *sorted(set(related_ids))))
    return f"diagnostic/{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


def managed_short_name(kind: str, stable_id: str) -> str:
    """Derive the exact short name used by managed package construction."""
    return _semantic_short_name(f"{kind}_{stable_id}", kind)


def _relation_confirmation_diagnostic(relation: DraftRelation) -> DraftDiagnostic:
    return _diagnostic(
        "relation_confirmation_required",
        "启用关系需要明确确认",
        "confirmation_required",
        (
            relation.id,
            relation.source_object_id,
            relation.source_field_id,
            relation.target_object_id,
            relation.target_field_id,
        ),
    )


def _diagnostic(
    code: str, message: str, severity: str, related_ids: tuple[str, ...]
) -> DraftDiagnostic:
    normalized_ids = tuple(sorted(set(related_ids)))
    return DraftDiagnostic(
        id=stable_diagnostic_id(code, normalized_ids),
        code=code,
        severity=severity,
        message=message,
        related_ids=normalized_ids,
    )


def _has_text(value: str | None) -> bool:
    return value is not None and bool(value.strip())
