# SQL 评测测试集极简模板 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成一份只要求填写“需求原文”和“真实SQL”的空白 Excel 测试集模板，并把空白模板提交 Git。

**Architecture:** 使用工作区提供的 `@oai/artifact-tool` 在临时目录构建工作簿；`测试案例` 是唯一输入事实表，`填写说明` 只承载规则。生成后通过结构检查、公式错误扫描和两张工作表渲染完成验收，最终仅保留一个 `.xlsx` 模板成品。

**Tech Stack:** Node.js、`@oai/artifact-tool`、Excel `.xlsx`、Git

## Global Constraints

- Git 只保存空白模板和通用填写说明。
- 用户只填写“需求原文”和“真实SQL”。
- 模板中不得出现真实或合成业务案例、业务表名、字段名、口径或示例 SQL。
- 填写后的真实测试集必须保存在 Git 工作树之外。
- 首期按 Hive SQL 处理；多平台方言由未来导入配置指定，不增加当前模板字段。
- 不修改应用代码，不实现批量导入器或评测执行器。

---

### Task 1: 生成并验证空白 Excel 模板

**Files:**
- Create: `docs/templates/sql-evaluation-testset-template.xlsx`
- Temporary: `%TEMP%/ontology-agent-sql-evaluation-template/build-template.mjs`
- Test: workbook structure inspection, formula-error scan, and rendered previews for both worksheets

**Interfaces:**
- Consumes: `@oai/artifact-tool` from the bundled workspace dependency path.
- Produces: `docs/templates/sql-evaluation-testset-template.xlsx` with worksheets `测试案例` and `填写说明`.

- [ ] **Step 1: Register the spreadsheet artifact operation**

Run the bundled marker exactly once before workbook authoring:

```powershell
& $bundledNode $markerScript --operation-kind create --expected-output-count 1 --output-format xlsx
```

Expected: exit code `0`.

- [ ] **Step 2: Create one temporary builder and dependency junction**

Create a temporary working directory and a `node_modules` junction to the loader-provided dependency directory. Write one `build-template.mjs` that:

```js
import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const workbook = Workbook.create();
const cases = workbook.worksheets.add("测试案例");
const guide = workbook.worksheets.add("填写说明");

cases.showGridLines = false;
cases.getRange("A1:B51").values = [
  ["需求原文", "真实SQL"],
  ...Array.from({ length: 50 }, () => [null, null]),
];
cases.freezePanes.freezeRows(1);
cases.getRange("A1:B1").format = {
  fill: "#155E75",
  font: { bold: true, color: "#FFFFFF" },
  rowHeight: 28,
};
cases.getRange("A2:B51").format = {
  wrapText: true,
  verticalAlignment: "top",
  rowHeight: 48,
};
cases.getRange("A:A").format.columnWidth = 48;
cases.getRange("B:B").format.columnWidth = 100;
cases.tables.add("A1:B51", true, "EvaluationCasesTable");
cases.getRange("A2:A51").conditionalFormats.addCustom(
  '=AND($A2="",$B2<>"")',
  { fill: "#FEE2E2", font: { color: "#991B1B" } },
);
cases.getRange("B2:B51").conditionalFormats.addCustom(
  '=AND($B2="",$A2<>"")',
  { fill: "#FEE2E2", font: { color: "#991B1B" } },
);

guide.showGridLines = false;
guide.mergeCells("A1:B1");
guide.getRange("A1").values = [["SQL 评测测试集填写说明"]];
guide.getRange("A3:B9").values = [
  ["规则", "说明"],
  ["填写范围", "只填写“需求原文”和“真实SQL”两列。"],
  ["案例粒度", "一行代表一个测试案例，两列必须同时填写。"],
  ["需求原文", "保留最初的完整业务表述，不为迎合系统改写。"],
  ["真实SQL", "填写人工确认的最终 SQL；多段 SQL 放在同一单元格并保留换行。"],
  ["评测原则", "SQL 文本结构可以不同，后续优先比较表、字段、关系、条件、账期和结果语义。"],
  ["安全要求", "填写后的文件不得提交 Git；请保存在项目工作树之外。"],
];
guide.getRange("A1:B1").format = {
  fill: "#155E75",
  font: { bold: true, color: "#FFFFFF", size: 16 },
  rowHeight: 34,
};
guide.getRange("A3:B3").format = {
  fill: "#CFFAFE",
  font: { bold: true, color: "#164E63" },
};
guide.getRange("A3:B9").format.wrapText = true;
guide.getRange("A:A").format.columnWidth = 18;
guide.getRange("B:B").format.columnWidth = 88;
guide.getRange("A4:B9").format.rowHeight = 42;

const output = await SpreadsheetFile.exportXlsx(workbook);
await fs.mkdir(outputDir, { recursive: true });
await output.save(outputPath);
```

Expected: the output path is `docs/templates/sql-evaluation-testset-template.xlsx`; no other `.xlsx` variant is exported.

- [ ] **Step 3: Inspect content and scan formula errors**

Run compact inspection in the same builder before export:

```js
console.log((await workbook.inspect({
  kind: "table",
  range: "测试案例!A1:B6",
  include: "values,formulas",
  tableMaxRows: 6,
  tableMaxCols: 2,
})).ndjson);
console.log((await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
})).ndjson);
```

Expected: two expected headers, no populated business rows, and no formula-error matches.

- [ ] **Step 4: Render both worksheets for visual verification**

Render `测试案例!A1:B8` and `填写说明!A1:B9` to temporary PNG files and inspect both images. Verify that headers, instructions and the two input columns are readable, no content is clipped, and there are no business examples.

Expected: both visual checks pass without requiring extra output workbooks.

- [ ] **Step 5: Commit the verified template**

```powershell
git add -- docs/templates/sql-evaluation-testset-template.xlsx
git diff --cached --check
git commit -m "docs: 提供极简 SQL 评测模板"
```

Expected: one binary template is committed; working tree is clean.
