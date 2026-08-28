# Chat Evidence Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将智能取数页升级为会话目录、主要消息工作区和本体证据检查器组成的三栏工作台，同时保持所有现有 API、轮询、SQL 编辑和执行行为。

**Architecture:** `Chat.tsx` 继续作为业务控制器，接口、副作用和状态不外移；新组件只消费 Props 和回调。当前本体证据由纯函数从消息列表和用户选择中确定，桌面显示右栏，中窄屏复用同一证据组件进入抽屉。

**Tech Stack:** React 18、TypeScript 5、React Router 6、Ant Design 5、Vite 5、CSS

## Global Constraints

- 不修改后端 API、Agent、SQL 文本、本体 DTO、路由地址或执行流程。
- 不新增 SQL diff、语法高亮、Markdown 或测试依赖。
- 保留新建、上下文、轮询、删除、批量删除、清空、编辑、复制和执行功能。
- 只改造智能取数页和本体 SQL 对比组件，不改本体工作台等其他页面内部结构。
- 每个独立任务通过必要契约测试和 production build 后自动提交 Git。
- 最终保留 `127.0.0.1:5199` 服务供用户验收，不推送或合并分支。

---

## File Map

- Create `frontend/src/features/chat/types.ts`: 会话、消息和 SQL 编辑状态的共享类型。
- Create `frontend/src/features/chat/evidenceSelection.ts`: 当前证据消息选择纯函数。
- Create `frontend/src/features/chat/ontologyPresentation.ts`: 本体状态标题和语义等级映射。
- Create `frontend/tests/chat-evidence-selection.test.ts`: 证据选择和状态映射契约。
- Create `frontend/src/features/chat/ConversationSidebar.tsx`: 会话目录与批量操作。
- Create `frontend/src/features/chat/TraceSteps.tsx`: 可折叠生成链路。
- Create `frontend/src/features/chat/MessageTimeline.tsx`: 消息、SQL 编辑与操作区。
- Create `frontend/src/features/chat/OntologyEvidencePanel.tsx`: 状态、账期、证据和本体包信息。
- Modify `frontend/src/components/OntologyComparison.tsx`: 聚焦 SQL 对比，不重复展示右栏证据。
- Create `frontend/src/pages/Chat.css`: 三栏工作台及响应式布局。
- Modify `frontend/src/pages/Chat.tsx`: 业务状态编排、证据选择和抽屉。
- Modify `docs/project-journal/2026-08.md`: 记录本轮难点、方案和简历素材。

---

### Task 1: 建立聊天展示类型与证据选择契约

**Files:**
- Create: `frontend/src/features/chat/types.ts`
- Create: `frontend/src/features/chat/evidenceSelection.ts`
- Create: `frontend/src/features/chat/ontologyPresentation.ts`
- Create: `frontend/tests/chat-evidence-selection.test.ts`

**Interfaces:**
- Produces: `ConversationItem`、`ChatMessage`、`EditingSql`、`TemporalEvidence`、`OntologyShadowResult`。
- Produces: `selectedEvidenceMessage(messages, selectedId)`。
- Produces: `ontologyStatusPresentation(status)`。

- [ ] **Step 1: 写失败的选择与状态契约测试**

```ts
import { selectedEvidenceMessage } from "../src/features/chat/evidenceSelection";
import { ontologyStatusPresentation } from "../src/features/chat/ontologyPresentation";

const shadow = (status: "generated" | "no_match") => ({ status });
const messages = [
  { id: 1, role: "assistant" as const, ontology_shadow: shadow("generated") },
  { id: 2, role: "user" as const, ontology_shadow: null },
  { id: 3, role: "assistant" as const, ontology_shadow: shadow("no_match") },
];

if (selectedEvidenceMessage(messages, null)?.id !== 3) throw new Error("latest evidence must win");
if (selectedEvidenceMessage(messages, 1)?.id !== 1) throw new Error("explicit selection must remain");
if (selectedEvidenceMessage(messages, 99)?.id !== 3) throw new Error("stale selection must fall back");
if (selectedEvidenceMessage([{ id: 4, role: "user", ontology_shadow: null }], null) !== null) throw new Error("empty evidence must be null");
if (ontologyStatusPresentation("generated").tone !== "success") throw new Error("generated tone");
if (ontologyStatusPresentation("no_match").tone !== "neutral") throw new Error("no-match is not a system error");
```

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

