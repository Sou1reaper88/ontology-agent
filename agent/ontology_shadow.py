from __future__ import annotations

import logging
import re
import threading
from functools import lru_cache
from pathlib import Path
from typing import Literal, Protocol

from config.settings import settings
from ontology_core.compiler import CompilerRegistry
from ontology_core.errors import (
    AmbiguousQueryConceptError,
    NoMatchingConceptError,
    OntologyCompileError,
    OntologyError,
    PackageNotFoundError,
    TemporalIntentError,
    UnsupportedQueryPlanError,
)
from ontology_core.models import FrozenModel
from ontology_core.planner import OntologyPlanner
from ontology_core.repository import OntologyRepository, OntologySnapshot
from ontology_core.resolver import OntologyResolver

logger = logging.getLogger(__name__)

_TABLE_REFERENCE = re.compile(
    r"\b(?:from|join)\s+([A-Za-z_\"][A-Za-z0-9_$\"]*(?:\.[A-Za-z_\"][A-Za-z0-9_$\"]*)?)",
    re.IGNORECASE,
)


class SqlDiff(FrozenModel):
    changed: bool
    legacy_tables: tuple[str, ...] = ()
    ontology_tables: tuple[str, ...] = ()


class OntologyEvidence(FrozenModel):
    concepts: tuple[str, ...] = ()
    properties: tuple[str, ...] = ()
    rules: tuple[str, ...] = ()
    data_sources: tuple[str, ...] = ()
    mappings: tuple[str, ...] = ()


class ShadowPackage(FrozenModel):
    package_id: str
    version: str
    sha256: str


class RuntimeHealth(FrozenModel):
    status: Literal["ok", "degraded"]
    package_id: str | None = None
    version: str | None = None
    sha256: str | None = None
    reason: str | None = None


class TemporalEvidence(FrozenModel):
    partition_field: str
    grain: str
    policy_source: Literal["ontology"] = "ontology"
    system_time: str
    user_time: str | None = None
    source: str
    default_strategy: str
    resolved_start: str
    resolved_end: str
    safety_status: Literal["bounded"] = "bounded"
    explanation: str


class OntologyShadowResult(FrozenModel):
    status: Literal[
        "generated",
        "no_match",
        "ambiguous",
        "unsupported",
        "unavailable",
        "clarification_required",
    ]
    ontology_sql: str | None = None
    summary: str
    diff: SqlDiff
    evidence: OntologyEvidence
    package: ShadowPackage | None = None
    temporal_decision: TemporalEvidence | None = None


class _SnapshotRuntime(Protocol):
    def snapshot(self) -> OntologySnapshot: ...


class OntologyRuntime:
    def __init__(self, initial_package_path: str | Path | None = None) -> None:
        self._lock = threading.RLock()
        self._snapshot = self._load_explicit(initial_package_path) if initial_package_path else None
        self._degraded_reason = None if self._snapshot is not None else "not_loaded"

    @staticmethod
    def _load_explicit(package_path: str | Path) -> OntologySnapshot:
        repository = OntologyRepository()
        repository.publish(package_path)
        return repository.current()

    def install(self, snapshot: OntologySnapshot) -> None:
        if not isinstance(snapshot, OntologySnapshot):
            raise TypeError("snapshot must be OntologySnapshot")
        with self._lock:
            self._snapshot = snapshot

    def _mark_degraded(self, reason: str) -> None:
        with self._lock:
            self._snapshot = None
            self._degraded_reason = reason

    def snapshot(self) -> OntologySnapshot:
        with self._lock:
            if self._snapshot is None:
                raise PackageNotFoundError("当前没有有效本体快照")
            return self._snapshot

    def health(self) -> RuntimeHealth:
        with self._lock:
            if self._snapshot is None:
                return RuntimeHealth(status="degraded", reason=self._degraded_reason)
            return RuntimeHealth(
                status="ok",
                package_id=self._snapshot.info.package_id,
                version=self._snapshot.info.version,
                sha256=self._snapshot.info.sha256,
            )


@lru_cache(maxsize=1)
def get_ontology_runtime() -> OntologyRuntime:
    package_path = settings.ontology.package_path.strip()
    return OntologyRuntime(package_path or None)


def _normalize_sql(value: str | None) -> str:
    return " ".join((value or "").strip().rstrip(";").split()).casefold()


def _tables(value: str | None) -> tuple[str, ...]:
    return tuple(
        sorted({match.replace('"', "") for match in _TABLE_REFERENCE.findall(value or "")})
    )


def _empty_result(
    status: Literal[
        "no_match",
        "ambiguous",
        "unsupported",
        "unavailable",
        "clarification_required",
    ],
    summary: str,
    legacy_sql: str | None,
) -> OntologyShadowResult:
    return OntologyShadowResult(
        status=status,
        summary=summary,
        diff=SqlDiff(changed=False, legacy_tables=_tables(legacy_sql)),
        evidence=OntologyEvidence(),
    )


def unavailable_shadow_result(legacy_sql: str | None) -> OntologyShadowResult:
    return _empty_result("unavailable", "本体影子链路当前不可用", legacy_sql)


