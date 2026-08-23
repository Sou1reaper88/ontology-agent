# ontology-agent

企业级本体驱动 HiveSQL 编译器取数智能体。

基于本体元数据（TTL）+ 用户外部表信息 + 系统时间，严格遵循技术规范生成 HiveSQL，并支持执行取数。具备权限管理、审计日志、多用户并发、表级数据隔离等企业级特性。

## 架构

详见 [设计文档](docs/designs/2026-08-05-ontology-agent-design.md)。

## 文档

- [分阶段实施计划](docs/plans/2026-08-06-ontology-agent-implementation-plan.md)
- [部署说明](docs/deployment.md)
- [开发环境验证说明](docs/dev-environment.md)
- [生产就绪检查清单](deploy/PRODUCTION_CHECKLIST.md)

## 快速开始

### 环境要求
- Python >= 3.11
- Docker / Docker Compose（用于 PostgreSQL + Redis）

### 1. 启动依赖服务
```bash
docker compose -f deploy/docker-compose.yml up -d
```

### 2. 安装依赖
```bash
pip install -e ".[dev]"
```

### 3. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env 填入 LLM API Key、本体平台地址等
```

### 4. 启动应用
```bash
uvicorn api.main:app --reload
```

访问 http://localhost:8000/health

## 项目结构

```
ontology-agent/
├── api/        FastAPI 路由
├── agent/      LangGraph 编排
├── tools/      工具适配层(本体平台API + 商业LLM)
├── executor/   Celery + Hive 执行器
├── auth/       认证 + 权限
├── audit/      审计中间件
├── models/     ORM 模型(SQLAlchemy)
├── schemas/    Pydantic 模型
├── config/     配置(settings.py + yaml)
├── frontend/   React 前端
├── tests/      测试
├── deploy/     Docker + K8s
└── docs/       文档
```

## 开发

```bash
ruff check .
black .
pytest
```

## 本体包开发

本体包编辑流程见 [Protégé 本体编辑指南](docs/ontology-authoring.md)。本里程碑中的 `OntologyResolver` 是只读的 Python 边界；现有 Agent 仍走 legacy path，尚未切换到该 Resolver。

```powershell
python -m ontology_core init D:\path\to\private-package --package-id private.package --base-uri https://example.invalid/private/
python -m ontology_core validate D:\path\to\private-package
python -m ontology_core inspect D:\path\to\private-package
```

## 实施计划

详见 [分阶段实施计划](docs/plans/2026-08-06-ontology-agent-implementation-plan.md)。
