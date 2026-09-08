"""FastAPI 应用入口。

阶段 0：提供 /health 与 /ready 健康检查。
后续阶段逐步接入路由、权限、审计、Agent 编排、执行等模块。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from agent.ontology_shadow import RuntimeHealth, get_ontology_runtime
from api.routes import (
    audit,
    auth,
    conversation,
    evaluations,
    execute,
    ontology,
    ontology_packages,
    permissions,
    prompts,
    roles,
    sql,
    users,
)
from audit.middleware import AuditMiddleware
from config.logging import setup_logging
from config.settings import settings
from ontology_core.management.bootstrap import (
    ManagedRuntimeBootstrapError,
    recover_managed_runtime,
)

setup_logging()


def bootstrap_runtime() -> RuntimeHealth:
    """Recover the durable active ontology once during application startup."""
    return recover_managed_runtime(
        root=settings.ontology.management_root,
        workspace_id=settings.ontology.management_workspace,
        repository_root=Path(__file__).resolve().parents[1],
        runtime=get_ontology_runtime(),
    )


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Install the active managed ontology snapshot before serving requests."""
    try:
        application.state.ontology_bootstrap = bootstrap_runtime()
    except ManagedRuntimeBootstrapError as error:
        application.state.ontology_bootstrap = RuntimeHealth(
            status="degraded",
            reason=str(error.details.get("reason", error.code)),
        )
    yield


def get_runtime_health(application: FastAPI) -> RuntimeHealth:
    """Prefer live runtime health and retain the sanitized startup reason."""
    current = get_ontology_runtime().health()
    if current.status == "ok":
        return current
    startup = getattr(application.state, "ontology_bootstrap", current)
    if current.reason == "not_loaded" and startup.status == "degraded":
        return startup
    return current


app = FastAPI(
    title=settings.app_name,
    description="企业级本体驱动 HiveSQL 编译器取数智能体",
    version="0.5.0",
    lifespan=lifespan,
)

app.add_middleware(AuditMiddleware)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(roles.router)
app.include_router(permissions.router)
app.include_router(execute.router)
app.include_router(evaluations.router)
app.include_router(conversation.router)
app.include_router(prompts.router)
app.include_router(sql.router)
app.include_router(ontology.router)
app.include_router(ontology_packages.router)
app.include_router(audit.router)


@app.get("/health", tags=["monitor"])
async def health() -> dict[str, str]:
    """存活探针：进程存活即返回 ok。"""
    return {"status": "ok"}


@app.get("/ready", tags=["monitor"])
async def ready(request: Request) -> dict[str, str]:
    """就绪探针：数据库与已发布本体的可用性独立报告。"""
    database = "ok"
    try:
        from models.base import engine

        with engine.connect():
            pass
    except Exception:
        database = "unavailable"
    runtime_health = get_runtime_health(request.app)
    ontology = runtime_health.status
    payload = {
        "status": "ok" if database == "ok" and ontology == "ok" else "degraded",
        "env": settings.env,
        "database": database,
        "ontology": ontology,
    }
    if ontology == "degraded":
        payload["ontology_reason"] = runtime_health.reason or "not_loaded"
    return payload


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Prometheus 抓取端点。"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
