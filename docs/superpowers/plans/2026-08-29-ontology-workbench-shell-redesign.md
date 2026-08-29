# Ontology Workbench Shell Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将本体包管理页改造成具有状态概览、资产统计和六阶段导航的工作台，同时完整复用既有业务面板和 API 行为。

**Architecture:** 新增纯 TypeScript 工作台模型，统一阶段键、默认选择和阶段摘要；`OntologyWorkbench` 保留加载、刷新、冲突处理与面板组装职责，并改为一次渲染一个活动阶段。专用 React 外壳组件和 CSS 只负责展示，不发起业务请求。

**Tech Stack:** React 18、TypeScript 5、Ant Design 5、Vite 5、CSS

## Global Constraints

- 不修改后端接口、本体数据模型、草稿修订协议、导入、诊断或发布行为。
- 不重写六个现有业务面板的内部表单。
- 不新增 UI 或测试依赖。
- 空草稿默认进入导入阶段，有对象时默认进入对象与字段阶段。
- 窄屏阶段导航可横向滚动，并可访问全部阶段。
- 完成后自动提交 Git，不推送或合并；保持本地前后端服务供用户验收。

---

## File Map

- Create `frontend/src/features/ontology-package/workbenchModel.ts`: 阶段类型、配置、默认阶段和摘要纯函数。
- Create `frontend/tests/ontology-workbench-model.test.ts`: 默认选择及摘要契约。
- Create `frontend/src/features/ontology-package/WorkbenchShell.tsx`: 状态栏、资产概览和阶段导航展示。
- Create `frontend/src/features/ontology-package/ontology-workbench.css`: 工作台专用布局与响应式样式。
- Modify `frontend/src/features/ontology-package/OntologyWorkbench.tsx`: 保留数据编排，接入阶段选择并一次展示一个面板。
- Modify `docs/project-journal/2026-08.md`: 记录难点、边界、验证和简历素材。

---

### Task 1: 建立工作台阶段模型契约

**Files:**
- Create: `frontend/tests/ontology-workbench-model.test.ts`
- Create: `frontend/src/features/ontology-package/workbenchModel.ts`

**Interfaces:**
- Produces: `WorkbenchStage = "import" | "objects" | "relations" | "temporal" | "diagnostics" | "versions"`。
- Produces: `WORKBENCH_STAGES`，包含稳定顺序、编号、标题和说明。
- Produces: `initialWorkbenchStage(objectCount: number): WorkbenchStage`。
- Produces: `workbenchStageSummary(stage, overview, versionCount): string`。

- [ ] **Step 1: 写失败的阶段模型契约**

创建测试，断言空草稿返回 `import`、存在对象返回 `objects`，六阶段顺序稳定，并验证对象、诊断和版本摘要使用输入计数生成。

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

```powershell
$testOut = Join-Path ([System.IO.Path]::GetTempPath()) 'ontology-workbench-model-test.cjs'
& '.\node_modules\.bin\esbuild.cmd' '.\tests\ontology-workbench-model.test.ts' --bundle --platform=node --format=cjs --outfile=$testOut
node $testOut
```

Expected: FAIL resolving `workbenchModel`。

- [ ] **Step 3: 实现最小阶段模型**

实现稳定配置数组、默认阶段函数和无副作用摘要函数。摘要只使用 `WorkspaceOverview` 已有字段：`counts`、`diagnostics`、`activeVersion` 和外部传入的版本数。

- [ ] **Step 4: 运行契约测试并确认通过**

运行 Step 2 相同命令。Expected: exit code `0`。

- [ ] **Step 5: 自动提交阶段模型**

```powershell
git add -- frontend/tests/ontology-workbench-model.test.ts frontend/src/features/ontology-package/workbenchModel.ts
git commit -m "feat: 建立本体工作台阶段模型"
```

---

### Task 2: 构建状态概览和阶段导航外壳

**Files:**
- Create: `frontend/src/features/ontology-package/WorkbenchShell.tsx`
- Create: `frontend/src/features/ontology-package/ontology-workbench.css`
- Modify: `frontend/src/features/ontology-package/OntologyWorkbench.tsx`

**Interfaces:**
- Consumes: `WorkbenchStage`、`WORKBENCH_STAGES`、`workbenchStageSummary`。
- Produces: `WorkbenchShell`，接收工作区概览、版本数、活动阶段、刷新状态、阶段切换与刷新回调，以及活动面板 `children`。

- [ ] **Step 1: 在 `OntologyWorkbench` 接入阶段状态和默认选择**

首次成功加载时使用 `initialWorkbenchStage`；后续刷新不重置用户当前选择。刷新期间保留现有 overview，并向外壳传递 `loading`。

- [ ] **Step 2: 实现工作台外壳**

状态栏展示本体包名称、活动版本、草稿修订和刷新按钮；资产带展示对象、字段、关系、时间策略；阶段导航从统一配置生成编号、标题和动态摘要；主内容区渲染 `children`。

- [ ] **Step 3: 将六个现有面板映射到活动阶段**

`OntologyWorkbench` 使用稳定映射分别渲染 `ImportPanel`、带外层标题的 `ObjectPanel`、`RelationPanel`、`TemporalPanel`、`DiagnosticsPanel` 和 `VersionPanel`。保留原 Props、刷新与冲突回调。

- [ ] **Step 4: 添加响应式样式**

桌面采用窄导航与宽操作区的两列网格；低于 `960px` 时导航改为横向滚动；低于 `640px` 时状态与统计自适应换行。使用现有全局设计令牌颜色，不引入渐变和大阴影。

- [ ] **Step 5: 运行模型契约和 production build**

```powershell
$testOut = Join-Path ([System.IO.Path]::GetTempPath()) 'ontology-workbench-model-test.cjs'
& '.\node_modules\.bin\esbuild.cmd' '.\tests\ontology-workbench-model.test.ts' --bundle --platform=node --format=cjs --outfile=$testOut
node $testOut
npm run build
```

Expected: 契约测试退出 `0`，TypeScript 与 Vite build 成功。

- [ ] **Step 6: 自动提交工作台界面**

```powershell
git add -- frontend/src/features/ontology-package/WorkbenchShell.tsx frontend/src/features/ontology-package/ontology-workbench.css frontend/src/features/ontology-package/OntologyWorkbench.tsx
git commit -m "style: 重构本体工作台阶段导航"
```

---

### Task 3: 记录实践并提供运行版本

**Files:**
- Modify: `docs/project-journal/2026-08.md`

**Interfaces:**
- Consumes: Task 1–2 的实现和验证结果。
- Produces: 可用于项目复盘与简历整理的本轮记录。

- [ ] **Step 1: 记录难点与解决方式**

追加工作台从长页面转向阶段式信息架构、保持修订状态与面板行为、空草稿默认引导、响应式阶段导航和验证证据。

- [ ] **Step 2: 运行最终聚焦验证**

重新运行 Task 2 的契约测试和 `npm run build`，并通过 `http://127.0.0.1:5199/ontology` 确认页面返回 HTTP `200`。

- [ ] **Step 3: 自动提交记录**

```powershell
git add -- docs/project-journal/2026-08.md
git commit -m "docs: 记录本体工作台重构实践"
```

- [ ] **Step 4: 保持服务运行并交付用户验收**

确认 `5199` 前端与 `8001` 后端仍监听；若服务缺失则从当前工作树启动。用户先检查视觉和交互效果，再决定是否改造对象与字段编辑器。
