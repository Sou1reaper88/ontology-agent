# 表格元数据本体导入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Python 将对象信息 TSV 转换成可校验、可发布的外部本体包，并让未预先保存为 SQL 模板的字段组合查询能够命中本体影子链路。

**Architecture:** 解析器将 TSV 转成与数据库无关的冻结 DTO，质量分析器和本地覆盖器在生成前产出结构化诊断；包生成器使用 RDFLib 构建领域与映射图，在同级暂存目录中校验成功后原子切换目标目录。CLI 组合这些接口，真实元数据和报告只写入 `.local/`，查询计划器补充基于属性反推概念的安全匹配能力。

**Tech Stack:** Python 3.11+、Pydantic v2、RDFLib、PySHACL、Typer-free argparse CLI、pytest、Ruff、Black

## Global Constraints

- 通用实现不得依赖 MySQL、Hive 或任何单一数据库连接。
- 真实附件、表名、字段名、字段描述、覆盖配置、诊断报告和生成包不得进入 Git。
- 生成包不得保存主机、端口、账户、密码、token 或连接字符串。
- 单次导入只允许一个对象；不从字段名称或描述生成业务规则。
- 推测性业务规则不得进入查询计划；当前导入结果的规则数量必须为零。
- 任何阻断诊断出现时不得创建或替换目标包。
- 生成和校验失败时必须保留原有目标包。
- 原有 SQL 链路继续运行，本体 SQL 只作为影子预览。
- 每个逻辑改动通过测试后自动 Git 提交；完成后启动服务供用户体验，不执行额外多轮审查。

---

## File Structure

- Create `ontology_core/tabular_metadata.py`: TSV DTO、解析、规范化、质量诊断和本地覆盖。
- Create `ontology_core/metadata_package.py`: RDF 图生成、暂存校验和目标目录切换。
- Modify `ontology_core/errors.py`: 增加稳定的元数据导入错误类型。
- Modify `ontology_core/cli.py`: 增加 `import-tabular` 命令并输出 JSON 报告。
- Modify `ontology_core/planner.py`: 在未直接命中概念时通过已匹配属性反推唯一概念，并拒绝无属性匹配。
- Modify `ontology_core/__init__.py`: 导出稳定的导入公共接口。
- Create `tests/ontology_core/test_tabular_metadata.py`: 解析、诊断和覆盖测试。
- Create `tests/ontology_core/test_metadata_package.py`: 包生成、语义计数和原子性测试。
- Modify `tests/ontology_core/test_cli.py`: 命令行导入测试。
- Modify `tests/ontology_core/test_planner.py`: 属性反推概念和未知属性关闭测试。
- Modify `docs/project-journal/2026-08.md`: 记录元数据质量、隐私隔离和原子发布实践，不记录真实业务标识符。

---

### Task 1: TSV 解析、诊断与本地覆盖

**Files:**
- Create: `ontology_core/tabular_metadata.py`
- Modify: `ontology_core/errors.py`
- Test: `tests/ontology_core/test_tabular_metadata.py`

**Interfaces:**
- Produces: `parse_tabular_metadata(text: str) -> TabularMetadataDraft`
- Produces: `load_metadata_overrides(path: Path) -> MetadataOverrides`
- Produces: `apply_metadata_overrides(draft: TabularMetadataDraft, overrides: MetadataOverrides) -> TabularMetadataDraft`
- Produces: `analyze_metadata(draft: TabularMetadataDraft) -> tuple[ImportDiagnostic, ...]`
- Produces: `raise_for_blocking_diagnostics(diagnostics: tuple[ImportDiagnostic, ...]) -> None`
- Produces: immutable `TableMetadata`, `FieldMetadata`, `SourceLocation`, `ImportDiagnostic`, `MetadataOverrides`

- [ ] **Step 1: Write failing parser and normalization tests**

Create synthetic TSV fixtures only. Cover Chinese header lookup independent of column order, extra columns, blank optional cells, original identifier case, source line number and one-object aggregation:

