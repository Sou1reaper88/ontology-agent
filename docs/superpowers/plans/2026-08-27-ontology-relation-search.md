# 本体关系编辑搜索实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为关系编辑器的四个端点选择器和现有关系列表增加中文名、物理名及关系标签本地搜索。

**Architecture:** 搜索规则集中在一个无 React 依赖的纯 TypeScript 模块中，`RelationPanel` 仅维护搜索词并调用该模块。工作区概览仍一次返回全部对象和关系，搜索不调用后端、不写草稿，也不改变修订号。

**Tech Stack:** React 18、TypeScript、Ant Design 5、esbuild Node 契约测试、Vite production build。

## Global Constraints

- 不新增或修改后端 API。
- 不改变关系保存、确认、基数、权限和修订冲突行为。
- 中文标签和物理名使用去除首尾空格、不区分英文大小写的包含匹配。
- 搜索只改变浏览器内展示，不改变表单值、草稿或修订号。
- 不引入新的测试框架或 UI 组件体系。
- 完成每个逻辑改动后自动 Git 提交；不自动推送或合并。

---

### Task 1: 搜索规则与关系编辑器接线

**Files:**
- Create: `frontend/src/features/ontology-package/relationSearch.ts`
- Create: `frontend/tests/relation-search.test.ts`
- Modify: `frontend/src/features/ontology-package/RelationPanel.tsx`

**Interfaces:**
- Consumes: `DraftObject`、`DraftRelation` from `frontend/src/features/ontology-package/types.ts`
- Produces: `includesRelationSearch(search: string, ...values: Array<string | null | undefined>): boolean`
- Produces: `relationMatchesSearch(search: string, objects: DraftObject[], relation: DraftRelation): boolean`
- Produces: 四个可搜索 `Select` 和一个可筛选的现有关系列表

- [ ] **Step 1: 编写失败的纯函数契约测试**

创建 `frontend/tests/relation-search.test.ts`：

```typescript
import {
  includesRelationSearch,
  relationMatchesSearch,
} from "../src/features/ontology-package/relationSearch";
import type { DraftObject, DraftRelation } from "../src/features/ontology-package/types";

function assert(value: unknown, label: string): asserts value {
  if (!value) throw new Error(label);
}

const objects: DraftObject[] = [
  {
    id: "object/customer",
    physicalName: "D_CUSTOMER_M",
    label: "客户主表",
    description: null,
    status: "active",
    priority: 100,
    fields: [
      {
        id: "field/customer-id",
        physicalName: "CUSTOMER_ID",
        label: "客户编号",
        description: null,
        xsdType: "string",
        primaryKey: true,
        title: true,
        aliases: [],
        status: "active",
        priority: 100,
      },
    ],
  },
  {
    id: "object/order",
    physicalName: "D_ORDER_D",
    label: "订单明细",
    description: null,
    status: "active",
    priority: 100,
    fields: [
      {
        id: "field/order-customer-id",
        physicalName: "CUSTOMER_ID",
        label: "订单客户编号",
        description: null,
        xsdType: "string",
        primaryKey: false,
        title: false,
        aliases: [],
        status: "active",
        priority: 100,
      },
    ],
  },
];

const relation: DraftRelation = {
  id: "relation/customer-order",
  label: "订单归属客户",
  sourceObjectId: "object/order",
  sourceFieldId: "field/order-customer-id",
  targetObjectId: "object/customer",
  targetFieldId: "field/customer-id",
  cardinality: "many_to_one",
  status: "active",
  priority: 100,
  confirmed: true,
};

assert(includesRelationSearch(" customer ", "CUSTOMER_ID"), "physical name is case-insensitive");
assert(includesRelationSearch("客户", "客户主表", "D_CUSTOMER_M"), "Chinese label matches");
assert(relationMatchesSearch("订单归属", objects, relation), "relation label matches");
assert(relationMatchesSearch("d_customer_m", objects, relation), "target object matches");
assert(relationMatchesSearch("订单客户编号", objects, relation), "source field matches");
assert(relationMatchesSearch("   ", objects, relation), "blank search returns all relations");
assert(!relationMatchesSearch("不存在", objects, relation), "unmatched relation is rejected");

const missingEndpoint = { ...relation, sourceObjectId: "object/missing" };
assert(
  relationMatchesSearch("已删除对象或字段", objects, missingEndpoint),
  "missing endpoint remains searchable"
);
```