```powershell
$chatEvidenceTestOut = Join-Path ([System.IO.Path]::GetTempPath()) 'ontology-agent-chat-evidence-test.cjs'
& '.\node_modules\.bin\esbuild.cmd' '.\tests\chat-evidence-selection.test.ts' --bundle --platform=node --format=cjs --outfile=$chatEvidenceTestOut
node $chatEvidenceTestOut
```

Expected: FAIL resolving `evidenceSelection` or `ontologyPresentation`.

- [ ] **Step 3: 实现共享类型和纯函数**

`types.ts` 导出原 `Chat.tsx` 与 `OntologyComparison.tsx` 中的会话、消息、本体结果和时间证据字段，`ChatMessage.ontology_shadow` 使用 `OntologyShadowResult | null`。`selectedEvidenceMessage` 接受只要求 `id`、`role` 和 `ontology_shadow` 的泛型消息；若显式 ID 仍指向带结果的 assistant 消息则返回它，否则从尾部返回最新结果。`ontologyStatusPresentation` 为六个状态返回固定 `title`、`description` 和 `tone: "success" | "neutral" | "warning"`，不推断后端未提供的缺口。

- [ ] **Step 4: 运行契约测试和 production build**

Expected: 契约测试退出 `0`，`npm run build` 成功。

- [ ] **Step 5: 提交选择契约**

```powershell
git add -- frontend/src/features/chat/types.ts frontend/src/features/chat/evidenceSelection.ts frontend/src/features/chat/ontologyPresentation.ts frontend/tests/chat-evidence-selection.test.ts frontend/tsconfig.tsbuildinfo
git commit -m "refactor: 建立聊天证据选择契约"
```

---

### Task 2: 重构 SQL 对比与本体证据展示

**Files:**
- Create: `frontend/src/features/chat/OntologyEvidencePanel.tsx`
- Modify: `frontend/src/components/OntologyComparison.tsx`
- Create: `frontend/src/features/chat/chat-components.css`

**Interfaces:**
- `OntologyComparison` consumes `legacySql`, `result`, `onEditLegacy`, `onCopyOntology`, `onViewEvidence`。
- `OntologyEvidencePanel` consumes `result: OntologyShadowResult | null`。

- [ ] **Step 1: 将 `OntologyComparison` 收敛为 SQL 比较区**

从 `features/chat/types.ts` 导入 DTO，并从 `OntologyComparison.tsx` 重新导出 `OntologyShadowResult` 类型以兼容现有调用方。移除完整账期卡片和证据标签清单；用语义化 `<section>`、两个 `<article>` 和统一代码块呈现现有 SQL与本体 SQL。非生成状态展示紧凑状态条和“查看本体依据”动作。生成状态显示表映射变化、可执行/只读边界、编辑与复制动作，不添加本体 SQL 执行按钮。

- [ ] **Step 2: 新增 `OntologyEvidencePanel`**

无结果时显示说明性空状态。生成状态依次显示摘要、每条 `temporal_decisions`（兼容旧 `temporal_decision`）、六类证据和 package 版本/摘要；非生成状态使用 `ontologyStatusPresentation` 和后端 `summary`。数组为空时不渲染空标签组。

- [ ] **Step 3: 写组件样式并构建**

`chat-components.css` 使用既有 `--oa-*` 令牌，实现统一 SQL 暗色表面、低饱和状态、时间决策分隔行和证据列表。运行 Task 1 契约测试与 `npm run build`。

Expected: TypeScript 和 Vite 构建成功，既有本体 DTO 消费方无类型错误。

- [ ] **Step 4: 提交 SQL 与证据组件**

```powershell
git add -- frontend/src/components/OntologyComparison.tsx frontend/src/features/chat/OntologyEvidencePanel.tsx frontend/src/features/chat/chat-components.css frontend/tsconfig.tsbuildinfo
git commit -m "style: 重构本体 SQL 对比与证据面板"
```

---

### Task 3: 拆分会话目录、生成链路和消息时间线

**Files:**
- Create: `frontend/src/features/chat/ConversationSidebar.tsx`
- Create: `frontend/src/features/chat/TraceSteps.tsx`
- Create: `frontend/src/features/chat/MessageTimeline.tsx`
- Modify: `frontend/src/features/chat/chat-components.css`

**Interfaces:**
- `ConversationSidebar` 通过 Props 接收列表、加载/选择状态和所有删除回调，不调用 API。
- `TraceSteps` 接收 `steps: unknown[]` 和 `generating?: boolean`。
- `MessageTimeline` 接收消息、编辑状态、执行状态、滚动 ref 及编辑/复制/执行/选择证据回调。

