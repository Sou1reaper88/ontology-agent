# Ontology Shadow SQL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有聊天回答中增加不影响 legacy SQL 的本体驱动 SQL 影子预览，并展示确定性的差异和本体证据。

**Architecture:** 外部本体包经 `OntologyRepository` 发布为快照，`OntologyResolver` 为 Planner 提供只读语义和映射查询，Planner 生成数据库无关 `QueryPlan`，编译器注册表按数据源 dialect 生成 SQL。Agent 完成 legacy SQL 后调用独立 Shadow Service，结构化结果存入现有 trace JSON，API 和前端从 trace 展示双 SQL 对比。

**Tech Stack:** Python 3.11、Pydantic、RDFLib、FastAPI、LangGraph、pytest、React 18、TypeScript、Ant Design、Vite。

## Global Constraints

- 只实施设计方案 A；legacy SQL 的生成、执行和 `QueryHistory` 行为保持不变。
- 本体 SQL 只允许预览和复制，不创建执行入口或 `QueryHistory`。
- 本体包通过 `ONTOLOGY__PACKAGE_PATH` 从外部目录读取；生产代码不得硬编码演示表、字段和规则。
- 首期只支持单一概念、单一数据源，不生成多表 JOIN。
- Planner 与数据库无关；SQL 方言通过 `SqlCompiler` 协议和注册表扩展。
- 无匹配、歧义、缺失映射、不支持规则或运行时异常必须 fail closed，不能猜测 SQL，也不能影响 legacy 成功结果。
- 演示包仅写入 Git 忽略的 `.local/ontology-packages/`。
- 每个实现任务严格执行 RED → GREEN → REFACTOR，并在逻辑任务完成后自动 Git 提交。

---

### Task 1: Resolver 映射查询与数据库无关 QueryPlan

**Files:**
- Create: `ontology_core/query_plan.py`
- Create: `ontology_core/planner.py`
- Modify: `ontology_core/resolver.py`
- Modify: `ontology_core/__init__.py`
- Test: `tests/ontology_core/test_resolver.py`
- Test: `tests/ontology_core/test_planner.py`

**Interfaces:**
- Consumes: `OntologySnapshot.catalog`、`OntologyResolver.list_concepts/list_properties/list_rules`。
- Produces: `OntologyResolver.list_data_sources() -> tuple[DataSource, ...]`、`OntologyResolver.list_mappings(semantic_element_uri: str, data_source_uri: str | None = None) -> tuple[PhysicalMapping, ...]`、`OntologyPlanner.plan(query: str) -> QueryPlan`。

- [ ] **Step 1: Write failing tests**

```python
def test_resolver_lists_sources_and_enabled_mappings_by_priority(resolver):
    assert [item.short_name for item in resolver.list_data_sources()] == ["Warehouse"]
    assert [item.priority for item in resolver.list_mappings(PROPERTY_URI)] == [20, 10]


def test_planner_builds_single_concept_plan_from_labels_and_mappings(resolver):
    plan = OntologyPlanner(resolver).plan("查询客户编号")
    assert plan.concept.short_name == "Customer"
    assert [item.semantic.short_name for item in plan.selections] == ["CustomerId"]
    assert plan.object_binding.object_name == "customer_snapshot"
    assert plan.selections[0].binding.field_name == "customer_id"
```

- [ ] **Step 2: Verify RED**

Run: `D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/ontology_core/test_resolver.py tests/ontology_core/test_planner.py -q`

Expected: FAIL because the new resolver methods and planner types do not exist.

- [ ] **Step 3: Implement minimal immutable plan and deterministic planner**

```python
class BoundSelection(FrozenModel):
    semantic: Property
    binding: PhysicalMapping


class QueryPlan(FrozenModel):
    concept: Concept
    data_source: DataSource
    object_binding: PhysicalMapping
    selections: tuple[BoundSelection, ...]
    rules: tuple[BusinessRule, ...] = ()
```