- [ ] **Step 2: 运行契约测试并确认红灯**

Run:

```powershell
$output = Join-Path $env:TEMP 'ontology-relation-search.test.cjs'
& '.\frontend\node_modules\.bin\esbuild.cmd' '.\frontend\tests\relation-search.test.ts' --bundle --platform=node --format=cjs --outfile=$output
```

Expected: FAIL because `relationSearch.ts` does not exist.

- [ ] **Step 3: 实现最小搜索规则模块**

创建 `frontend/src/features/ontology-package/relationSearch.ts`：

```typescript
import type { DraftObject, DraftRelation } from "./types";

const MISSING_ENDPOINT = "已删除对象或字段";

function normalized(value: string | null | undefined): string {
  return (value ?? "").trim().toLocaleLowerCase();
}

export function includesRelationSearch(
  search: string,
  ...values: Array<string | null | undefined>
): boolean {
  const query = normalized(search);
  if (!query) return true;
  return values.some((value) => normalized(value).includes(query));
}

function endpointValues(
  objects: DraftObject[],
  objectId: string,
  fieldId: string
): string[] {
  const object = objects.find((item) => item.id === objectId);
  const field = object?.fields.find((item) => item.id === fieldId);
  if (!object || !field) return [MISSING_ENDPOINT];
  return [object.label ?? "", object.physicalName, field.label ?? "", field.physicalName];
}

export function relationMatchesSearch(
  search: string,
  objects: DraftObject[],
  relation: DraftRelation
): boolean {
  return includesRelationSearch(
    search,
    relation.label,
    ...endpointValues(objects, relation.sourceObjectId, relation.sourceFieldId),
    ...endpointValues(objects, relation.targetObjectId, relation.targetFieldId)
  );
}
```

- [ ] **Step 4: 运行搜索契约并确认绿灯**

Run:

```powershell
$output = Join-Path $env:TEMP 'ontology-relation-search.test.cjs'
& '.\frontend\node_modules\.bin\esbuild.cmd' '.\frontend\tests\relation-search.test.ts' --bundle --platform=node --format=cjs --outfile=$output
if ($LASTEXITCODE -eq 0) { node $output }
```

Expected: esbuild exits `0`, Node exits `0`, and no assertion error is printed.

- [ ] **Step 5: 接入四个选择器搜索**

在 `RelationPanel.tsx` 导入：

```typescript
import { includesRelationSearch, relationMatchesSearch } from "./relationSearch";
```

为源对象、源字段、目标对象、目标字段四个 `Select` 添加相同的显式搜索配置：

```tsx
showSearch
filterOption={(input, option) =>
  includesRelationSearch(input, String(option?.label ?? ""))
}
```

保留现有 `options`、`disabled` 和对象变化时清空字段的行为。对象和字段选项标签已经同时包含中文名与物理名，因此显式过滤会覆盖两种名称。

- [ ] **Step 6: 接入现有关系列表搜索**

在 `RelationPanel` 增加状态和派生列表：

```typescript
const [relationSearch, setRelationSearch] = useState("");
const visibleRelations = useMemo(
  () => relations.filter((item) => relationMatchesSearch(relationSearch, objects, item)),
  [objects, relationSearch, relations]
);
```

在“现有关系”标题与 `List` 之间增加：

```tsx
<Input.Search
  allowClear
  placeholder="搜索关系标签、对象或字段"
  value={relationSearch}
  onChange={(event) => setRelationSearch(event.target.value)}
/>
```

将 `List` 的数据和空状态改为：

