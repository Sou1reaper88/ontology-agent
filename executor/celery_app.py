"""Celery 应用配置。

本机无 Redis（GitHub 不可达无法安装），使用 eager 模式同步执行（不需要 broker）；
生产环境设置 REDIS_AVAILABLE=True 并使用 redis broker 即切换为异步队列。
"""

from __future__ import annotations

from celery import Celery

from config.settings import settings

# 本机无真实 Redis；生产环境改为 True 并确保 Redis 可用
REDIS_AVAILABLE = False

_broker = settings.redis.url if REDIS_AVAILABLE else "memory://"
_backend = settings.redis.url if REDIS_AVAILABLE else "cache+memory://"

celery_app = Celery(
    "ontology_agent",
    broker=_broker,
    backend=_backend,
    include=["executor.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_always_eager=not REDIS_AVAILABLE,  # 无 Redis 时同步执行
    task_eager_propagates=True,  # eager 模式抛异常，便于测试发现错误
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
