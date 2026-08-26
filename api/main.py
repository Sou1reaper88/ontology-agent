"""FastAPI 应用入口。

阶段 0：提供 /health 与 /ready 健康检查。
后续阶段逐步接入路由、权限、审计、Agent 编排、执行等模块。
"""

from __future__ import annotations

from fastapi import FastAPI
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from api.routes import (
    audit,
    auth,
    conversation,
    execute,
    ontology,
    ontology_packages,
    permissions,
    roles,
    sql,
    users,
)
from audit.middleware import AuditMiddleware
from config.logging import setup_logging
from config.settings import settings

setup_logging()

app = FastAPI(
    title=settings.app_name,
    description="企业级本体驱动 HiveSQL 编译器取数智能体",
    version="0.5.0",
)

app.add_middleware(AuditMiddleware)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(roles.router)
app.include_router(permissions.router)
app.include_router(execute.router)
app.include_router(conversation.router)
app.include_router(sql.router)
app.include_router(ontology.router)
app.include_router(ontology_packages.router)
app.include_router(audit.router)


@app.get("/health", tags=["monitor"])
async def health() -> dict[str, str]:
    """存活探针：进程存活即返回 ok。"""
    return {"status": "ok"}


@app.get("/ready", tags=["monitor"])
async def ready() -> dict[str, str]:
    """就绪探针：数据库与已发布本体的可用性独立报告。"""
    database = "ok"
    try:
        from models.base import engine

        with engine.connect():
            pass
    except Exception:
        database = "unavailable"
    ontology = "ok"
    try:
        from api.routes.ontology_packages import get_management_service

        health = get_management_service().recover(settings.ontology.management_workspace)
        if health.status != "ok":
            ontology = "degraded"
    except Exception:
        ontology = "degraded"
    return {
        "status": "ok" if database == "ok" and ontology == "ok" else "degraded",
        "env": settings.env,
        "database": database,
        "ontology": ontology,
    }


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Prometheus 抓取端点。"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
