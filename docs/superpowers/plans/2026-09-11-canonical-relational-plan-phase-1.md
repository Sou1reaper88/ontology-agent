# Canonical Relational Plan Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可表达扫描、并集、连接、过滤、投影、聚合和物化的统一关系逻辑计划，并提供不接入生产入口的 Hive 确定性编译器。

**Architecture:** 新合同用有向无环图表达关系运算，每个节点只引用上游节点的逻辑列槽位；本体候选对象和字段负责把槽位绑定到真实物理元数据。独立编译器按拓扑顺序编译物化节点，生成安全的 `DROP TABLE IF EXISTS` + `CREATE TABLE AS SELECT` 程序，并复用现有程序安全校验；本阶段不修改 `run_agent`、元数据规划器或聊天 API。

**Tech Stack:** Python 3.13、Pydantic v2、sqlglot、pytest

## Global Constraints

- 仅生成 SQL 程序，不连接业务数据库、不执行脚本。
- 物理对象和字段必须来自同一不可变已发布本体快照。
- 不允许大模型注入 SQL、目标表名或未发布物理标识符。
- `union_all` 必须显式声明来源和列映射，不隐式去重。
- `left` 与 `anti` 保留左侧语义，不允许编译器自动反转。
- 无法绑定的节点、列、对象、字段、数据类型或前向引用必须失败关闭。
- 本阶段保留现有生产入口，不切换现有运行行为。
- 使用测试先行；每个新增行为先观察到预期失败，再写最小实现。
- 完成后更新工程日志，只记录通用技术难点和真实验证证据，不记录业务敏感标识符。

---

### Task 1: 规范关系计划合同、校验器与 Hive 编译器

**Files:**
- Create: `ontology_core/relational_plan.py`
- Create: `ontology_core/relational_compiler.py`
- Create: `tests/ontology_core/test_relational_plan.py`
- Create: `tests/ontology_core/test_relational_compiler.py`
- Modify: `ontology_core/__init__.py`
- Modify: `docs/project-journal/2026-09.md`

**Interfaces:**
- Consumes: `CandidateObject`、`CandidateField`、`RuleOperator`、`CompiledProgram`、`ProgramTableNamer`、`HiveProgramCompiler.validate_program`。
- Produces: `CanonicalRelationalPlan`、各类不可变逻辑节点、`HiveRelationalCompiler.compile(plan, program_id)`、`RelationalCompilerRegistry.default().get(dialect)`。

- [ ] **Step 1: 写计划合同的失败测试**

在 `tests/ontology_core/test_relational_plan.py` 构造完全合成的候选对象，覆盖以下合同：

```python
def test_plan_round_trip_preserves_union_join_and_materialization() -> None:
    restored = CanonicalRelationalPlan.model_validate(plan.model_dump(mode="json"))
    assert restored == plan

def test_plan_rejects_unknown_or_forward_node_reference() -> None:
    payload = _valid_plan().model_dump(mode="json")
    payload["nodes"][1]["inputs"][0] = "future_source"
    with pytest.raises(ValidationError, match="上游节点"):
        CanonicalRelationalPlan.model_validate(payload)

def test_union_requires_one_compatible_source_column_per_input() -> None:
    payload = _valid_plan().model_dump(mode="json")
    payload["nodes"][2]["columns"][0]["sources"].pop()
    with pytest.raises(ValidationError, match="并集"):
        CanonicalRelationalPlan.model_validate(payload)

def test_left_and_anti_join_conditions_preserve_declared_sides() -> None:
    payload = _valid_plan().model_dump(mode="json")
    payload["nodes"][4]["conditions"][0]["left"]["node_id"] = "dimension_scan"
    with pytest.raises(ValidationError, match="左右输入"):
        CanonicalRelationalPlan.model_validate(payload)

def test_plan_rejects_cross_snapshot_or_cross_datasource_objects() -> None:
    payload = _valid_plan().model_dump(mode="json")
    payload["objects"][1]["data_source_ref"] = "warehouse.secondary"
    with pytest.raises(ValidationError, match="同一数据源"):
        CanonicalRelationalPlan.model_validate(payload)
```

节点合同必须包含：

