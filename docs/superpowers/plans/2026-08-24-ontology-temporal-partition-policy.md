# 本体驱动时间分区策略 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让声明了时间分区策略的本体查询根据系统时间或用户明确时间生成有界分区谓词，并在聊天页面展示完整、可解释的账期决策链。

**Architecture:** 本体包新增 `TemporalPartitionPolicy`，元数据覆盖文件显式声明分区字段、粒度和默认算法；确定性时间解析器把自然语言与系统时间转换为规范化时间意图，规划器将其绑定到物理字段并写入数据库无关的 `QueryPlan`。SQL 编译器只编译结构化过滤条件，影子服务返回时间证据，前端直接展示后端决策。

**Tech Stack:** Python 3.11+、Pydantic v2、RDFLib 7.6、PySHACL 0.40、pytest 8、Ruff、Black、FastAPI、React 18、TypeScript 5.5、Ant Design 5、Vite 5

## Global Constraints

- 不根据 `P_MON`、`P_DAY` 等字段名在 Python 中硬编码分区策略。
- 不实现、也不为“查询数据库最新可用分区”预留接口。
- 系统时间 `2026-08-24` 必须推算 `p_day=20260822`、`p_mon=202607`。
- 用户明确指定时间时，用户时间优先于默认推算。
- 同一张表最多存在一个激活的时间分区粒度和策略。
- 月表默认使用上一个完整自然月，日表默认使用 `T-2`。
- 声明了时间策略的查询对象遇到冲突、无边界、非法时间或缺失映射时必须失败关闭，不得生成无分区条件 SQL。
- 编译器不得读取系统时钟、解析自然语言或实现业务账期口径。
- 真实附件、表名、字段名、字段描述、覆盖配置、诊断报告和生成包不得进入 Git。
- 原有 SQL 链路继续运行，本体 SQL 仍为影子预览，不自动执行。
- 每个独立逻辑改动通过聚焦测试后自动 Git 提交；未经明确授权不推送或合并。
- 完成代码与必要测试后先启动服务供用户验收，不执行额外多轮审查代理。

---

## File Structure

- Modify `ontology_core/semantic_models.py`: 时间策略枚举、DTO、目录与计数字段。
- Modify `ontology_core/vocabulary.py`: 时间策略 RDF 类型和谓词常量。
- Modify `ontology_core/resources/core.ttl`: 时间策略 OWL 词汇声明。
- Modify `ontology_core/resources/shapes.ttl`: 时间策略 SHACL 结构与枚举约束。
- Modify `ontology_core/semantic_parser.py`: 时间策略解析、引用验证和唯一性验证。
- Modify `ontology_core/resolver.py`: 按概念读取唯一激活时间策略。
- Modify `ontology_core/inspection.py`: 统计并列出时间策略。
- Modify `ontology_core/__init__.py`: 导出稳定公共类型。
- Modify `ontology_core/tabular_metadata.py`: 本地覆盖中的时间策略声明和字段引用验证。
- Modify `ontology_core/metadata_package.py`: 将确认后的策略发布到 `rules.ttl`。
- Create `ontology_core/temporal.py`: 严格系统日期解析、中文时间意图解析、冲突与无边界检测。
- Modify `ontology_core/errors.py`: 增加稳定的时间意图错误类型。
- Modify `ontology_core/query_plan.py`: 已解析过滤条件和时间决策证据。
- Modify `ontology_core/compiler.py`: 编译 `ResolvedFilter` 并执行分区安全门槛。
- Modify `ontology_core/planner.py`: 组合本体策略、时间解析、字段映射和查询计划。
- Modify `agent/ontology_shadow.py`: 传递系统时间、映射澄清状态、返回账期证据。
- Modify `agent/orchestrator.py`: 将当前请求的 `system_time` 传入本体影子服务。
- Modify `frontend/src/components/OntologyComparison.tsx`: 显示业务账期决策卡片和澄清状态。
- Modify ontology-core and integration test files named in each task.
- Local only `.local/ontology-imports/user-table-v1/overrides.json`: 确认当前月表分区策略。
- Local only `.local/ontology-packages/user-table-v1/`: 重新发布当前本体包。
- Modify `docs/project-journal/2026-08.md`: 记录时间语义、失败关闭和可解释证据实践。

---

### Task 1: 时间分区本体模型、RDF 解析与约束

**Files:**
- Modify: `ontology_core/semantic_models.py`
- Modify: `ontology_core/vocabulary.py`
- Modify: `ontology_core/resources/core.ttl`
- Modify: `ontology_core/resources/shapes.ttl`
- Modify: `ontology_core/semantic_parser.py`
- Modify: `ontology_core/resolver.py`
- Modify: `ontology_core/inspection.py`
- Modify: `ontology_core/__init__.py`
- Test: `tests/ontology_core/test_semantic_models.py`
- Test: `tests/ontology_core/test_semantic_parser.py`
- Test: `tests/ontology_core/test_resolver.py`
- Test: `tests/ontology_core/test_validator.py`
- Test: `tests/ontology_core/test_public_api.py`
- Test: `tests/ontology_core/test_repository.py`
- Test: `tests/ontology_core/test_cli.py`