```python
def test_parse_tabular_metadata_groups_one_object_and_preserves_identifiers() -> None:
    draft = parse_tabular_metadata(SYNTHETIC_TSV)
    assert draft.table.physical_name == "DEMO_ENTITY_M"
    assert draft.table.label == "演示实体月表"
    assert [field.physical_name for field in draft.fields] == ["ENTITY_ID", "P_MON"]
    assert draft.fields[0].location.line == 2
```

- [ ] **Step 2: Run parser tests and verify RED**

Run: `pytest tests/ontology_core/test_tabular_metadata.py -q`

Expected: FAIL during import because `ontology_core.tabular_metadata` does not exist.

- [ ] **Step 3: Implement frozen DTOs and TSV parser**

Use Pydantic frozen models and exact input column aliases:

```python
class DiagnosticSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    CONFIRMATION_REQUIRED = "confirmation_required"


class SourceLocation(FrozenModel):
    line: int = Field(ge=2)
    column: str


class FieldMetadata(FrozenModel):
    physical_name: str
    label: str | None = None
    source_type: str | None = None
    description: str | None = None
    primary_key: bool = False
    title: bool = False
    aliases: tuple[str, ...] = ()
    location: SourceLocation


class TableMetadata(FrozenModel):
    physical_name: str
    label: str | None = None
    description: str | None = None
    enabled: bool = True


class TabularMetadataDraft(FrozenModel):
    table: TableMetadata
    fields: tuple[FieldMetadata, ...]
```

Parse with `csv.DictReader(io.StringIO(text), delimiter="\t")`; strip values, reject missing required headers through `OntologyImportError`, preserve physical identifier case, and normalize only comparison keys with `casefold()`.

- [ ] **Step 4: Write failing quality diagnostic tests**

Cover missing physical names, multiple objects, duplicate field names case-insensitively, invalid SQL identifiers, blank descriptions, unknown source types and a conservative name/description conflict heuristic. Assertions use stable codes such as `duplicate_field`, `multiple_objects`, `blank_field_description`, `unknown_field_type` and `metadata_text_conflict`.

- [ ] **Step 5: Implement diagnostics and blocking exception**

Add `OntologyImportError(OntologyError)` in `ontology_core/errors.py` with code `ontology_import_error`. Implement diagnostics as immutable values:

```python
class ImportDiagnostic(FrozenModel):
    code: str
    severity: DiagnosticSeverity
    message: str
    location: SourceLocation | None = None
    field_name: str | None = None


def raise_for_blocking_diagnostics(diagnostics: tuple[ImportDiagnostic, ...]) -> None:
    blocking = tuple(item for item in diagnostics if item.severity == DiagnosticSeverity.ERROR)
    if blocking:
        raise OntologyImportError(
            "元数据包含阻断问题",
            details={"diagnostics": [item.model_dump(mode="json") for item in blocking]},
        )
```

Do not include complete source rows in messages or exception details.

- [ ] **Step 6: Write failing override tests**

Use a synthetic JSON file to verify description and aliases can be corrected, unknown fields fail, and `physical_name` cannot be overridden.

- [ ] **Step 7: Implement local overrides**

Define:

```python
class FieldOverride(FrozenModel):
    label: str | None = None
    description: str | None = None
    source_type: str | None = None
    aliases: tuple[str, ...] = ()


class MetadataOverrides(FrozenModel):
    fields: dict[str, FieldOverride] = Field(default_factory=dict)
```

Load JSON by default and YAML for `.yaml`/`.yml`, reject any keys not modeled by Pydantic `extra="forbid"`, and locate fields case-insensitively without changing their physical names.

- [ ] **Step 8: Run focused tests and quality checks**

Run:

```powershell
pytest tests/ontology_core/test_tabular_metadata.py -q
ruff check ontology_core/tabular_metadata.py ontology_core/errors.py tests/ontology_core/test_tabular_metadata.py
black --check ontology_core/tabular_metadata.py ontology_core/errors.py tests/ontology_core/test_tabular_metadata.py
```

