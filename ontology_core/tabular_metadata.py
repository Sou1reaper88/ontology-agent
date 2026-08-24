from __future__ import annotations

import csv
import io
import json
import re
from enum import StrEnum
from pathlib import Path
from typing import Self

import yaml
from pydantic import Field, ValidationError, model_validator

from ontology_core.errors import OntologyImportError
from ontology_core.models import FrozenModel
from ontology_core.normalization import normalize_text
from ontology_core.semantic_models import TemporalDefaultStrategy, TemporalGrain

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_KNOWN_TYPES = {
    "bigint",
    "bool",
    "boolean",
    "date",
    "datetime",
    "decimal",
    "double",
    "float",
    "int",
    "integer",
    "long",
    "number",
    "short",
    "string",
    "timestamp",
}


class DiagnosticSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    CONFIRMATION_REQUIRED = "confirmation_required"


class SourceLocation(FrozenModel):
    line: int = Field(ge=2)
    column: str


class ImportDiagnostic(FrozenModel):
    code: str
    severity: DiagnosticSeverity
    message: str
    location: SourceLocation | None = None
    field_name: str | None = None


class FieldMetadata(FrozenModel):
    physical_name: str
    label: str | None = None
    source_type: str | None = None
    description: str | None = None
    primary_key: bool = False
    title: bool = False
    aliases: tuple[str, ...] = ()
    location: SourceLocation


class TableMetadata(FrozenModel):
    physical_name: str
    label: str | None = None
    description: str | None = None
    enabled: bool = True


class TabularMetadataDraft(FrozenModel):
    table: TableMetadata
    fields: tuple[FieldMetadata, ...]
    object_names: tuple[str, ...] = ()
    diagnostics: tuple[ImportDiagnostic, ...] = ()
    temporal_policy: TemporalPolicyOverride | None = None


class FieldOverride(FrozenModel):
    label: str | None = None
    description: str | None = None
    source_type: str | None = None
    aliases: tuple[str, ...] | None = None


class TemporalPolicyOverride(FrozenModel):
    field: str
    grain: TemporalGrain
    default_strategy: TemporalDefaultStrategy
    allow_query_override: bool = True

    @model_validator(mode="after")
    def validate_pair(self) -> Self:
        expected = {
            TemporalGrain.DAY: TemporalDefaultStrategy.T_MINUS_2,
            TemporalGrain.MONTH: TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH,
        }
        if expected[self.grain] is not self.default_strategy:
            raise ValueError("时间分区粒度与默认策略不匹配")
        return self


class MetadataOverrides(FrozenModel):
    fields: dict[str, FieldOverride] = Field(default_factory=dict)
    temporal_policy: TemporalPolicyOverride | None = None


def _clean(row: dict[str, str | None], column: str) -> str | None:
    value = row.get(column)
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _is_true(value: str | None) -> bool:
    return (value or "").casefold() in {"1", "true", "yes", "y", "是", "启用"}


def parse_tabular_metadata(text: str) -> TabularMetadataDraft:
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    required_headers = {"对象英文名称", "属性英文名"}
    missing_headers = sorted(required_headers - set(reader.fieldnames or ()))
    if missing_headers:
        raise OntologyImportError(
            "元数据缺少必需列",
            details={"columns": missing_headers},
        )
    fields: list[FieldMetadata] = []
    diagnostics: list[ImportDiagnostic] = []
    table_name: str | None = None
    table_label: str | None = None
    table_description: str | None = None
    table_status: str | None = None
    object_names: set[str] = set()

    for line, row in enumerate(reader, start=2):
        current_table = _clean(row, "对象英文名称")
        field_name = _clean(row, "属性英文名")
        if current_table is None:
            diagnostics.append(
                ImportDiagnostic(
                    code="missing_table_name",
                    severity=DiagnosticSeverity.ERROR,
                    message="对象物理名称为空",
                    location=SourceLocation(line=line, column="对象英文名称"),
                )
            )
        if field_name is None:
            diagnostics.append(
                ImportDiagnostic(
                    code="missing_field_name",
                    severity=DiagnosticSeverity.ERROR,
                    message="属性物理名称为空",
                    location=SourceLocation(line=line, column="属性英文名"),
                )
            )
        if current_table is None or field_name is None:
            continue
        object_names.add(current_table)
        table_name = table_name or current_table
        table_label = table_label or _clean(row, "对象中文名称")
        table_description = table_description or _clean(row, "对象描述")
        table_status = table_status or _clean(row, "状态")
        fields.append(
            FieldMetadata(
                physical_name=field_name,
                label=_clean(row, "属性中文名"),
                source_type=_clean(row, "属性类型"),
                description=_clean(row, "属性描述"),
                primary_key=_is_true(_clean(row, "是否主键")),
                title=_is_true(_clean(row, "是否标题")),
                location=SourceLocation(line=line, column="属性英文名"),
            )
        )

    if table_name is None:
        raise OntologyImportError(
            "未解析到有效对象元数据",
            details={"diagnostics": [item.model_dump(mode="json") for item in diagnostics]},
        )
    return TabularMetadataDraft(
        table=TableMetadata(
            physical_name=table_name,
            label=table_label,
            description=table_description,
            enabled=table_status is None or _is_true(table_status),
        ),
        fields=tuple(fields),
        object_names=tuple(sorted(object_names, key=lambda value: (value.casefold(), value))),
        diagnostics=tuple(diagnostics),
    )