**Interfaces:**
- Produces: `TemporalGrain.DAY`, `TemporalGrain.MONTH`
- Produces: `TemporalDefaultStrategy.T_MINUS_2`, `TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH`
- Produces: immutable `TemporalPartitionPolicy`
- Produces: `OntologyResolver.get_temporal_policy(concept_id: str) -> TemporalPartitionPolicy | None`
- Extends: `SemanticCatalog.temporal_policies` and `SemanticCounts.temporal_policies`

- [ ] **Step 1: Write failing semantic model tests**

Add exact model construction and immutability assertions:

```python
def test_temporal_partition_policy_is_typed_and_frozen() -> None:
    policy = TemporalPartitionPolicy(
        uri="https://example.invalid/ontology/MonthlyPolicy",
        short_name="MonthlyPolicy",
        label="月分区策略",
        labels=_text("月分区策略"),
        applies_to_uri="https://example.invalid/ontology/Record",
        partition_property_uri="https://example.invalid/ontology/AccountingMonth",
        grain=TemporalGrain.MONTH,
        default_strategy=TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH,
        allow_query_override=True,
        status="active",
        priority=100,
    )
    assert policy.grain is TemporalGrain.MONTH
    assert policy.default_strategy is TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH
    with pytest.raises(ValidationError):
        policy.priority = 1
```

- [ ] **Step 2: Run the model test and verify RED**

Run: `pytest tests/ontology_core/test_semantic_models.py::test_temporal_partition_policy_is_typed_and_frozen -q`

Expected: FAIL during import because the temporal policy types do not exist.

- [ ] **Step 3: Add temporal enums, policy DTO and catalog fields**

Implement the public types exactly:

```python
class TemporalGrain(StrEnum):
    DAY = "day"
    MONTH = "month"


class TemporalDefaultStrategy(StrEnum):
    T_MINUS_2 = "t_minus_2"
    PREVIOUS_COMPLETE_MONTH = "previous_complete_month"


class TemporalPartitionPolicy(SemanticElement):
    applies_to_uri: str
    partition_property_uri: str
    grain: TemporalGrain
    default_strategy: TemporalDefaultStrategy
    allow_query_override: bool = True
    status: str = "active"
    priority: int = 0
```

Add `temporal_policies: tuple[TemporalPartitionPolicy, ...] = ()` to `SemanticCatalog` and `temporal_policies: int = 0` to `SemanticCounts`. Export all three public types from `ontology_core/__init__.py`.

- [ ] **Step 4: Write failing RDF, SHACL and resolver tests**

Use anonymous Turtle only:

```turtle
ex:MonthlyPolicy a oa:TemporalPartitionPolicy ;
    oa:shortName "MonthlyPolicy" ;
    rdfs:label "Monthly policy" ;
    oa:appliesTo ex:Record ;
    oa:partitionProperty ex:AccountingMonth ;
    oa:partitionGrain "month" ;
    oa:defaultStrategy "previous_complete_month" ;
    oa:allowQueryOverride true ;
    oa:status "active" ;
    oa:priority 100 .
```

Assert parsing returns one typed policy and `get_temporal_policy(ex:Record)` returns it. Add invalid cases for unknown concept, property outside the concept, invalid grain/strategy pair, and two active policies for one concept; each package must fail validation or catalog parsing before publication.

- [ ] **Step 5: Extend vocabulary, core OWL and SHACL**

Add constants:

```python
TEMPORAL_PARTITION_POLICY = OA.TemporalPartitionPolicy
PARTITION_PROPERTY = OA.partitionProperty
PARTITION_GRAIN = OA.partitionGrain
DEFAULT_STRATEGY = OA.defaultStrategy
ALLOW_QUERY_OVERRIDE = OA.allowQueryOverride
```

Add `oa:TemporalPartitionPolicy` to `oa:SemanticElementShape` targets and declare the class/properties in `core.ttl`. Add a SHACL shape requiring exactly one `oa:appliesTo`, `oa:partitionProperty`, `oa:partitionGrain`, `oa:defaultStrategy`, and `oa:allowQueryOverride`; constrain grain to `("day" "month")`, strategy to `("t_minus_2" "previous_complete_month")`, and boolean type to `xsd:boolean`.

- [ ] **Step 6: Parse and validate temporal policies deterministically**

Add the policy marker to `_MARKERS`. Parse literals with the existing safe `_single_uri`, `_single_literal`, `_optional_literal` and `_element_fields` helpers. Validate:

```python
valid_pairs = {
    (TemporalGrain.DAY, TemporalDefaultStrategy.T_MINUS_2),
    (TemporalGrain.MONTH, TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH),
}
```

Require the partition property URI to be in `marked_property_uris` and its `concept_uri` to equal `applies_to_uri`. If more than one policy has `status == "active"` for one concept, append a stable `duplicate_temporal_policy` violation and reject the catalog.

- [ ] **Step 7: Add resolver, inspection and public API behavior**

Index policies by `applies_to_uri` and implement:

```python
def get_temporal_policy(self, concept_id: str) -> TemporalPartitionPolicy | None:
    concept = self.get_concept(concept_id)
    active = tuple(
        item
        for item in self._temporal_policies_by_concept.get(concept.uri, ())
        if item.status == "active"
    )
    return active[0] if active else None
```

Include policies in inspection counts and optional identifier listing. Update exact expected counts/signature dictionaries in repository, resolver, CLI and public API tests.

- [ ] **Step 8: Run focused and ontology-core regression tests**

Run:

```powershell
pytest tests/ontology_core/test_semantic_models.py tests/ontology_core/test_semantic_parser.py tests/ontology_core/test_resolver.py tests/ontology_core/test_validator.py tests/ontology_core/test_repository.py tests/ontology_core/test_public_api.py tests/ontology_core/test_cli.py -q
ruff check ontology_core tests/ontology_core
black --check ontology_core tests/ontology_core
```

Expected: selected tests, Ruff and Black all pass.

- [ ] **Step 9: Commit**

```powershell
git add ontology_core/semantic_models.py ontology_core/vocabulary.py ontology_core/resources/core.ttl ontology_core/resources/shapes.ttl ontology_core/semantic_parser.py ontology_core/resolver.py ontology_core/inspection.py ontology_core/__init__.py tests/ontology_core
git commit -m "feat: 增加本体时间分区策略模型"
```

---

### Task 2: 元数据覆盖与时间策略发布

**Files:**
- Modify: `ontology_core/tabular_metadata.py`
- Modify: `ontology_core/metadata_package.py`
- Modify: `tests/ontology_core/test_tabular_metadata.py`
- Modify: `tests/ontology_core/test_metadata_package.py`
- Modify: `tests/ontology_core/test_cli.py`

**Interfaces:**
- Consumes: `TemporalGrain`, `TemporalDefaultStrategy`, `TemporalPartitionPolicy` vocabulary.
- Produces: `TemporalPolicyOverride`
- Extends: `MetadataOverrides.temporal_policy` and `TabularMetadataDraft.temporal_policy`
- Produces: deterministic `rules.ttl` policy triples from confirmed local override.

- [ ] **Step 1: Write failing override tests**

Add JSON parsing and field validation tests:

```python
def test_apply_overrides_attaches_confirmed_temporal_policy(tmp_path: Path) -> None:
    path = tmp_path / "overrides.json"
    path.write_text(
        json.dumps(
            {
                "temporal_policy": {
                    "field": "ACCOUNTING_MONTH",
                    "grain": "month",
                    "default_strategy": "previous_complete_month",
                    "allow_query_override": True,
                }
            }
        ),
        encoding="utf-8",
    )
    draft = apply_metadata_overrides(_draft(), load_metadata_overrides(path))
    assert draft.temporal_policy is not None
    assert draft.temporal_policy.field == "ACCOUNTING_MONTH"
```

Add failures for an unknown field, `month + t_minus_2`, `day + previous_complete_month`, and extra keys. Assert no automatic strategy appears when overrides omit `temporal_policy`, even if a field label contains “时间分区”.

- [ ] **Step 2: Run override tests and verify RED**

Run: `pytest tests/ontology_core/test_tabular_metadata.py -q`

Expected: FAIL because `MetadataOverrides` rejects or ignores `temporal_policy`.

- [ ] **Step 3: Implement strict temporal override models**

Define:

```python
class TemporalPolicyOverride(FrozenModel):
    field: str
    grain: TemporalGrain
    default_strategy: TemporalDefaultStrategy
    allow_query_override: bool = True

    @model_validator(mode="after")
    def validate_pair(self) -> Self:
        expected = {
            TemporalGrain.DAY: TemporalDefaultStrategy.T_MINUS_2,
            TemporalGrain.MONTH: TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH,
        }
        if expected[self.grain] is not self.default_strategy:
            raise ValueError("时间分区粒度与默认策略不匹配")
        return self


class MetadataOverrides(FrozenModel):
    fields: dict[str, FieldOverride] = Field(default_factory=dict)
    temporal_policy: TemporalPolicyOverride | None = None
```

Configure override models with `extra="forbid"`. Resolve `field` case-insensitively to the preserved physical name and reject unknown fields through `OntologyImportError("时间分区策略引用了未知字段")`.

- [ ] **Step 4: Write failing package publication test**

Generate an anonymous package with a confirmed monthly policy and assert:

```python
resolver = OntologyResolver(repository.current())
concept = resolver.get_concept("DEMO_ENTITY_M")
policy = resolver.get_temporal_policy(concept.uri)
assert policy is not None
assert policy.partition_property_uri.endswith("/property/ACCOUNTING_MONTH")
assert result.inspection.counts.temporal_policies == 1
```

Also assert a draft without an override still produces zero policies.

- [ ] **Step 5: Generate policy triples into `rules.ttl`**

Add `_rules_graph(draft, options) -> Graph`. When `draft.temporal_policy` exists, resolve the confirmed field URI and emit a stable policy URI with `RDF.type OA.TemporalPartitionPolicy`, text fields, `oa:appliesTo`, `oa:partitionProperty`, grain, strategy, override boolean, active status and integer priority 100. Write this graph to the staging package before repository publication.

Do not inspect field names or labels to invent a policy when the override is absent.

- [ ] **Step 6: Run focused import tests and checks**

Run:

```powershell
pytest tests/ontology_core/test_tabular_metadata.py tests/ontology_core/test_metadata_package.py tests/ontology_core/test_cli.py -q
ruff check ontology_core/tabular_metadata.py ontology_core/metadata_package.py tests/ontology_core/test_tabular_metadata.py tests/ontology_core/test_metadata_package.py tests/ontology_core/test_cli.py
black --check ontology_core/tabular_metadata.py ontology_core/metadata_package.py tests/ontology_core/test_tabular_metadata.py tests/ontology_core/test_metadata_package.py tests/ontology_core/test_cli.py
```

