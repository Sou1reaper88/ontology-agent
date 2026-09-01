"""Managed ontology runtime recovery at application startup."""

from __future__ import annotations

from pathlib import Path

from agent.ontology_shadow import OntologyRuntime, RuntimeHealth
from ontology_core.errors import OntologyError
from ontology_core.management.service import OntologyManagementService


class ManagedRuntimeBootstrapError(OntologyError):
    code = "ontology_runtime_bootstrap_failed"

    def __init__(self, *, reason: str) -> None:
        super().__init__("本体运行时恢复失败", details={"reason": reason})


def recover_managed_runtime(
    *,
    root: str | Path,
    workspace_id: str,
    repository_root: Path,
    runtime: OntologyRuntime,
) -> RuntimeHealth:
    try:
        service = OntologyManagementService(
            Path(root),
            repository_root=repository_root,
            runtime=runtime,
        )
        health = service.recover(workspace_id)
    except OntologyError as error:
        raise ManagedRuntimeBootstrapError(reason=error.code) from error
    if health.status != "ok":
        raise ManagedRuntimeBootstrapError(reason=health.reason or "recovery_failed")
    return health
