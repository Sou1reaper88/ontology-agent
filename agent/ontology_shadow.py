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


class OntologyShadowResult(FrozenModel):
    status: Literal["generated", "no_match", "ambiguous", "unsupported", "unavailable"]
    ontology_sql: str | None = None
    summary: str
    diff: SqlDiff
    evidence: OntologyEvidence
    package: ShadowPackage | None = None


class _SnapshotRuntime(Protocol):
    def snapshot(self) -> OntologySnapshot: ...


class OntologyRuntime:
    def __init__(self, package_path: str | Path) -> None:
        self._package_path = Path(package_path)
        self._lock = threading.RLock()
        self._snapshot: OntologySnapshot | None = None

    def snapshot(self) -> OntologySnapshot:
        with self._lock:
            if self._snapshot is None:
                repository = OntologyRepository()
                repository.publish(self._package_path)
                self._snapshot = repository.current()
            return self._snapshot


def _normalize_sql(value: str | None) -> str:
    return " ".join((value or "").strip().rstrip(";").split()).casefold()


def _tables(value: str | None) -> tuple[str, ...]:
    return tuple(
        sorted({match.replace('"', "") for match in _TABLE_REFERENCE.findall(value or "")})
    )


def _empty_result(
    status: Literal["no_match", "ambiguous", "unsupported", "unavailable"],
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

    def preview(self, query: str, legacy_sql: str | None) -> OntologyShadowResult:
        if not self._enabled:
            return _empty_result("unavailable", "本体 SQL 影子模式未启用", legacy_sql)
        if self._runtime is None:
            return _empty_result("unavailable", "尚未配置外部本体包", legacy_sql)
        try:
            snapshot = self._runtime.snapshot()
            plan = OntologyPlanner(OntologyResolver(snapshot)).plan(query)
            dialect = plan.data_source.dialect or plan.data_source.platform_type
            compiled = self._registry.get(dialect).compile(plan)
            changed = _normalize_sql(legacy_sql) != _normalize_sql(compiled.sql)
            summary = "本体 SQL 与现有 SQL 存在差异" if changed else "本体 SQL 与现有 SQL 一致"
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
                    concepts=(plan.concept.short_name,),
                    properties=tuple(item.semantic.short_name for item in plan.selections),
                    rules=tuple(item.short_name for item in plan.rules),
                    data_sources=(plan.data_source.short_name,),
                    mappings=tuple(
                        dict.fromkeys(
                            (
                                plan.object_binding.short_name,
                                *(item.binding.short_name for item in plan.property_bindings),
                            )
                        )
                    ),
                ),
                package=ShadowPackage(
                    package_id=snapshot.info.package_id,
                    version=snapshot.info.version,
                    sha256=snapshot.info.sha256[:12],
                ),
            )
        except NoMatchingConceptError:
            return _empty_result("no_match", "当前本体包未匹配到查询概念", legacy_sql)
        except AmbiguousQueryConceptError:
            return _empty_result("ambiguous", "查询命中了多个同等本体概念", legacy_sql)
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
    runtime = OntologyRuntime(package_path) if package_path.strip() else None
    return OntologyShadowService(runtime=runtime, enabled=enabled)


def get_ontology_shadow_service() -> OntologyShadowService:
    return _configured_service(
        settings.ontology.package_path,
        settings.ontology.shadow_enabled,
    )
