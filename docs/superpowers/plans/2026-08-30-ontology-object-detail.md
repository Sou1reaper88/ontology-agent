# Ontology Object Detail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将“对象与字段”阶段改造成对象目录与完整宽度详情两层体验，使表描述和字段描述在只读与编辑状态下都具有充足空间。

**Architecture:** `OntologyWorkbench` 继续持有 overview 与刷新逻辑，并用 `object` URL 查询参数记录详情选择。`ObjectPanel` 只负责对象目录，新增 `ObjectDetailPanel` 负责对象和字段的查看、编辑与删除；纯函数模块统一对象筛选、查询参数写入和失效选择判断。

**Tech Stack:** React 18、TypeScript 5、React Router 6、Ant Design 5、Vite 5、CSS

## Global Constraints

- 不修改后端接口、草稿模型、修订冲突协议、级联删除或字段保存行为。
- 默认只读，用户显式点击后统一进入编辑态。
- 当前对象写入 `/ontology?object=<encoded-id>`，支持刷新和浏览器返回。
- 搜索、导航和编辑模式切换不得产生草稿写入。
- 不新增 UI 或测试依赖。
- 每个独立阶段自动提交 Git，不推送或合并；完成后保持服务运行供用户验收。

---

## File Map

- Create `frontend/src/features/ontology-package/objectNavigation.ts`: 对象筛选、选择和查询参数更新纯函数。
- Create `frontend/tests/ontology-object-navigation.test.ts`: 对象目录与 URL 选择契约。
- Modify `frontend/src/features/ontology-package/ObjectPanel.tsx`: 收敛为对象目录。
- Create `frontend/src/features/ontology-package/ObjectDetailPanel.tsx`: 完整宽度对象与字段详情。
- Create `frontend/src/features/ontology-package/object-detail.css`: 对象目录、详情和响应式表格样式。
- Modify `frontend/src/features/ontology-package/OntologyWorkbench.tsx`: 读取和更新对象查询参数，组装列表或详情。
- Modify `docs/project-journal/2026-08.md`: 记录信息层级与编辑安全实践。

---

### Task 1: 建立对象导航契约

**Files:**
- Create: `frontend/tests/ontology-object-navigation.test.ts`
- Create: `frontend/src/features/ontology-package/objectNavigation.ts`

**Interfaces:**
- Produces: `filterOntologyObjects(objects: DraftObject[], query: string): DraftObject[]`。
- Produces: `selectedOntologyObject(objects: DraftObject[], objectId: string | null): DraftObject | null`。
- Produces: `withSelectedObject(params: URLSearchParams, objectId: string | null): URLSearchParams`。

- [ ] **Step 1: 写失败契约**

测试中文名、物理名和描述搜索；有效 ID 返回对象、失效 ID 返回空；查询参数写入时保留其他参数，返回列表时只移除 `object`；使用含 URI 字符的对象 ID 验证编码交给 `URLSearchParams`。

- [ ] **Step 2: 运行并确认因模块不存在而失败**

```powershell
$testOut = Join-Path ([System.IO.Path]::GetTempPath()) 'ontology-object-navigation-test.cjs'
& '.\node_modules\.bin\esbuild.cmd' '.\tests\ontology-object-navigation.test.ts' --bundle --platform=node --format=cjs --outfile=$testOut
node $testOut
```

Expected: FAIL resolving `objectNavigation`。

- [ ] **Step 3: 实现最小纯函数**

筛选统一去首尾空白并转小写；无查询返回原数组。查询参数函数复制输入参数，非空 ID 使用 `set`，空 ID 使用 `delete`，不修改调用方对象。

- [ ] **Step 4: 运行契约并确认通过**

运行 Step 2 相同命令。Expected: exit code `0`。

- [ ] **Step 5: 自动提交**

```powershell
git add -- frontend/tests/ontology-object-navigation.test.ts frontend/src/features/ontology-package/objectNavigation.ts
git commit -m "feat: 建立本体对象详情导航契约"
```

---

### Task 2: 拆分对象目录与详情