```tsx
dataSource={visibleRelations}
locale={{
  emptyText: relations.length === 0 ? "尚未配置关系" : "未找到匹配关系",
}}
```

- [ ] **Step 7: 运行前端契约和生产构建**

Run:

```powershell
$output = Join-Path $env:TEMP 'ontology-relation-search.test.cjs'
& '.\frontend\node_modules\.bin\esbuild.cmd' '.\frontend\tests\relation-search.test.ts' --bundle --platform=node --format=cjs --outfile=$output
if ($LASTEXITCODE -eq 0) { node $output }
if ($LASTEXITCODE -eq 0) { npm --prefix frontend run build }
```

Expected: contract process exits `0`; TypeScript and Vite build succeed. The existing large-chunk warning may remain.

- [ ] **Step 8: 提交搜索功能**

```powershell
git add -- frontend/src/features/ontology-package/relationSearch.ts frontend/src/features/ontology-package/RelationPanel.tsx frontend/tests/relation-search.test.ts frontend/tsconfig.tsbuildinfo
git diff --cached --check
git commit -m "feat: 支持搜索本体关系与端点"
```

---

### Task 2: 运行态验收与工程记录

**Files:**
- Modify: `docs/project-journal/2026-08.md`

**Interfaces:**
- Consumes: Task 1 的四个可搜索选择器和 `visibleRelations`
- Produces: 可复查的运行态证据、工程实践记录和保持运行的本地服务

- [ ] **Step 1: 确认服务加载当前工作树**

先通过端口监听信息确认 `5199` 的现有前端进程属于本次工作树，再只停止该进程并从当前工作树重新启动；后端接口没有变化，无需重启后端。启动命令：

```powershell
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5199
```

Expected: `http://127.0.0.1:5199/ontology` returns `200` and displays the ontology workbench.

- [ ] **Step 2: 执行一条真实页面搜索路径**

在关系编辑器验证：

1. 源对象下拉输入现有对象物理名片段，只保留匹配对象。
2. 选中对象后，在源字段下拉输入字段物理名片段，只保留匹配字段。
3. 在现有关系搜索框输入关系标签或端点名称，列表即时缩小。
4. 清空搜索框，完整关系列表恢复。
5. 验收前后读取工作区概览，确认草稿修订号不变，且没有发生 `PATCH`、`PUT`、`DELETE` 或导入确认请求。

若当前草稿没有关系，只验收四个选择器搜索和“尚未配置关系”空状态；关系列表匹配由 Task 1 契约测试证明，不创建合成关系污染用户草稿。

- [ ] **Step 3: 记录工程难点与验证证据**

在 `docs/project-journal/2026-08.md` 追加：

```markdown
## 2026-08-27：本体关系编辑本地搜索

### 问题与解决方式

- 关系编辑器已加载全部对象、字段和关系，但缺少定位能力。采用前端本地包含匹配，避免新增无收益的后端搜索接口。
- 将大小写、空白、缺失端点和组合关系索引放入纯 TypeScript 模块，使 UI 接线保持简单且可独立验证。
- 搜索只过滤展示数组，不改变表单值、草稿和修订号；运行态验收同时检查页面行为与无写请求边界。

### 验证证据

- 搜索契约测试通过，覆盖中文名、物理名、关系标签、两端对象/字段、空搜索、无结果和缺失端点。
- 前端 production build 通过。
- 真实页面对象/字段搜索可用，清空后恢复完整结果，草稿修订号保持不变。
```

只写实际发生的验收事实；若关系列表因当前无关系而未完成页面匹配验收，将最后一条改为“真实页面对象/字段搜索与空状态通过，关系列表匹配由合成契约覆盖”。

- [ ] **Step 4: 提交工程记录并确认干净状态**

```powershell
git add -- docs/project-journal/2026-08.md
git diff --cached --check
git commit -m "docs: 记录本体关系搜索实践"
git status --short
```

Expected: journal commit succeeds; `git status --short` is empty. Do not push or merge.