class OntologyShadowService:
    def __init__(
        self,
        runtime: _SnapshotRuntime | None,
        *,
        enabled: bool = True,
        registry: CompilerRegistry | None = None,
    ) -> None:
        self._runtime = runtime
        self._enabled = enabled
        self._registry = registry or CompilerRegistry.default()

    def preview(
        self,
        query: str,
        legacy_sql: str | None,
        *,
        system_time: str | None = None,
    ) -> OntologyShadowResult:
        if not self._enabled:
            return _empty_result("unavailable", "本体 SQL 影子模式未启用", legacy_sql)
        if self._runtime is None:
            return _empty_result("unavailable", "尚未配置外部本体包", legacy_sql)
        try:
            snapshot = self._runtime.snapshot()
            plan = OntologyPlanner(OntologyResolver(snapshot)).plan(
                query,
                system_time=system_time,
            )
            dialect = plan.data_source.dialect or plan.data_source.platform_type
            compiled = self._registry.get(dialect).compile(plan)
            changed = _normalize_sql(legacy_sql) != _normalize_sql(compiled.sql)
            summary = "本体 SQL 与现有 SQL 存在差异" if changed else "本体 SQL 与现有 SQL 一致"
            evidence_property_uris = {
                *(item.semantic.uri for item in plan.selections),
                *(uri for rule in plan.rules for uri in rule.property_uris),
                *(item.property.semantic.uri for item in plan.filters),
            }
            evidence_bindings = tuple(
                item
                for item in plan.property_bindings
                if item.semantic.uri in evidence_property_uris
            )
            temporal_evidence = None
            temporal_decision = plan.temporal_decisions[0] if plan.temporal_decisions else None
            if temporal_decision is not None:
                partition_binding = next(
                    item
                    for item in plan.property_bindings
                    if item.semantic.uri == temporal_decision.partition_property_uri
                )
                temporal_evidence = TemporalEvidence(
                    partition_field=str(partition_binding.binding.field_name),
                    grain=temporal_decision.grain.value,
                    system_time=temporal_decision.system_date.isoformat(),
                    user_time=temporal_decision.matched_text,
                    source=temporal_decision.source.value,
                    default_strategy=temporal_decision.default_strategy.value,
                    resolved_start=temporal_decision.resolved_start,
                    resolved_end=temporal_decision.resolved_end,
                    explanation=temporal_decision.explanation,
                )
            return OntologyShadowResult(
                status="generated",
                ontology_sql=compiled.sql,
                summary=summary,
                diff=SqlDiff(
                    changed=changed,
                    legacy_tables=_tables(legacy_sql),
                    ontology_tables=compiled.tables,
                ),
                evidence=OntologyEvidence(
                    concepts=tuple(item.short_name for item in plan.concepts),
                    properties=tuple(item.semantic.short_name for item in plan.selections),
                    rules=tuple(item.short_name for item in plan.rules),
                    data_sources=(plan.data_source.short_name,),
                    mappings=tuple(
                        dict.fromkeys(
                            (
                                *(item.binding.short_name for item in plan.objects),
                                *(item.binding.short_name for item in evidence_bindings),
                            )
                        )
                    ),
                ),
                package=ShadowPackage(
                    package_id=snapshot.info.package_id,
                    version=snapshot.info.version,
                    sha256=snapshot.info.sha256[:12],
                ),
                temporal_decision=temporal_evidence,
            )
        except NoMatchingConceptError:
            return _empty_result("no_match", "当前本体包未匹配到查询概念", legacy_sql)
        except AmbiguousQueryConceptError:
            return _empty_result("ambiguous", "查询命中了多个同等本体概念", legacy_sql)
        except TemporalIntentError as exc:
            reason = exc.details.get("reason")
            if reason == "conflicting_partition_time":
                return _empty_result(
                    "clarification_required",
                    "需求中存在多个冲突账期，请确认最终账期",
                    legacy_sql,
                )
            if reason == "unbounded_time":
                return _empty_result(
                    "clarification_required",
                    "需求未限定安全时间范围，请明确账期",
                    legacy_sql,
                )
            return _empty_result("unsupported", "时间条件无法安全解析", legacy_sql)
        except (UnsupportedQueryPlanError, OntologyCompileError):
            return _empty_result("unsupported", "当前本体映射不足以生成安全 SQL", legacy_sql)
        except OntologyError as exc:
            logger.warning("本体影子运行失败: %s", type(exc).__name__)
            return _empty_result("unavailable", "本体影子链路当前不可用", legacy_sql)
        except Exception as exc:
            logger.warning("本体影子运行异常: %s", type(exc).__name__)
            return _empty_result("unavailable", "本体影子链路当前不可用", legacy_sql)


@lru_cache(maxsize=8)
def _configured_service(package_path: str, enabled: bool) -> OntologyShadowService:
    return OntologyShadowService(runtime=get_ontology_runtime(), enabled=enabled)


def get_ontology_shadow_service() -> OntologyShadowService:
    return _configured_service(
        settings.ontology.package_path,
        settings.ontology.shadow_enabled,
    )