Expected: all focused tests and checks pass.

- [ ] **Step 7: Commit**

```powershell
git add ontology_core/tabular_metadata.py ontology_core/metadata_package.py tests/ontology_core/test_tabular_metadata.py tests/ontology_core/test_metadata_package.py tests/ontology_core/test_cli.py
git commit -m "feat: 发布元数据时间分区策略"
```

---

### Task 3: 确定性中文时间意图解析

**Files:**
- Create: `ontology_core/temporal.py`
- Modify: `ontology_core/errors.py`
- Create: `tests/ontology_core/test_temporal.py`

**Interfaces:**
- Produces: `TemporalIntentSource`, `TemporalIntent`, `TemporalTarget`, `TemporalParseResult`
- Produces: `parse_system_date(value: str | None, *, today: date | None = None) -> date`
- Produces: `parse_temporal_intents(query: str, *, system_date: date, grain: TemporalGrain, default_strategy: TemporalDefaultStrategy, partition_target: TemporalTarget, other_targets: tuple[TemporalTarget, ...] = ()) -> TemporalParseResult`
- Produces: `TemporalIntentError(QueryPlanningError)` with safe `reason` details.

- [ ] **Step 1: Write failing system date and monthly default tests**

Add exact expectations:

```python
def test_parse_system_date_is_strict() -> None:
    assert parse_system_date("2026-08-24") == date(2026, 8, 24)
    with pytest.raises(TemporalIntentError, match="系统时间格式无效"):
        parse_system_date("2026/08/24")


def test_monthly_query_without_time_uses_previous_complete_month() -> None:
    result = parse_temporal_intents(
        "查询客户编码",
        system_date=date(2026, 8, 24),
        grain=TemporalGrain.MONTH,
        default_strategy=TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH,
        partition_target=_partition_target(),
    )
    assert result.partition.start == "202607"
    assert result.partition.end == "202607"
    assert result.partition.source is TemporalIntentSource.ONTOLOGY_DEFAULT
```

Add a day default assertion for `20260822`.

The day test must pass `grain=TemporalGrain.DAY` and
`default_strategy=TemporalDefaultStrategy.T_MINUS_2`. Add invalid-pair tests proving the
parser rejects `month + t_minus_2` and `day + previous_complete_month` instead of selecting a
strategy from the grain in Python.

- [ ] **Step 2: Run temporal tests and verify RED**

Run: `pytest tests/ontology_core/test_temporal.py -q`

Expected: FAIL during import because `ontology_core.temporal` does not exist.

- [ ] **Step 3: Implement strict date parsing and immutable intent DTOs**

Define:

```python
class TemporalIntentSource(StrEnum):
    EXPLICIT_ABSOLUTE = "explicit_absolute"
    EXPLICIT_RELATIVE = "explicit_relative"
    ONTOLOGY_DEFAULT = "ontology_default"


class TemporalTarget(FrozenModel):
    property_uri: str
    aliases: tuple[str, ...]
    datatype_uri: str


class TemporalIntent(FrozenModel):
    target_property_uri: str
    start: str
    end: str
    source: TemporalIntentSource
    matched_text: str | None = None
    explanation: str


class TemporalParseResult(FrozenModel):
    partition: TemporalIntent
    property_intents: tuple[TemporalIntent, ...] = ()
```

`parse_system_date` accepts only exact ISO `YYYY-MM-DD`; `None` uses the supplied `today` or `date.today()`. Invalid non-empty values raise `TemporalIntentError("系统时间格式无效", details={"reason": "invalid_system_time"})` without embedding the raw value.

- [ ] **Step 4: Write failing absolute, range and relative month tests**

Cover this complete matrix with `system_date=date(2026, 8, 24)`:

```python
cases = {
    "查询2026年6月数据": ("202606", "202606", "explicit_absolute"),
    "查询202606账期": ("202606", "202606", "explicit_absolute"),
    "查询2026-06数据": ("202606", "202606", "explicit_absolute"),
    "查询6月用户": ("202606", "202606", "explicit_absolute"),
    "查询2026年4月至6月数据": ("202604", "202606", "explicit_absolute"),
    "查询本月数据": ("202608", "202608", "explicit_relative"),
    "查询上月数据": ("202607", "202607", "explicit_relative"),
    "查询最近3个账期": ("202605", "202607", "explicit_relative"),
}
```

Also cover this day-grain matrix with the same system date:

```python
day_cases = {
    "查询2026年8月20日数据": ("20260820", "20260820", "explicit_absolute"),
    "查询2026-08-20数据": ("20260820", "20260820", "explicit_absolute"),
    "查询2026-08-20至2026-08-22数据": ("20260820", "20260822", "explicit_absolute"),
    "查询今天数据": ("20260824", "20260824", "explicit_relative"),
    "查询昨天数据": ("20260823", "20260823", "explicit_relative"),
    "查询前天数据": ("20260822", "20260822", "explicit_relative"),
}
```

- [ ] **Step 5: Implement deterministic month/day parsing**

Use compiled regular expressions with named groups for fully qualified month, compact month, dashed month, yearless month, closed month range, relative month and recent-N-period forms. Validate real calendar values with `date`; normalize month to `YYYYMM` and day to `YYYYMMDD`. For `最近 N 个账期`, use the default complete period as the end and subtract `N-1` periods for the start.