```python
class LogicalColumnRef(FrozenModel):
    node_id: NodeId
    column: ColumnName

class ScanNode(FrozenModel):
    kind: Literal["scan"] = "scan"
    node_id: NodeId
    object_ref: SemanticRef
    columns: tuple[ScanColumn, ...]

class UnionAllNode(FrozenModel):
    kind: Literal["union_all"] = "union_all"
    node_id: NodeId
    inputs: tuple[NodeId, ...]
    columns: tuple[UnionColumn, ...]

class JoinNode(FrozenModel):
    kind: Literal["join"] = "join"
    node_id: NodeId
    left_input: NodeId
    right_input: NodeId
    join_type: Literal["inner", "left", "anti"]
    conditions: tuple[JoinCondition, ...]
    match_filters: tuple[FilterPredicate, ...] = ()
    columns: tuple[DerivedColumn, ...]

class FilterNode(FrozenModel):
    kind: Literal["filter"] = "filter"
    node_id: NodeId
    input: NodeId
    predicates: tuple[FilterPredicate, ...]

class ProjectNode(FrozenModel):
    kind: Literal["project"] = "project"
    node_id: NodeId
    input: NodeId
    columns: tuple[DerivedColumn, ...]

class AggregateNode(FrozenModel):
    kind: Literal["aggregate"] = "aggregate"
    node_id: NodeId
    input: NodeId
    group_by: tuple[DerivedColumn, ...] = ()
    aggregations: tuple[AggregateColumn, ...]

class MaterializeNode(FrozenModel):
    kind: Literal["materialize"] = "materialize"
    node_id: NodeId
    input: NodeId
    step_kind: ProgramStepKind
```

`CanonicalRelationalPlan` 必须保存 `package_id`、`package_version`、`package_sha256`、`data_source_ref`、`dialect`、`objects`、`nodes` 和 `result_node_id`。校验器按声明顺序建立输出列和数据类型，禁止重复节点、未知/前向引用、重复输出列、扫描字段越权、并集输入/类型不一致、连接条件跨边、过滤/投影列越权、结果节点不是唯一 `RESULT` 物化节点。

- [ ] **Step 2: 运行测试并确认因模块缺失而失败**

Run: `python -m pytest tests/ontology_core/test_relational_plan.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'ontology_core.relational_plan'`.

- [ ] **Step 3: 实现最小不可变合同与确定性结构校验**

在 `ontology_core/relational_plan.py` 实现上述模型。使用 `Annotated[... , Field(discriminator="kind")]` 组成 `RelationalNode`；所有模型继承 `FrozenModel` 并拒绝额外字段。`CanonicalRelationalPlan` 的 `model_validator(mode="after")` 必须只根据绑定元数据和节点合同推导列类型，不接受 SQL 字符串。

列引用规则必须精确为：

```python
# union：每个 UnionColumn.sources 的 node_id 顺序与 inputs 完全一致
# join：condition.left 只引用 left_input，condition.right 只引用 right_input
# match_filters：只引用 right_input
# filter/project/aggregate：只引用直接 input
# anti：输出列只能来自 left_input
```

- [ ] **Step 4: 运行合同测试并确认通过**

Run: `python -m pytest tests/ontology_core/test_relational_plan.py -q`

Expected: PASS.

- [ ] **Step 5: 写 Hive 编译器的失败测试**

在 `tests/ontology_core/test_relational_compiler.py` 覆盖：

```python
def test_compiles_union_all_before_left_join_into_one_result_ctas() -> None:
    program = HiveRelationalCompiler().compile(plan, program_id="a1b2c3d4e5f6")
    assert "UNION ALL" in program.sql
    assert "LEFT JOIN" in program.sql
    assert program.result_table == "temp_oa_a1b2c3d4e5f6_result_table"
    assert "DROP TABLE" not in program.statements[-1].create_sql

def test_compiles_anti_join_without_reversing_preserved_side() -> None:
    program = HiveRelationalCompiler().compile(plan, program_id="a1b2c3d4e5f6")
    assert "LEFT JOIN" in program.sql
    assert "IS NULL" in program.sql

def test_compiles_grouped_aggregation_from_logical_columns() -> None:
    program = HiveRelationalCompiler().compile(
        _aggregate_plan(), program_id="a1b2c3d4e5f6"
    )
    assert "COUNT(DISTINCT" in program.sql

def test_compiler_rejects_non_hive_plan_and_user_physical_identifiers() -> None:
    payload = _union_join_plan().model_dump(mode="json")
    payload["dialect"] = "postgres"
    with pytest.raises(OntologyCompileError, match="方言"):
        HiveRelationalCompiler().compile(
            CanonicalRelationalPlan.model_validate(payload),
            program_id="a1b2c3d4e5f6",
        )

    injected = payload["nodes"][0]
    injected["sql"] = "DROP TABLE source_table"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CanonicalRelationalPlan.model_validate(payload)

def test_registry_resolves_hive_and_rejects_unknown_dialect() -> None:
    assert isinstance(RelationalCompilerRegistry.default().get("hive"), HiveRelationalCompiler)
```