Expected: all focused tests and checks pass.

- [ ] **Step 9: Commit**

```powershell
git add ontology_core/tabular_metadata.py ontology_core/errors.py tests/ontology_core/test_tabular_metadata.py
git commit -m "feat: 增加表格元数据解析与诊断"
```

---

### Task 2: 本体包生成与安全发布

**Files:**
- Create: `ontology_core/metadata_package.py`
- Modify: `ontology_core/__init__.py`
- Test: `tests/ontology_core/test_metadata_package.py`

**Interfaces:**
- Consumes: `TabularMetadataDraft`, `ImportDiagnostic`, `analyze_metadata`, `raise_for_blocking_diagnostics`
- Produces: `PackageGenerationOptions`
- Produces: `MetadataImportResult`
- Produces: `generate_metadata_package(draft: TabularMetadataDraft, target: Path, options: PackageGenerationOptions, *, replace: bool = False) -> MetadataImportResult`

- [ ] **Step 1: Write failing graph generation test**

Create a two-field synthetic draft and assert repository inspection returns exactly one concept, two properties, one data source, three mappings and zero rules. Assert `RDFS.comment` survives resolver parsing and physical namespace, object name and field names preserve case.

- [ ] **Step 2: Run generation test and verify RED**

Run: `pytest tests/ontology_core/test_metadata_package.py::test_generate_metadata_package_builds_publishable_semantics -q`

Expected: FAIL during import because `ontology_core.metadata_package` does not exist.

- [ ] **Step 3: Implement options, type mapping and RDF graph builders**

Define stable options and result types:

```python
class PackageGenerationOptions(FrozenModel):
    package_id: str
    base_uri: str
    version: str = "0.1.0"
    physical_namespace: str
    platform_type: str = "generic"
    dialect: str = "generic"


class MetadataImportResult(FrozenModel):
    target: Path
    diagnostics: tuple[ImportDiagnostic, ...]
    inspection: PackageInspection
```

Map normalized input types to XSD (`string -> xsd:string`, integer family to `xsd:integer`, decimal family to `xsd:decimal`, date/datetime/boolean to matching XSD). Unknown types remain `xsd:string` only when accompanied by `unknown_field_type` warning.

Use RDFLib graphs and `Literal` for escaping. Concept/property URIs derive from a URL-quoted stable semantic segment, never from unchecked Turtle interpolation. Use one generated data source, one object mapping and one field mapping per property. Write field descriptions as `rdfs:comment`; do not emit business-rule triples.

- [ ] **Step 4: Write failing safety and atomicity tests**

Cover malicious labels being serialized as literals, credentials absent from generated source triples, blocking diagnostics producing no target, validation failure preserving an existing target, replace success removing temporary/backup directories, and replace=false refusing a non-empty target.

- [ ] **Step 5: Implement staged generation and atomic target switch**

Create a random sibling staging directory, initialize its manifest/core/shapes using `initialize_package`, write generated `domain.ttl` and `mappings.ttl`, leave `rules.ttl` empty, then validate with `OntologyRepository.publish(staging)` before switching.

For `replace=True`, validate that target, staging and backup are real sibling directories without links/reparse points. Rename existing target to a random backup, rename staging to target, restore backup if the second rename fails, and remove backup only after `OntologyRepository.publish(target)` succeeds. Any failure must leave either the old valid target or the new valid target in place.

- [ ] **Step 6: Export public interfaces**

Add `PackageGenerationOptions`, `MetadataImportResult`, `generate_metadata_package`, parser DTOs and parser functions to `ontology_core/__init__.py` and its `__all__` list.

- [ ] **Step 7: Run focused and ontology-core regression tests**

Run:

```powershell
pytest tests/ontology_core/test_metadata_package.py tests/ontology_core/test_public_api.py -q
pytest tests/ontology_core -q
ruff check ontology_core tests/ontology_core/test_metadata_package.py
black --check ontology_core tests/ontology_core/test_metadata_package.py
```

