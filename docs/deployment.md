# 部署说明

## 1. 环境要求

- Python >= 3.11（后端）
- Node >= 20（前端构建）
- PostgreSQL 16、Redis 7（或 Docker）
- K8s（生产）

## 2. 环境变量（.env）

参考 `.env.example`，生产必须配置：

| 变量 | 必填 | 说明 |
| :--- | :--- | :--- |
| `SECRET_KEY` | ✅ | JWT 签名密钥，生产用强随机值 |
| `LLM__API_KEY` | ✅ | 商业 LLM API Key |
| `DATABASE__PASSWORD` | ✅ | 数据库密码 |
| `ENV` | — | dev / staging / prod |

## 3. Docker Compose（开发/小规模）

```bash
# 仅基础设施（PostgreSQL + Redis）
docker compose -f deploy/docker-compose.yml up -d

# 完整编排（后端 + Worker + 前端 + 基础设施）
docker compose -f deploy/docker-compose.full.yml up -d

# 初始化数据库 + 种子数据
docker exec ontology-backend alembic upgrade head
docker exec ontology-backend python -m scripts.seed
```

前端访问 `http://localhost:8080`，后端 API `http://localhost:8000`。

> 生产请将 `executor/celery_app.py` 的 `REDIS_AVAILABLE` 改为 `True`（当前无 Redis 时走 eager 同步模式）。

## 4. Kubernetes（生产）

```bash
kubectl create namespace ontology

# 1) 创建密钥（用真实值覆盖 secret.yaml）
kubectl create secret generic ontology-agent-secret -n ontology \
  --from-literal=DATABASE__PASSWORD=<db-password> \
  --from-literal=SECRET_KEY=<jwt-secret> \
  --from-literal=LLM__API_KEY=<llm-key>

# 2) 应用资源配置
kubectl apply -f deploy/k8s/configmap.yaml
kubectl apply -f deploy/k8s/statefulset-postgres-redis.yaml
kubectl apply -f deploy/k8s/migrate-and-backup.yaml   # 迁移 Job + 备份 CronJob

# 3) 等待 postgres/redis 就绪后应用应用
kubectl apply -f deploy/k8s/deployment-backend.yaml
kubectl apply -f deploy/k8s/deployment-worker.yaml
kubectl apply -f deploy/k8s/deployment-frontend.yaml
kubectl apply -f deploy/k8s/ingress.yaml
```

镜像构建（本地）：

```bash
docker build -t ontology-agent-backend -f deploy/Dockerfile .
docker build -t ontology-agent-frontend -f frontend/Dockerfile frontend/
```

## 5. 监控

- `/metrics` 端点暴露 Prometheus 指标（http_requests_total / http_request_duration_seconds / llm_call_duration_seconds / query_execution_duration_seconds）
- 日志为结构化 JSON（`config/logging.py`），可接入 Loki / ELK

## 6. 生产上线步骤

1. 修改 `secret.yaml` 或 `kubectl create secret` 注入真实密钥
2. 执行迁移 Job（`alembic upgrade head`）
3. 运行种子脚本（`python -m scripts.seed`）
4. 验证 `/health`、`/ready`、`/metrics`
5. 修改 Ingress 域名与 TLS 证书
6. 按 [生产就绪检查清单](PRODUCTION_CHECKLIST.md) 逐项验收