The default branch must switch on the supplied `default_strategy`, verify it is compatible with
the supplied `grain`, and reject invalid pairs. It must not derive the strategy from the grain.

Do not send text to an LLM and do not evaluate arbitrary expressions.

- [ ] **Step 6: Write failing conflict, unbounded and property-binding tests**

Assert:

```python
with pytest.raises(TemporalIntentError) as conflict:
    parse_temporal_intents(
        "查询2026年5月用户，账期按202606",
        system_date=SYSTEM_DATE,
        grain=TemporalGrain.MONTH,
        default_strategy=TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH,
        partition_target=_partition_target(),
    )
assert conflict.value.details["reason"] == "conflicting_partition_time"

with pytest.raises(TemporalIntentError) as unbounded:
    parse_temporal_intents(
        "查询全部历史用户，不限时间",
        system_date=SYSTEM_DATE,
        grain=TemporalGrain.MONTH,
        default_strategy=TemporalDefaultStrategy.PREVIOUS_COMPLETE_MONTH,
        partition_target=_partition_target(),
    )
assert unbounded.value.details["reason"] == "unbounded_time"
```

Add `查询2026年6月入网、账期为202607的用户` with an `入网日期` `TemporalTarget`; assert the partition resolves to `202607` and the property intent targets the入网日期 URI. Add a string-typed business date target and assert `unsupported_business_date_type` rather than silently dropping it.

- [ ] **Step 7: Implement target binding and failure-closed rules**

Normalize target aliases with existing `normalize_text`. A time expression directly adjacent to a non-partition temporal alias binds to that property. Explicit `账期`/`分区` cues bind to the partition. Bare “N 月数据/用户” binds to the partition. More than one non-range value for one target raises conflict. `全部历史`, `不限时间`, `不限制账期` and `全量数据` raise `unbounded_time`.

For non-partition business dates, support only `xsd:date` in this task; month intent becomes first through last calendar day. Other datatypes raise `unsupported_business_date_type`, preserving correctness until a confirmed physical date format exists.

- [ ] **Step 8: Run focused tests and checks**

Run:

```powershell
pytest tests/ontology_core/test_temporal.py -q
ruff check ontology_core/temporal.py ontology_core/errors.py tests/ontology_core/test_temporal.py
black --check ontology_core/temporal.py ontology_core/errors.py tests/ontology_core/test_temporal.py
```

Expected: all temporal tests and checks pass.

- [ ] **Step 9: Commit**

```powershell
git add ontology_core/temporal.py ontology_core/errors.py tests/ontology_core/test_temporal.py
git commit -m "feat: 解析确定性业务时间意图"
```

---

### Task 4: 查询计划过滤条件与编译安全门槛

**Files:**
- Modify: `ontology_core/query_plan.py`
- Modify: `ontology_core/compiler.py`
- Modify: `tests/ontology_core/test_compiler.py`

**Interfaces:**
- Consumes: `BoundProperty`, `RuleOperator`, `RdfLiteral`, `TemporalPartitionPolicy`.
- Produces: `ResolvedFilter`, `TemporalDecision`.
- Extends: `QueryPlan.filters`, `QueryPlan.temporal_policy`, `QueryPlan.temporal_decision`.
- Preserves: `SqlCompiler.compile(plan: QueryPlan) -> CompiledQuery`.

- [ ] **Step 1: Write failing filter compilation tests**

Extend the anonymous compiler fixture with an accounting-month binding and assert:

```python
compiled = GenericSqlCompiler().compile(
    _plan(
        filters=(
            ResolvedFilter(
                property=month_binding,
                operator=RuleOperator.EQ,
                values=(RdfLiteral(lexical_form="202607", datatype_uri=f"{XSD}string"),),
                source="ontology_default",
                explanation="默认取上一个完整自然月",
            ),
        ),
        temporal_policy=monthly_policy,
        temporal_decision=monthly_decision,
    )
)
assert '"accounting_month" = \'202607\'' in compiled.sql
```

Add `BETWEEN '202604' AND '202606'`, a business rule plus temporal filter joined with `AND`, and assertions that a filter field is not automatically in `CompiledQuery.fields`.

- [ ] **Step 2: Write failing safety-gate tests**

Create plans with: policy but no decision, decision but no matching partition filter, filter using an unbound field, and empty range values. Each must raise `OntologyCompileError`; none may return SQL.

- [ ] **Step 3: Run compiler tests and verify RED**

Run: `pytest tests/ontology_core/test_compiler.py -q`

Expected: FAIL because `ResolvedFilter`, `TemporalDecision` and query-plan fields do not exist.

- [ ] **Step 4: Add query-plan DTOs**

Implement:

```python
class ResolvedFilter(FrozenModel):
    property: BoundProperty
    operator: RuleOperator
    values: tuple[RdfLiteral, ...]
    source: str
    explanation: str


class TemporalDecision(FrozenModel):
    partition_property_uri: str
    grain: TemporalGrain
    source: TemporalIntentSource
    system_date: date
    matched_text: str | None = None
    resolved_start: str
    resolved_end: str
    default_strategy: TemporalDefaultStrategy
    explanation: str


class QueryPlan(FrozenModel):
    # existing fields remain unchanged
    filters: tuple[ResolvedFilter, ...] = ()
    temporal_policy: TemporalPartitionPolicy | None = None
    temporal_decision: TemporalDecision | None = None
```

- [ ] **Step 5: Compile resolved filters and enforce the guard**