Expected: focused tests and the complete ontology-core suite pass.

- [ ] **Step 8: Commit**

```powershell
git add ontology_core/metadata_package.py ontology_core/__init__.py tests/ontology_core/test_metadata_package.py tests/ontology_core/test_public_api.py
git commit -m "feat: 生成并安全发布元数据本体包"
```

---

### Task 3: `import-tabular` CLI

**Files:**
- Modify: `ontology_core/cli.py`
- Modify: `tests/ontology_core/test_cli.py`

**Interfaces:**
- Consumes: Task 1 parser/override/diagnostic functions and Task 2 package generator.
- Produces: `python -m ontology_core import-tabular INPUT TARGET ...`

- [ ] **Step 1: Write failing CLI success test**

Invoke `main([...])` with a synthetic TSV, package options, namespace and `--json`. Assert exit code zero, JSON contains `status: imported`, diagnostics counts, package counts and target path; inspect generated package independently.

- [ ] **Step 2: Write failing CLI error tests**

Cover malformed input, blocking diagnostics, unknown override field, existing target without `--replace` and JSON-safe errors. Assert stderr never contains the complete TSV row.

- [ ] **Step 3: Run CLI tests and verify RED**

Run: `pytest tests/ontology_core/test_cli.py -q`

Expected: FAIL because `import-tabular` is not a recognized command.

- [ ] **Step 4: Implement CLI handler and arguments**

Add:

```text
ontology-core import-tabular INPUT TARGET
  --package-id PACKAGE_ID
  --base-uri BASE_URI
  --version VERSION
  --physical-namespace NAMESPACE
  --platform-type PLATFORM
  --dialect DIALECT
  [--overrides PATH]
  [--report PATH]
  [--replace]
  [--json]
```

The handler reads UTF-8 input, parses, applies optional overrides, analyzes, generates, then optionally writes a JSON report containing only structured diagnostics and counts. Parent directories may be created, but input and override files are never copied.

- [ ] **Step 5: Run focused CLI tests and checks**

Run:

```powershell
pytest tests/ontology_core/test_cli.py -q
ruff check ontology_core/cli.py tests/ontology_core/test_cli.py
black --check ontology_core/cli.py tests/ontology_core/test_cli.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add ontology_core/cli.py tests/ontology_core/test_cli.py
git commit -m "feat: 增加表格元数据导入命令"
```

---

### Task 4: 属性驱动的概念推断与失败关闭

**Files:**
- Modify: `ontology_core/planner.py`
- Modify: `tests/ontology_core/test_planner.py`

**Interfaces:**
- Consumes: existing `OntologyResolver.list_concepts()` and `list_properties(concept_uri)`.
- Produces: planner behavior that chooses a directly named concept first, otherwise infers one unique concept from matched property labels/short names.

- [ ] **Step 1: Write failing property-inference tests**

Add catalogs with two concepts and distinct properties. Assert a query containing two property labels but no concept label selects the unique owning concept and only those properties. Add a tie case where properties belong to two concepts and assert `AmbiguousQueryConceptError`.

- [ ] **Step 2: Write failing unknown-property safety test**

Assert a query that directly names a concept but contains no known property raises `UnsupportedQueryPlanError("未匹配到查询属性")` rather than selecting every mapped field. Keep a separate explicit test for the intended behavior if a future `select_all` flag is introduced; do not infer select-all from missing matches.

- [ ] **Step 3: Run planner tests and verify RED**

Run: `pytest tests/ontology_core/test_planner.py -q`

Expected: property-only query raises no-concept error and unknown-property query selects all fields.

- [ ] **Step 4: Implement deterministic property inference**

Build `(concept, matched_properties, total_score)` candidates by matching each concept's property aliases. Direct concept-label match remains highest priority. When no concept label matches, require exactly one best concept; equal winners raise ambiguity. Require at least one matched property for normal plans and keep mapping availability checks unchanged.