**Files:**
- Modify: `frontend/src/features/ontology-package/ObjectPanel.tsx`
- Create: `frontend/src/features/ontology-package/ObjectDetailPanel.tsx`
- Create: `frontend/src/features/ontology-package/object-detail.css`
- Modify: `frontend/src/features/ontology-package/OntologyWorkbench.tsx`

**Interfaces:**
- Consumes: Task 1 的三个纯函数。
- Produces: `ObjectPanel({ objects, onSelectObject })` 对象目录。
- Produces: `ObjectDetailPanel({ workspaceId, revision, object, onChanged, onConflict, onBack })` 详情治理界面。

- [ ] **Step 1: 将 `ObjectPanel` 收敛为目录**

移除字段草稿、API 调用、抽屉和删除状态；保留搜索并显示对象中文名、物理表名、描述摘要、状态和字段数，点击调用 `onSelectObject(item.id)`。空对象显示导入提示。

- [ ] **Step 2: 新增默认只读详情**

详情头部提供返回对象列表、对象中文名、物理表名、描述、状态和字段数；字段表默认用文本展示物理名、类型、中文名、描述、主键与标题标记，并保留字段搜索和分页。

- [ ] **Step 3: 接入统一编辑模式**

点击“编辑对象与字段”后显示对象中文名、对象描述、字段中文名和字段描述输入框。对象使用 `updateObject` 保存，字段按行使用 `updateField` 保存；退出编辑重建初始草稿。对象与字段删除继续使用 `DeleteDraftModal`，删除当前对象后调用 `onBack`。

- [ ] **Step 4: 接入 URL 查询参数**

`OntologyWorkbench` 使用 `useSearchParams` 读取 `object`。对象阶段根据参数渲染目录、有效详情或失效链接状态；进入和返回使用 `withSelectedObject` 更新参数，保留其他查询参数。诊断跳转到对象阶段时移除旧对象选择，避免误停留在不相关详情。

- [ ] **Step 5: 添加完整宽度与响应式样式**

对象目录采用纵向可点击行；详情使用标题区与元数据带。字段表设置最小宽度并在窄屏横向滚动，描述列弹性最大；编辑态和只读态具有明确视觉差异。

- [ ] **Step 6: 运行契约与 production build**

```powershell
$testOut = Join-Path ([System.IO.Path]::GetTempPath()) 'ontology-object-navigation-test.cjs'
& '.\node_modules\.bin\esbuild.cmd' '.\tests\ontology-object-navigation.test.ts' --bundle --platform=node --format=cjs --outfile=$testOut
node $testOut
npm run build
```

Expected: 契约退出 `0`，TypeScript 与 Vite build 成功，仅允许项目既有的大 chunk 警告。

- [ ] **Step 7: 自动提交**

```powershell
git add -- frontend/src/features/ontology-package/ObjectPanel.tsx frontend/src/features/ontology-package/ObjectDetailPanel.tsx frontend/src/features/ontology-package/object-detail.css frontend/src/features/ontology-package/OntologyWorkbench.tsx frontend/tsconfig.tsbuildinfo
git commit -m "style: 拆分本体对象目录与详情"
```

---

### Task 3: 记录与运行交付

**Files:**
- Modify: `docs/project-journal/2026-08.md`

**Interfaces:**
- Consumes: Task 1–2 的实现和验证结果。
- Produces: 项目难点、解决方式与简历表述记录。

- [ ] **Step 1: 追加工程记录**

记录并排布局压缩描述、URL 选择与草稿状态隔离、默认只读与显式编辑、删除后回退和字段宽表响应式处理。

- [ ] **Step 2: 最终聚焦验证**

重新运行对象导航契约和 `npm run build`；验证 `5199/ontology`、`8001/health` 以及经前端代理访问的工作区接口返回 HTTP 200。

- [ ] **Step 3: 自动提交记录**

```powershell
git add -- docs/project-journal/2026-08.md
git commit -m "docs: 记录本体对象详情重构实践"
```

- [ ] **Step 4: 保持服务运行**

保留当前 `5199` 前端和 `8001` 后端，用户先验收对象列表、返回、只读详情和编辑态效果。