def _diagnostic(
    code: str,
    severity: DiagnosticSeverity,
    message: str,
    *,
    field: FieldMetadata | None = None,
) -> ImportDiagnostic:
    return ImportDiagnostic(
        code=code,
        severity=severity,
        message=message,
        location=field.location if field is not None else None,
        field_name=field.physical_name if field is not None else None,
    )


def _comparison_text(value: str) -> str:
    normalized = normalize_text(value)
    for filler in ("字段", "当前", "的"):
        normalized = normalized.replace(filler, "")
    return normalized


def _looks_conflicting(field: FieldMetadata) -> bool:
    if not field.label or not field.description:
        return False
    label = _comparison_text(field.label)
    description = _comparison_text(field.description)
    if not label or not description or label in description or description in label:
        return False
    if len(label) > 24 or len(description) > 24:
        return False
    overlap = set(label) & set(description)
    return not overlap


def analyze_metadata(draft: TabularMetadataDraft) -> tuple[ImportDiagnostic, ...]:
    diagnostics = list(draft.diagnostics)
    if len({name.casefold() for name in draft.object_names}) != 1:
        diagnostics.append(
            _diagnostic(
                "multiple_objects",
                DiagnosticSeverity.ERROR,
                "单次元数据导入只能包含一个对象",
            )
        )
    if not _IDENTIFIER.fullmatch(draft.table.physical_name):
        diagnostics.append(
            _diagnostic(
                "invalid_table_identifier",
                DiagnosticSeverity.ERROR,
                "对象物理名称不是受支持的 SQL 标识符",
            )
        )
    if not draft.table.description:
        diagnostics.append(
            _diagnostic(
                "blank_table_description",
                DiagnosticSeverity.WARNING,
                "对象描述为空",
            )
        )

    seen: dict[str, FieldMetadata] = {}
    for field in draft.fields:
        key = field.physical_name.casefold()
        if key in seen:
            diagnostics.append(
                _diagnostic(
                    "duplicate_field",
                    DiagnosticSeverity.ERROR,
                    "属性物理名称重复",
                    field=field,
                )
            )
        else:
            seen[key] = field
        if not _IDENTIFIER.fullmatch(field.physical_name):
            diagnostics.append(
                _diagnostic(
                    "invalid_field_identifier",
                    DiagnosticSeverity.ERROR,
                    "属性物理名称不是受支持的 SQL 标识符",
                    field=field,
                )
            )
        if not field.description:
            diagnostics.append(
                _diagnostic(
                    "blank_field_description",
                    DiagnosticSeverity.WARNING,
                    "属性描述为空",
                    field=field,
                )
            )
        if field.source_type and field.source_type.casefold() not in _KNOWN_TYPES:
            diagnostics.append(
                _diagnostic(
                    "unknown_field_type",
                    DiagnosticSeverity.WARNING,
                    "属性类型无法可靠映射，将按字符串处理",
                    field=field,
                )
            )
        if _looks_conflicting(field):
            diagnostics.append(
                _diagnostic(
                    "metadata_text_conflict",
                    DiagnosticSeverity.CONFIRMATION_REQUIRED,
                    "属性中文名与描述可能表达不同含义",
                    field=field,
                )
            )
    return tuple(
        sorted(
            diagnostics,
            key=lambda item: (
                item.severity.value,
                item.code,
                item.location.line if item.location else 0,
                item.field_name or "",
            ),
        )
    )


def raise_for_blocking_diagnostics(diagnostics: tuple[ImportDiagnostic, ...]) -> None:
    blocking = tuple(item for item in diagnostics if item.severity is DiagnosticSeverity.ERROR)
    if blocking:
        raise OntologyImportError(
            "元数据包含阻断问题",
            details={
                "diagnostics": [item.model_dump(mode="json") for item in blocking],
            },
        )


def load_metadata_overrides(path: Path) -> MetadataOverrides:
    try:
        content = path.read_text(encoding="utf-8")
        payload = (
            yaml.safe_load(content)
            if path.suffix.casefold() in {".yaml", ".yml"}
            else json.loads(content)
        )
        return MetadataOverrides.model_validate(payload or {})
    except (OSError, ValueError, TypeError, ValidationError, yaml.YAMLError) as exc:
        raise OntologyImportError(
            "本地覆盖配置无效",
            details={"path": str(path), "reason": type(exc).__name__},
        ) from exc


def apply_metadata_overrides(
    draft: TabularMetadataDraft, overrides: MetadataOverrides
) -> TabularMetadataDraft:
    fields_by_key = {field.physical_name.casefold(): field for field in draft.fields}
    override_keys = {name.casefold(): name for name in overrides.fields}
    unknown = sorted(
        (override_keys[key] for key in override_keys if key not in fields_by_key),
        key=lambda value: (value.casefold(), value),
    )
    if unknown:
        raise OntologyImportError(
            "覆盖配置引用了未知字段",
            details={"fields": unknown},
        )

    temporal_policy = overrides.temporal_policy
    if temporal_policy is not None:
        matched_field = fields_by_key.get(temporal_policy.field.casefold())
        if matched_field is None:
            raise OntologyImportError(
                "时间分区策略引用了未知字段",
                details={"field": temporal_policy.field},
            )
        temporal_policy = temporal_policy.model_copy(update={"field": matched_field.physical_name})

    updated: list[FieldMetadata] = []
    for field in draft.fields:
        source_name = override_keys.get(field.physical_name.casefold())
        override = overrides.fields[source_name] if source_name is not None else None
        if override is None:
            updated.append(field)
            continue
        changes = override.model_dump(exclude_none=True)
        updated.append(field.model_copy(update=changes))
    return draft.model_copy(update={"fields": tuple(updated), "temporal_policy": temporal_policy})