Resolver indexes data sources and enabled mappings. Mapping order is `priority DESC, normalized short_name, uri`. Planner matches normalized labels and short names as query substrings, requires exactly one winning concept, limits properties to that concept, and requires compatible concept/property mappings from one source. Typed planner errors represent `no_match`, `ambiguous`, and `unsupported`.

- [ ] **Step 4: Verify GREEN**

Run: `D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/ontology_core/test_resolver.py tests/ontology_core/test_planner.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add ontology_core/query_plan.py ontology_core/planner.py ontology_core/resolver.py ontology_core/__init__.py tests/ontology_core/test_resolver.py tests/ontology_core/test_planner.py
git commit -m "feat: 增加本体查询计划器"
```

### Task 2: 可替换 SQL 编译器

**Files:**
- Create: `ontology_core/compiler.py`
- Modify: `ontology_core/query_plan.py`
- Modify: `ontology_core/__init__.py`
- Test: `tests/ontology_core/test_compiler.py`

**Interfaces:**
- Consumes: `QueryPlan`、`RuleExpression`、`PhysicalMapping`。
- Produces: `SqlCompiler.compile(plan: QueryPlan) -> CompiledQuery`、`CompilerRegistry.get(dialect: str | None) -> SqlCompiler`。

- [ ] **Step 1: Write failing tests**

```python
def test_generic_compiler_uses_only_plan_bindings(plan):
    compiled = GenericSqlCompiler().compile(plan)
    assert compiled.sql == (
        'SELECT "customer_id" FROM "analytics"."customer_snapshot" '
        'WHERE "status_code" = \'ACTIVE\';'
    )


def test_compiler_escapes_literals(plan):
    assert "'O''Reilly'" in GenericSqlCompiler().compile(plan_with_literal("O'Reilly")).sql
```

Add parameterized cases for `eq/ne/gt/gte/lt/lte/in/between/is_null/all_of/any_of/not`, missing field mappings, unsupported datatype, invalid identifier and unknown dialect.

- [ ] **Step 2: Verify RED**

Run: `D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/ontology_core/test_compiler.py -q`

Expected: FAIL because `ontology_core.compiler` does not exist.

- [ ] **Step 3: Implement protocol, generic compiler and registry**

```python
class SqlCompiler(Protocol):
    def compile(self, plan: QueryPlan) -> CompiledQuery: ...


class CompilerRegistry:
    def __init__(self, compilers: Mapping[str, SqlCompiler]) -> None: ...
    def get(self, dialect: str | None) -> SqlCompiler: ...
```

Quote each identifier component, serialize RDF literals by datatype, escape text apostrophes, and resolve every rule property through plan bindings. Missing bindings, unsupported operations/datatypes and unknown dialects raise safe `OntologyCompileError`.

- [ ] **Step 4: Verify GREEN**

Run: `D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/ontology_core/test_compiler.py tests/ontology_core/test_planner.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add ontology_core/compiler.py ontology_core/query_plan.py ontology_core/__init__.py tests/ontology_core/test_compiler.py
git commit -m "feat: 增加可替换本体 SQL 编译器"
```

### Task 3: 外部包运行时与 Shadow Service

**Files:**
- Create: `agent/ontology_shadow.py`
- Modify: `config/settings.py`
- Modify: `.env.example`
- Modify: `.gitignore`
- Test: `tests/test_ontology_shadow.py`

**Interfaces:**
- Consumes: repository、resolver、planner、compiler registry。
- Produces: `OntologyShadowService.preview(query: str, legacy_sql: str | None) -> OntologyShadowResult`、`get_ontology_shadow_service()`。

- [ ] **Step 1: Write failing tests**