- [ ] **Step 1: 实现 `ConversationSidebar`**

迁移现有新建、全选、批量删除、完成、清空、单条删除和 checkbox 行为。使用 `Skeleton` 匹配列表行加载形状；当前会话、批量选中和空状态通过 class 表达；单条删除继续使用 `Popconfirm`。

- [ ] **Step 2: 实现 `TraceSteps`**

使用 Ant `Collapse` 或原生 `details` 默认折叠为“生成链路 · N 步”；展开后复用 `Steps`，保留 label/node、summary、duration 和 error/process 状态，不再使用可点击 `div`。

- [ ] **Step 3: 实现 `MessageTimeline`**

迁移用户/assistant 渲染、生成链路、`OntologyComparison`、legacy SQL 编辑框、执行和复制按钮。每条带 `ontology_shadow` 的 assistant 回答提供“查看本体依据”，并以 `aria-current` 或可见文本表示当前证据选择。保持原有按钮出现条件与回调参数不变。

- [ ] **Step 4: 补充样式并构建**

在 `chat-components.css` 增加会话行、报告式 assistant 消息、紧凑用户需求块、骨架和操作栏样式。运行 Task 1 契约测试与 `npm run build`。

Expected: 构建成功，三个展示组件不包含 `client` 导入。

- [ ] **Step 5: 提交展示组件拆分**

```powershell
git add -- frontend/src/features/chat/ConversationSidebar.tsx frontend/src/features/chat/TraceSteps.tsx frontend/src/features/chat/MessageTimeline.tsx frontend/src/features/chat/chat-components.css frontend/tsconfig.tsbuildinfo
git commit -m "refactor: 拆分智能取数展示组件"
```

---

### Task 4: 集成三栏工作台与响应式抽屉

**Files:**
- Create: `frontend/src/pages/Chat.css`
- Modify: `frontend/src/pages/Chat.tsx`
- Modify: `docs/project-journal/2026-08.md`

**Interfaces:**
- `Chat.tsx` consumes all Task 1-3 exports and remains the only API owner。
- CSS breakpoints: desktop evidence at `>=1200px`; desktop conversations at `>=900px`。

- [ ] **Step 1: 保留业务控制器并替换 JSX 编排**

在 `Chat.tsx` 保留所有 API 函数和现有业务 state，移除内联展示组件及旧 Ant `Layout/Sider`。新增 `selectedEvidenceId`、`conversationDrawerOpen`、`evidenceDrawerOpen`；用 `selectedEvidenceMessage(messages, selectedEvidenceId)` 派生证据消息。切换会话/新建时清空显式证据选择；点击回答时设置 ID，并在 `<1200px` 打开证据抽屉。

- [ ] **Step 2: 实现桌面三栏与窄屏抽屉**

使用 CSS Grid 组装 `ConversationSidebar`、主工作区和 `OntologyEvidencePanel`。`Grid.useBreakpoint()` 控制两个 Ant `Drawer`，但同一时间只渲染一份可交互会话目录和一份可见证据面板。主区顶部保留标题、上下文状态和设置按钮，底部保留 Enter/Shift+Enter 输入行为。

- [ ] **Step 3: 实现 `Chat.css`**

提供三栏比例、面板分隔、独立滚动、主区输入底栏和两个响应式断点。使用 `min-height: calc(100dvh - 136px)` 而不是固定 `100vh`；SQL 在窄屏换行并允许横向滚动；页面不得产生整体横向溢出。

- [ ] **Step 4: 更新工程日志**

在 `docs/project-journal/2026-08.md` 追加本轮问题、组件边界、证据选择回退、响应式抽屉、验证证据和简历素材；明确只完成前端展示重构。

- [ ] **Step 5: 运行最小必要最终验证**

运行新增契约测试、现有 theme/navigation/login 契约测试和 `npm run build`。确认 `git diff --check` 通过；运行态验证 `/chat` 与 `/login` 返回 `200`。

- [ ] **Step 6: 提交工作台集成**

```powershell
git add -- frontend/src/pages/Chat.tsx frontend/src/pages/Chat.css docs/project-journal/2026-08.md frontend/tsconfig.tsbuildinfo
git commit -m "style: 构建智能取数三栏证据工作台"
```

- [ ] **Step 7: 保留服务供用户验收**

确认 `5199` 监听进程命令行属于当前工作树；若已运行则依赖 Vite HMR，不重启。访问 `http://127.0.0.1:5199/chat`，由用户先进行视觉与核心交互验收。