Convert each filter to a `RuleExpression` and reuse `_expression` so identifier quoting and literal escaping stay centralized:

```python
def _filter_expression(item: ResolvedFilter) -> RuleExpression:
    return RuleExpression(
        operator=item.operator,
        property_uri=item.property.semantic.uri,
        values=item.values,
    )
```

Before SQL construction, if `plan.temporal_policy` exists, require `plan.temporal_decision` and exactly one filter whose bound semantic URI equals `partition_property_uri` and whose operator is `EQ` or `BETWEEN`. Compile rule predicates first and resolved filters second in deterministic tuple order, joining all with `AND`.

- [ ] **Step 6: Run compiler and plan regression checks**

Run:

```powershell
pytest tests/ontology_core/test_compiler.py tests/ontology_core/test_planner.py -q
ruff check ontology_core/query_plan.py ontology_core/compiler.py tests/ontology_core/test_compiler.py
black --check ontology_core/query_plan.py ontology_core/compiler.py tests/ontology_core/test_compiler.py
```

Expected: all tests and checks pass.

- [ ] **Step 7: Commit**

```powershell
git add ontology_core/query_plan.py ontology_core/compiler.py tests/ontology_core/test_compiler.py
git commit -m "feat: 编译有界时间过滤条件"
```

---

### Task 5: 规划器接入本体时间策略

**Files:**
- Modify: `ontology_core/planner.py`
- Modify: `tests/ontology_core/test_planner.py`

**Interfaces:**
- Consumes: `OntologyResolver.get_temporal_policy`, `parse_system_date`, `parse_temporal_intents`.
- Changes: `OntologyPlanner.plan(query: str, *, system_time: str | None = None) -> QueryPlan`.
- Produces: bound partition/business-date `ResolvedFilter` values and `TemporalDecision` evidence.

- [ ] **Step 1: Extend the planner fixture with an optional monthly policy**

Add `ACCOUNTING_MONTH` property/mapping and a `TemporalPartitionPolicy` only when `with_temporal_policy=True`. Keep existing planner tests using the default false value so non-partition concepts preserve current behavior.

- [ ] **Step 2: Write failing default and explicit account-period tests**

Add:

```python
def test_planner_applies_ontology_default_month_without_selecting_partition() -> None:
    plan = OntologyPlanner(_resolver(with_temporal_policy=True)).plan(
        "查询客户编号",
        system_time="2026-08-24",
    )
    assert tuple(item.semantic.short_name for item in plan.selections) == ("CustomerId",)
    assert plan.temporal_decision is not None
    assert plan.temporal_decision.resolved_start == "202607"
    assert plan.filters[0].property.semantic.short_name == "AccountingMonth"


def test_planner_uses_explicit_month_over_default() -> None:
    plan = OntologyPlanner(_resolver(with_temporal_policy=True)).plan(
        "查询2026年6月客户编号",
        system_time="2026-08-24",
    )
    assert plan.temporal_decision is not None
    assert plan.temporal_decision.resolved_start == "202606"
    assert plan.temporal_decision.source is TemporalIntentSource.EXPLICIT_ABSOLUTE
```

Add range, `本月`, `最近3个账期`, invalid system time, missing partition mapping and policy-free compatibility tests.

- [ ] **Step 3: Run planner tests and verify RED**

Run: `pytest tests/ontology_core/test_planner.py -q`

Expected: temporal plans contain no filters and the plan method does not accept `system_time`.

- [ ] **Step 4: Bind policy and time intents into the plan**

After choosing the concept/data source and building `by_property_uri`, read the policy. If absent, preserve existing behavior. If present:

```python
system_date = parse_system_date(system_time)
partition_property = next(
    item for item in properties if item.uri == policy.partition_property_uri
)
partition_binding = by_property_uri.get(partition_property.uri)
if partition_binding is None:
    raise UnsupportedQueryPlanError("时间分区属性缺少可用的字段映射")
```

Build `TemporalTarget` aliases from short name, label and localized labels, call `parse_temporal_intents` with both `policy.grain` and `policy.default_strategy`, convert the partition result to `EQ` when start equals end and `BETWEEN` otherwise, and create typed `RdfLiteral` values. Populate `TemporalDecision` from the exact parse result.

- [ ] **Step 5: Bind supported business-date intents and reject incomplete semantics**

For each non-partition intent targeting an `xsd:date` property, require a field mapping and create one `BETWEEN` filter using ISO `YYYY-MM-DD` values. If the parser reports an unsupported datatype or the target lacks a mapping, propagate a safe planning error so SQL is not generated. A business-date intent never removes the default partition filter.

- [ ] **Step 6: Prevent implicit partition selection**

Keep the partition property out of `selections` when it appears only because the policy needs a filter. Include it when the normalized user text explicitly contains one of its aliases in a return-field context such as `显示账期`, `返回账期`, `查询账期和客户编号` or `时间分区字段`.

- [ ] **Step 7: Run planner, compiler and full ontology-core tests**

Run:

```powershell
pytest tests/ontology_core/test_planner.py tests/ontology_core/test_compiler.py -q
pytest tests/ontology_core -q
ruff check ontology_core tests/ontology_core
black --check ontology_core tests/ontology_core
```

Expected: focused tests and the complete ontology-core suite pass.

- [ ] **Step 8: Commit**

