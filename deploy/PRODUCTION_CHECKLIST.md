# 生产就绪检查清单

> 对齐设计文档 §7.5。上线前逐项验收。

## 应用可用性

- [ ] `/health` 存活探针返回 200
- [ ] `/ready` 就绪探针返回 `database: ok`
- [ ] 优雅关闭（SIGTERM 信号处理，uvicorn 默认支持）

## 配置与安全

- [ ] 配置外部化：非敏感走 ConfigMap（`deploy/k8s/configmap.yaml`），敏感走 Secret（`deploy/k8s/secret.yaml`）
- [ ] `SECRET_KEY` 为强随机值（生产 `python -c "import secrets; print(secrets.token_hex(32))"`）
- [ ] `LLM__API_KEY` 不落入 git（`.env` 已被 `.gitignore` 排除）
- [ ] HTTPS/TLS（Ingress 配置证书）

## 可观测性

- [ ] Prometheus 抓取 `/metrics` 正常（http_requests_total 等指标可见）
- [ ] 结构化 JSON 日志输出（`config/logging.py`），可接入 Loki/ELK
- [ ] 告警规则：失败率、队列积压、Hive 不可用（AlertManager）

## 数据

- [ ] Alembic 迁移在部署时执行（K8s migrate Job / initContainer）
- [ ] PostgreSQL 定期备份（`deploy/k8s/migrate-and-backup.yaml` CronJob，每日 02:00）
- [ ] 结果存储目录（大结果文件）挂载持久卷

## 资源与治理

- [ ] 请求限流（网关/Ingress 层）
- [ ] 资源请求/限制（backend/worker Deployment 已配置）
- [ ] 审计日志定期归档策略

## 数据库初始化（一次性）

```bash
alembic upgrade head
python -m scripts.seed   # 角色×2 + admin 账号 + 示例表权限
```

## 验收记录

| 检查项 | 状态 | 备注 |
| :--- | :--- | :--- |
| /health | ☐ | |
| /ready | ☐ | |
| /metrics | ☐ | |
| 迁移 | ☐ | |
| 种子数据 | ☐ | |
| 备份 CronJob | ☐ | |
