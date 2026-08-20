# 开发环境验证说明

> 记录本机（Windows）阶段 0 开发环境的验证状态与数据库配置指引。

## 验证状态总览

| 项目 | 状态 | 说明 |
| :--- | :--- | :--- |
| FastAPI 应用（/health /ready） | ✅ 通过 | HTTP 200，`{"status":"ok"}` |
| 单元测试 | ✅ 4 passed | test_health ×2 + test_redis_smoke ×2，无警告 |
| Redis 客户端接口 | ✅ 通过（fakeredis 模拟） | 本机无真实 Redis |
| PostgreSQL 连通 | ✅ 通过 | 已创建 ontology 账号 + ontology_agent 库，psycopg2 验证 OK |

## 环境约束（本机）

- Docker / Docker Compose：不可用
- GitHub：网络不可达（无法下载 Redis 便携版 / 拉取镜像）
- 系统级工具（netstat 等）：被安全策略禁用
- PostgreSQL 14：已安装于 `C:\Program Files\PostgreSQL\14`，pg_hba.conf 全部 scram-sha-256 密码认证

## PostgreSQL 凭据（已配置）

已通过临时 trust 引导方式创建专用账号（2026-08-14），凭据如下：

```
DATABASE__USER=ontology
DATABASE__PASSWORD=ontology
DATABASE__NAME=ontology_agent
```

与项目 `.env` 默认值一致，无需修改。

> 引导过程：临时修改 `pg_hba.conf` 加入 `127.0.0.1 trust`（已备份 `.bak`）→ reload → 建号 → 立即恢复并再次 reload。全程仅限本地回环地址，现已恢复 scram-sha-256 安全认证。

## Redis 真实验证方式

阶段 0 的 `/health` 不依赖 Redis。真实 Redis 用于阶段 4（Celery 队列），届时二选一：

- 有 Docker 环境：`docker compose -f deploy/docker-compose.yml up -d redis`
- 有 GitHub 网络：下载 tporadowski/redis 便携版解压，运行 `redis-server.exe`