```powershell
git add ontology_core/planner.py tests/ontology_core/test_planner.py
git commit -m "feat: 在本体查询计划中解析业务账期"
```

---

### Task 6: 影子服务、编排器与 API 时间证据

**Files:**
- Modify: `agent/ontology_shadow.py`
- Modify: `agent/orchestrator.py`
- Modify: `tests/test_ontology_shadow.py`
- Modify: `tests/test_orchestrator.py`
- Modify: `tests/test_conversation.py`

**Interfaces:**
- Changes: `OntologyShadowService.preview(query: str, legacy_sql: str | None, *, system_time: str | None = None) -> OntologyShadowResult`
- Produces: `TemporalEvidence`
- Extends: `OntologyShadowResult.status` with `clarification_required`
- Extends: `OntologyShadowResult.temporal_decision: TemporalEvidence | None`

- [ ] **Step 1: Write failing shadow result and evidence tests**

Extend the anonymous snapshot with a monthly policy and assert:

```python
result = service.preview(
    "查询客户编号",
    "SELECT legacy_one FROM old_table;",
    system_time="2026-08-24",
)
assert result.status == "generated"
assert '"accounting_month" = \'202607\'' in result.ontology_sql
assert result.temporal_decision is not None
assert result.temporal_decision.partition_field == "accounting_month"
assert result.temporal_decision.source == "ontology_default"
assert result.temporal_decision.resolved_start == "202607"
assert result.temporal_decision.safety_status == "bounded"
```

Assert conflicting and unbounded queries return `clarification_required`, `ontology_sql is None`, and a safe Chinese summary without package paths or raw exception details.

- [ ] **Step 2: Run shadow tests and verify RED**

Run: `pytest tests/test_ontology_shadow.py -q`

Expected: preview does not accept `system_time` and no temporal evidence exists.

- [ ] **Step 3: Add safe temporal evidence DTO**

Implement:

```python
class TemporalEvidence(FrozenModel):
    partition_field: str
    grain: str
    policy_source: Literal["ontology"] = "ontology"
    system_time: str
    user_time: str | None = None
    source: str
    default_strategy: str
    resolved_start: str
    resolved_end: str
    safety_status: Literal["bounded"] = "bounded"
    explanation: str
```

Add `temporal_decision: TemporalEvidence | None = None` and the new status literal to `OntologyShadowResult`.

- [ ] **Step 4: Pass system time through planning and map errors**

Call `OntologyPlanner(...).plan(query, system_time=system_time)`. Convert a successful `TemporalDecision` and its bound property field name into `TemporalEvidence`. Map `TemporalIntentError` reasons `conflicting_partition_time` and `unbounded_time` to `clarification_required`; map invalid system time, unsupported business date type and missing mapping to `unsupported`. Do not expose exception details in the response.

- [ ] **Step 5: Pass `system_time` from the orchestrator**

Change the call to:

```python
shadow = get_ontology_shadow_service().preview(
    user_query,
    legacy_sql,
    system_time=system_time,
)
```

Update test doubles in `tests/test_orchestrator.py` to accept the keyword-only argument and assert it receives `2026-08-14`. The conversation route already forwards `MessageSend.system_time` to `run_agent`, so no request schema change is required.

- [ ] **Step 6: Verify trace and persistence behavior**

Update conversation tests so polling and persisted messages retain `temporal_decision` inside the `ontology_shadow` payload. Assert `clarification_required` produces a skipped ontology step and no ontology SQL while leaving the existing legacy SQL path unchanged.

- [ ] **Step 7: Run integration tests and checks**

Run:

```powershell
pytest tests/test_ontology_shadow.py tests/test_orchestrator.py tests/test_conversation.py -q
ruff check agent/ontology_shadow.py agent/orchestrator.py tests/test_ontology_shadow.py tests/test_orchestrator.py tests/test_conversation.py
black --check agent/ontology_shadow.py agent/orchestrator.py tests/test_ontology_shadow.py tests/test_orchestrator.py tests/test_conversation.py
```

Expected: all selected tests and checks pass.

- [ ] **Step 8: Commit**

```powershell
git add agent/ontology_shadow.py agent/orchestrator.py tests/test_ontology_shadow.py tests/test_orchestrator.py tests/test_conversation.py
git commit -m "feat: 输出可解释的本体账期证据"
```

---

### Task 7: 聊天页面展示业务账期决策

**Files:**
- Modify: `frontend/src/components/OntologyComparison.tsx`

**Interfaces:**
- Consumes: backend `OntologyShadowResult.temporal_decision`.
- Produces: visible business-period decision card and clarification alert.

- [ ] **Step 1: Extend TypeScript response types**

Add:

```typescript
export interface TemporalEvidence {
  partition_field: string;
  grain: "day" | "month";
  policy_source: "ontology";
  system_time: string;
  user_time: string | null;
  source: "explicit_absolute" | "explicit_relative" | "ontology_default";
  default_strategy: "t_minus_2" | "previous_complete_month";
  resolved_start: string;
  resolved_end: string;
  safety_status: "bounded";
  explanation: string;
}
```

Extend status with `clarification_required` and add `temporal_decision: TemporalEvidence | null`.

- [ ] **Step 2: Render a compact evidence card**

Use Ant Design `Descriptions` below the generated SQL and above the generic ontology evidence. Map values without recomputation:

