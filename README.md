# ontology-agent

本体驱动的 HiveSQL 取数智能体。

基于已发布 RDF 本体元数据、用户需求和系统时间生成 HiveSQL 建表脚本。智能取数链路只生成脚本，不执行脚本；保留权限管理、审计日志与多用户会话能力。

## 架构

默认链路为：大模型理解对话并选择生成工具 → 检索已发布本体 → 大模型直接编写 SQL 并按需查询元数据、调用校验工具 → Python 静态校验 → 输出一份脚本。Python 不再要求关系代数计划或重新渲染 SQL。没有登记关系或口径时，模型仍可结合真实表字段描述及用户补充推断，并展示假设；不自动写回本体。

模型可以使用 JOIN、NOT EXISTS、UNION、窗口函数、HAVING 等 Hive 写法。CTE 未被禁止时可用；会话模型识别禁用 CTE 后将限制传给生成工具，最终通过 AST 检查。脚本包含临时表 DROP/CREATE 配对步骤，不生成末尾清理、不执行、不运行影子 SQL。基础扫描必须给出有限分区范围；明确账期优先，默认日分区为系统日期减两天，月分区为上一个自然月。

`config/settings.yaml` 的 `sql_pipeline` 默认为 `llm`；原 `canonical` 值是新默认链路的兼容别名。`legacy` 仍可显式选择旧图，但失败不会自动回退。旧关系计划编译模块暂留作独立兼容代码，不参与默认生成。

实施记录见 [模型编写 SQL 改造计划](docs/superpowers/plans/2026-09-14-llm-sql-authoring.md)。静态校验不证明业务口径正确；用户明确指定的外部表字段未经本体验证。评测中心的多步骤比较仍待升级，本次不新增框架。

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
├── agent/      自然对话工具编排 + SQL 生成服务（旧图使用 LangGraph）
├── ontology_core/ RDF 本体、元数据证据、语义校验与统一关系编译
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

本体包编辑流程见 [Protégé 本体编辑指南](docs/ontology-authoring.md)。前台本体管理支持元数据草稿编辑、校验和不可变版本发布；智能取数从活动版本检索真实对象与字段，并通过只读 Python 校验及统一关系编译边界生成脚本。

```powershell
python -m ontology_core init D:\path\to\private-package --package-id private.package --base-uri https://example.invalid/private/
python -m ontology_core validate D:\path\to\private-package
python -m ontology_core inspect D:\path\to\private-package
```

## 实施计划

详见 [分阶段实施计划](docs/plans/2026-08-06-ontology-agent-implementation-plan.md)。