```python
def test_shadow_sql_does_not_depend_on_legacy_sql(service):
    first = service.preview("查询客户编号", "SELECT legacy_one;")
    second = service.preview("查询客户编号", "SELECT other_legacy;")
    assert first.ontology_sql == second.ontology_sql
    assert first.status == "generated"
    assert first.diff.changed is True


def test_shadow_failure_is_safe(broken_service):
    result = broken_service.preview("查询客户编号", "SELECT 1;")
    assert result.status == "unavailable"
    assert result.ontology_sql is None
    assert "C:\\" not in result.summary
```

Add disabled, invalid package, no match, ambiguity and unsupported mapping cases.

- [ ] **Step 2: Verify RED**

Run: `D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/test_ontology_shadow.py -q`

Expected: FAIL because the service and settings do not exist.

- [ ] **Step 3: Implement settings, lazy runtime, result model and diff**

Add `package_path: str = ""` and `shadow_enabled: bool = True` to `OntologySettings`; document `ONTOLOGY__PACKAGE_PATH` and `ONTOLOGY__SHADOW_ENABLED`; ignore `.local/`.

```python
class OntologyShadowResult(FrozenModel):
    status: Literal["generated", "no_match", "ambiguous", "unsupported", "unavailable"]
    ontology_sql: str | None = None
    summary: str
    diff: SqlDiff
    evidence: OntologyEvidence
    package: ShadowPackage | None = None
```

Lazy-publish the configured package once under a lock. Return package ID/version/12-character digest only. Compare normalized SQL and table names deterministically. Known domain errors map to safe statuses; unexpected exceptions map to `unavailable` and log exception type only.

- [ ] **Step 4: Verify GREEN**

Run: `D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/test_ontology_shadow.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add agent/ontology_shadow.py config/settings.py .env.example .gitignore tests/test_ontology_shadow.py
git commit -m "feat: 增加本体 SQL 影子服务"
```

### Task 4: Agent、trace 与对话 API 接入

**Files:**
- Modify: `agent/orchestrator.py`
- Modify: `api/routes/conversation.py`
- Modify: `tests/test_orchestrator.py`
- Modify: `tests/test_conversation.py`

**Interfaces:**
- Consumes: `get_ontology_shadow_service().preview(query, legacy_sql)`。
- Produces: `output["ontology_shadow"]`、trace `ontology_shadow` step、`MessageOut.ontology_shadow`。

- [ ] **Step 1: Write failing Agent and API tests**

```python
def test_run_agent_appends_shadow_without_changing_legacy_sql(monkeypatch):
    monkeypatch.setattr(orchestrator, "get_ontology_shadow_service", fake_service)
    output = run_agent("查询客户编号")
    assert output["sql"] == EXPECTED_LEGACY_SQL
    assert output["ontology_shadow"]["status"] == "generated"
    assert output["trace"][-1]["node"] == "ontology_shadow"
```

Also assert shadow exceptions do not fail conversations, historical and polling payloads match, and `query_id` still references only legacy SQL.

- [ ] **Step 2: Verify RED**

Run: `D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/test_orchestrator.py tests/test_conversation.py -q`

Expected: FAIL because Agent/API do not expose the shadow result.

- [ ] **Step 3: Implement post-graph shadow step and trace extraction**

After graph invocation, call the service only when legacy SQL exists. Append a step labeled `本体规划与编译` with safe summary and `payload`; invoke `on_step(step)`. Preserve every existing output field.

```python
def _extract_ontology_shadow(trace: list[dict] | None) -> dict | None:
    return next(
        (item.get("payload") for item in reversed(trace or [])
         if item.get("node") == "ontology_shadow"),
        None,
    )
```

Use the helper in historical detail and polling responses. Do not add a database column or migration.

- [ ] **Step 4: Verify GREEN**

Run: `D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/test_orchestrator.py tests/test_conversation.py tests/test_health.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add agent/orchestrator.py api/routes/conversation.py tests/test_orchestrator.py tests/test_conversation.py
git commit -m "feat: 接入本体 SQL 影子链路"
```

### Task 5: 聊天页 SQL 对比面板