Do not match `description` automatically: descriptions are evidence and quality inputs, while only labels, short names and later confirmed aliases are safe query aliases.

- [ ] **Step 5: Run planner, compiler and shadow regression tests**

Run:

```powershell
pytest tests/ontology_core/test_planner.py tests/ontology_core/test_compiler.py tests/test_ontology_shadow.py -q
ruff check ontology_core/planner.py tests/ontology_core/test_planner.py
black --check ontology_core/planner.py tests/ontology_core/test_planner.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add ontology_core/planner.py tests/ontology_core/test_planner.py
git commit -m "feat: 通过本体属性推断查询概念"
```

---

### Task 5: 本地真实导入、泛化验收和服务切换

**Files:**
- Local only: `.local/ontology-imports/user-table-v1/overrides.json`
- Local only: `.local/ontology-imports/user-table-v1/report.json`
- Local only: `.local/ontology-packages/user-table-v1/`
- Modify: `docs/project-journal/2026-08.md`

**Interfaces:**
- Consumes: user attachment path, user-confirmed physical namespace and one user-confirmed description correction.
- Produces: validated local package configured through `ONTOLOGY__PACKAGE_PATH`.

- [ ] **Step 1: Create ignored local override configuration**

Use `apply_patch` to create the override JSON under `.local/ontology-imports/`; include only the user-confirmed description correction. Verify with `git check-ignore -v` that the file is ignored before continuing.

- [ ] **Step 2: Run real local import**

Invoke `python -m ontology_core import-tabular` with the attachment path, an ignored target directory, the confirmed physical namespace, a local package ID/base URI, `platform-type=hive`, `dialect=generic`, local overrides, local report and `--replace --json`.

Expected: one concept, attachment field count properties, one data source, field count plus one mappings, zero rules, and no blocking diagnostics.

- [ ] **Step 3: Validate privacy and package integrity**

Run `python -m ontology_core validate .local/ontology-packages/user-table-v1 --json` and `python -m ontology_core inspect .local/ontology-packages/user-table-v1 --json`. Run `git status --short` and `git check-ignore -v` for all local outputs. Search tracked diffs for the real physical identifiers and fail the task if any are present.

- [ ] **Step 4: Run novel query integration checks**

Instantiate `OntologyRuntime` against the generated local package and execute at least three user-approved combinations that were not stored as SQL templates: two-field selection, partition plus status selection, and three-field selection. Assert generated SQL references the confirmed full physical table and exactly the requested mapped fields. Add one unknown-field query and assert safe non-generation.

- [ ] **Step 5: Run necessary project verification**

Run:

```powershell
pytest tests/ontology_core tests/test_ontology_shadow.py tests/test_orchestrator.py tests/test_conversation.py -q
npm run build
git diff --check
```

Run the frontend build from `frontend/`. Expected: all selected Python tests pass and Vite exits zero. Do not run extra review agents.

- [ ] **Step 6: Record reusable engineering evidence**

Append a generic, non-business-specific entry to `docs/project-journal/2026-08.md` covering: separating engine from ontology content, metadata conflict diagnostics, ignored local packages, atomic publication, and novel-query validation. Do not record real identifiers or descriptions.

- [ ] **Step 7: Commit tracked documentation**

```powershell
git add docs/project-journal/2026-08.md
git commit -m "docs: 记录元数据本体导入实践"
```

- [ ] **Step 8: Restart backend with the imported package and verify runtime**

Stop only the process listening on the backend development port after resolving its exact PID. Start backend with `ONTOLOGY__PACKAGE_PATH` pointing to the generated ignored package and `ONTOLOGY__SHADOW_ENABLED=true`; keep the existing frontend or restart it if unavailable. Verify backend health, frontend HTTP 200 and OpenAPI `ontology_shadow` field.

- [ ] **Step 9: Hand off for visual testing**

Report the local URL, three concrete natural-language test prompts, expected ontology evidence, branch name, latest commits, test totals and known non-blocking warnings. Keep branch and worktree as-is; do not merge or push.