测试必须通过现有 `HiveProgramCompiler.validate_program(program)` 验证 SQL 程序可解析。夹具只使用合成对象名与字段名。

- [ ] **Step 6: 运行编译器测试并确认因模块缺失而失败**

Run: `python -m pytest tests/ontology_core/test_relational_compiler.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'ontology_core.relational_compiler'`.

- [ ] **Step 7: 实现 Hive 编译器和注册表**

在 `ontology_core/relational_compiler.py` 实现：

```python
class RelationalCompiler(Protocol):
    def compile(
        self,
        plan: CanonicalRelationalPlan,
        *,
        program_id: str,
    ) -> CompiledProgram:
        raise NotImplementedError

class HiveRelationalCompiler:
    platform = "hive"

    def compile(self, plan: CanonicalRelationalPlan, *, program_id: str) -> CompiledProgram:
        if plan.dialect.casefold() != self.platform:
            raise OntologyCompileError("关系计划当前没有可用的方言编译器")
        program = self._compile_materializations(plan, program_id=program_id)
        HiveProgramCompiler().validate_program(program)
        return program

class RelationalCompilerRegistry:
    @classmethod
    def default(cls) -> "RelationalCompilerRegistry":
        return cls({"hive": HiveRelationalCompiler()})
```

编译器按节点拓扑递归生成带稳定别名的关系 SQL：扫描绑定物理表/字段；并集按显式列映射生成 `UNION ALL`；连接从声明左右输入生成 `INNER JOIN`、`LEFT JOIN` 或 `LEFT JOIN ... IS NULL`；右侧匹配过滤只进入 `ON`；普通过滤进入 `WHERE`；投影和聚合只使用逻辑列；物化目标只由 `ProgramTableNamer` 生成。每个物化节点生成一个 `CompiledStatement`，前缀删除与 CTAS 分开保存，不生成末尾清理语句。

最终 `CompiledProgram` 必须包含本体源表、物理字段、节点依赖血缘和已有时间证据可扩展位置，并调用 `HiveProgramCompiler.validate_program`。不要修改现有 `HiveInferenceCompiler`、`ProgramCompilerRegistry` 或任何生产入口。

- [ ] **Step 8: 导出公共接口并执行聚焦回归**

在 `ontology_core/__init__.py` 导出 `CanonicalRelationalPlan`、节点类型、`HiveRelationalCompiler` 和 `RelationalCompilerRegistry`。

Run:

```powershell
python -m pytest tests/ontology_core/test_relational_plan.py tests/ontology_core/test_relational_compiler.py tests/ontology_core/test_inference_compiler.py tests/ontology_core/test_program_compiler.py -q
```

Expected: PASS；旧推断编译器和旧程序编译器行为不变。

- [ ] **Step 9: 记录难点、证据并提交**

在 `docs/project-journal/2026-09.md` 追加一节，记录：双规划器表达力不一致如何演化为统一关系代数合同；为什么模型只声明语义运算而 Python 绑定元数据并强制拓扑；为什么 `union_all`、`left`、`anti` 需要显式方向和列映射；聚焦测试的实际通过数量和提交号。不要写入真实表名、字段名、需求文本或外部模型内容。

Run:

```powershell
git diff --check
git status --short
git add -- ontology_core/relational_plan.py ontology_core/relational_compiler.py ontology_core/__init__.py tests/ontology_core/test_relational_plan.py tests/ontology_core/test_relational_compiler.py docs/project-journal/2026-09.md
git commit -m "feat: add canonical relational plan compiler"
```

Expected: commit succeeds; `.codex-artifacts/` remains untracked and is not staged.
