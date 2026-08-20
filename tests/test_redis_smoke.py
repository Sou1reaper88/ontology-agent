"""Redis 客户端接口冒烟测试。

本机无真实 Redis（GitHub 不可达无法下载便携版、Docker 不可用），
用 fakeredis 模拟 Redis 协议，验证 redis-py 客户端接口可用。
真实 Redis 连通性留待有 Docker/GitHub 环境时验证。
"""

from __future__ import annotations

import fakeredis
import redis


def test_redis_interface_smoke() -> None:
    """用 fakeredis 验证 redis-py 基础接口（set/get/expire/delete）。"""
    r: redis.Redis = fakeredis.FakeStrictRedis()
    r.set("smoke:key", "ok")
    assert r.get("smoke:key") == b"ok"
    r.expire("smoke:key", 60)
    assert r.ttl("smoke:key") > 0
    r.delete("smoke:key")
    assert r.get("smoke:key") is None


def test_redis_ping_interface() -> None:
    """验证 ping 命令接口。"""
    r: redis.Redis = fakeredis.FakeStrictRedis()
    assert r.ping() is True
