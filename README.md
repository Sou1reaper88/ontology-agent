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

## Windows 本地启动

本项目的本地前端使用 Vite 5，要求 **Node.js 18+**，推荐安装 Node.js 20 LTS。后端与前端分别监听 `8001` 和 `5199` 端口。

### 首次准备

在项目根目录执行：

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Set-Location .\frontend
npm.cmd install
Set-Location ..
```

`.env` 至少需要保留本体管理存储配置；不要将 API Key 提交到 Git：

```dotenv
ONTOLOGY__MANAGEMENT_ROOT=D:/Projects/ontology-agent-data/ontology-management
ONTOLOGY__MANAGEMENT_WORKSPACE=evaluation
```

启动前可检查环境：

```powershell
node --version       # 应为 v18+，推荐 v20+
.\.venv\Scripts\python.exe --version
```

### 一键启动

在实际项目根目录 `D:\Projects\ontology-agent` 双击 `start.bat`，或在 PowerShell 执行：

```powershell
.\start.bat
```

该脚本会打开两个窗口：后端 `http://127.0.0.1:8001` 与前端 `http://127.0.0.1:5199`。访问 `http://127.0.0.1:5199/chat` 使用智能取数，访问 `http://127.0.0.1:5199/ontology` 管理本体。

> 不要运行 `.worktrees\...` 下的 `start.bat`；那里是开发工作树，默认不会包含你的 `.env` 与 `.venv`。

### 手动启动

若需要查看单独服务的日志，可使用两个 PowerShell 窗口。

窗口一：后端。

```powershell
Set-Location D:\Projects\ontology-agent
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8001
```

窗口二：前端。

```powershell
Set-Location D:\Projects\ontology-agent\frontend
npm.cmd run dev -- --host 127.0.0.1 --port 5199 --strictPort
```

服务启动后，执行下列检查。本体字段必须为 `ok`，否则智能体不会加载已发布本体包：

```powershell
Invoke-WebRequest http://127.0.0.1:8001/ready | Select-Object -ExpandProperty Content
```

预期结果包含：

```json
{"status":"ok","database":"ok","ontology":"ok"}
```

### 停止与排障

停止服务：

```powershell
.\stop.bat
```

- 出现 `Vite 5 needs Node.js 18+` 或 `crypto.getRandomValues is not a function`：安装 Node.js 20 LTS，并重新打开 PowerShell。
- `/ready` 返回 `ontology_management_configuration_error`：检查 `.env` 中 `ONTOLOGY__MANAGEMENT_ROOT` 是否存在且可访问。
- `/ready` 返回 `ontology_parse_error`：已发布本体包无法读取，进入本体管理页面检查活动版本。
- 端口已被占用：先运行 `stop.bat`，确认后再运行 `start.bat`。

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