```typescript
const sourceLabels = {
  explicit_absolute: "用户明确指定",
  explicit_relative: "用户相对时间",
  ontology_default: "本体默认推算",
};

const period =
  decision.resolved_start === decision.resolved_end
    ? decision.resolved_start
    : `${decision.resolved_start} 至 ${decision.resolved_end}`;
```

Show: 分区字段、分区粒度、策略来源、系统时间、用户时间、默认算法、最终账期、安全状态. Render “已添加有界分区约束” as a green tag.

- [ ] **Step 3: Render clarification-required state**

Add `clarification_required: "业务账期需要确认"` to `statusTitles`; use warning alert styling and display the backend summary. Do not show or enable the ontology SQL copy button when SQL is absent.

- [ ] **Step 4: Build the frontend**

Run from `frontend/`:

```powershell
npm run build
```

Expected: TypeScript and Vite complete with exit code 0. The existing bundle-size warning may remain but no new compile error is allowed.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/OntologyComparison.tsx
git commit -m "feat: 展示本体业务账期决策"
```

---

### Task 8: 当前本地月表验收、项目记录与服务启动

**Files:**
- Local only: `.local/ontology-imports/user-table-v1/overrides.json`
- Local only: `.local/ontology-imports/user-table-v1/report.json`
- Local only: `.local/ontology-packages/user-table-v1/`
- Modify: `docs/project-journal/2026-08.md`

**Interfaces:**
- Consumes: confirmed current monthly partition field and strategy.
- Produces: validated local package loaded by the running backend.

- [ ] **Step 1: Add the confirmed ignored local strategy**

Use `apply_patch` to add this object alongside the existing field-description correction in the ignored override file:

```json
"temporal_policy": {
  "field": "P_MON",
  "grain": "month",
  "default_strategy": "previous_complete_month",
  "allow_query_override": true
}
```

Run `git check-ignore -v .local/ontology-imports/user-table-v1/overrides.json` before regenerating. Expected: an ignore rule is printed.

- [ ] **Step 2: Re-publish and validate the local package**

Re-run the existing `python -m ontology_core import-tabular` command against the original ignored attachment and confirmed physical namespace, preserving package ID/base URI/version/platform/dialect arguments, with `--overrides`, `--report`, `--replace` and `--json`.

Then run:

```powershell
python -m ontology_core validate .local/ontology-packages/user-table-v1 --json
python -m ontology_core inspect .local/ontology-packages/user-table-v1 --json
```

Expected: package is valid and contains exactly one temporal policy. All generated files remain ignored.

- [ ] **Step 3: Run current-table behavioral acceptance**

Instantiate `OntologyRuntime` for the regenerated local package and call `OntologyShadowService.preview` with `system_time="2026-08-24"`. Assert:

```text
查询用户编码和客户编码
  -> WHERE "P_MON" = '202607'

查询6月用户编码和客户编码
  -> WHERE "P_MON" = '202606'

查询2026年4月至6月用户编码
  -> WHERE "P_MON" BETWEEN '202604' AND '202606'

查询2026年5月用户，账期按202606
  -> clarification_required, ontology_sql=null

查询全部历史用户编码
  -> clarification_required, ontology_sql=null
```

Also assert `P_MON` is absent from the `SELECT` list unless the prompt explicitly requests the账期 field.

- [ ] **Step 4: Run necessary project verification once**

Run:

```powershell
pytest -q
ruff check ontology_core agent tests
black --check ontology_core agent tests
npm run build
git diff --check
```

Run the frontend build from `frontend/`. Expected: complete Python suite passes with documented skips only, Ruff/Black pass, Vite exits 0, and no whitespace errors exist. Do not dispatch extra review agents.

- [ ] **Step 5: Verify privacy and Git boundaries**

Run `git status --short` and `git check-ignore -v` for the local override, report and package. Search tracked diffs for the current real physical namespace/table and fail the task if any occur outside previously tracked historical documentation explicitly approved by the user.

- [ ] **Step 6: Record reusable engineering evidence**

Append a generic entry to `docs/project-journal/2026-08.md` covering:

```text
难点：把“默认上月/T-2”从编排器技巧提升为本体事实，同时避免时间误绑定和静默全表扫描。
方案：本体声明策略、确定性时间解析、QueryPlan 有界谓词硬门槛、后端时间证据和前端可视化。
验证：默认月、显式月、范围、冲突、无边界、缺失映射及完整回归测试。
简历价值：将风控/取数领域的账期口径转化为可治理、可解释、跨编译器的 Agent 语义能力。
```

Do not include real table or field identifiers in the tracked journal.

- [ ] **Step 7: Commit tracked documentation**

```powershell
git add docs/project-journal/2026-08.md
git commit -m "docs: 记录本体账期治理实践"
```

- [ ] **Step 8: Restart services safely and verify availability**

Resolve the exact backend and frontend listener PIDs before stopping only those development processes. Start backend with the ignored local package and shadow mode enabled; start or reuse the frontend on port 5199. Verify:

```text
GET http://127.0.0.1:8001/health -> HTTP 200 and healthy=true
GET http://127.0.0.1:5199/chat   -> HTTP 200
```

Do not stop unrelated Python or Node processes.

- [ ] **Step 9: Hand off for visual testing**

Report the chat URL, the five acceptance prompts from Step 3, expected visible “业务账期决策” fields, branch name, commits, test totals and known non-blocking warnings. Keep the worktree and branch; do not merge or push.