**Files:**
- Create: `frontend/src/components/OntologyComparison.tsx`
- Modify: `frontend/src/pages/Chat.tsx`

**Interfaces:**
- Consumes: historical/polling `ontology_shadow` payload。
- Produces: side-by-side legacy/ontology SQL UI; ontology side has copy only.

- [ ] **Step 1: Add import/render and verify RED build**

```tsx
<OntologyComparison legacySql={m.sql} result={m.ontology_shadow} />
```

Run: `npm run build`

Expected: FAIL because component and message field do not exist.

- [ ] **Step 2: Implement typed comparison component**

Render `generated` as responsive two-column Ant Design Cards with SQL, package badge, diff summary and evidence Tags. Render non-generated statuses as Alert. The ontology card contains a copy button and text `影子预览，不会自动执行`; it receives no execution callback.

- [ ] **Step 3: Wire historical and polling payloads**

Extend `Msg` with `ontology_shadow`. Copy polling payload into the generating message. Use the comparison panel when payload exists; preserve legacy-only UI otherwise.

- [ ] **Step 4: Verify GREEN build**

Run: `npm run build`

Expected: PASS without TypeScript/Vite errors.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/OntologyComparison.tsx frontend/src/pages/Chat.tsx
git commit -m "feat: 展示本体 SQL 影子对比"
```

### Task 6: 本机演示包、完整验证与可视验收

**Files:**
- Create, do not commit: `.local/ontology-packages/shadow-demo/manifest.yaml`
- Create, do not commit: `.local/ontology-packages/shadow-demo/*.ttl`
- Modify: `docs/project-journal/2026-08.md`
- Modify: `docs/career/project-story.md`

- [ ] **Step 1: Create and validate a local-only neutral package**

Run `python -m ontology_core init .local/ontology-packages/shadow-demo --package-id local.shadow-demo --base-uri https://example.invalid/local-shadow/`, then use ignored TTL files to define one neutral concept, two properties, one active rule, one generic source, one object mapping and two field mappings. Include no real business identifiers or credentials.

Run:

```powershell
D:\Projects\ontology-agent\.venv\Scripts\python.exe -m ontology_core validate .local/ontology-packages/shadow-demo
D:\Projects\ontology-agent\.venv\Scripts\python.exe -m ontology_core inspect .local/ontology-packages/shadow-demo
```

Expected: valid with non-zero concept, property, rule, source and mapping counts.

- [ ] **Step 2: Run complete verification**

```powershell
D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest -q
D:\Projects\ontology-agent\.venv\Scripts\python.exe -m ruff check .
D:\Projects\ontology-agent\.venv\Scripts\python.exe -m black --check .
npm run build
git diff --check
```

Expected: all exit 0.

- [ ] **Step 3: Record project/career evidence and commit**

Document the difficulty “new ontology core existed beside legacy Agent but produced no visible value”, the solution “shadow mode + neutral plan + replaceable compiler”, verification counts, and measurable evaluation plan. Do not include local package contents or paths.

```powershell
git add docs/project-journal/2026-08.md docs/career/project-story.md
git commit -m "docs: 记录本体影子链路实践"
```

- [ ] **Step 4: Start and verify services**

Start backend with `ONTOLOGY__PACKAGE_PATH` pointing to the ignored package and frontend on port 5199. Verify backend health and chat page return HTTP 200. In the browser confirm the neutral prompt displays different legacy/ontology SQL, evidence and no ontology execute button.

## Plan Self-Review

- Spec coverage: external package、resolver、neutral plan、compiler protocol、shadow isolation、trace persistence、API、UI、no execution、tests and local demo map to Tasks 1–6.
- Placeholder scan: no placeholder markers or undecided implementation behavior remains.
- Type consistency: `QueryPlan` flows Task 1 → Tasks 2–3; `OntologyShadowResult` flows Task 3 → Tasks 4–5.
- Scope: multi-table JOIN、online publishing、hot reload and legacy replacement remain excluded.
