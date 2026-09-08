# SQL Evaluation Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立一个不执行 SQL 的本地评测中心，批量比较真实 SQL、Legacy SQL 与本体 SQL，输出可复现的结构评分、失败归因和可视化结果。

**Architecture:** 新增独立 Python `evaluation` 包，依次承担 Excel 导入、现有 `run_agent` 适配、SQL AST 结构提取、确定性比较与批量任务编排；任务和案例存入应用数据库，但不进入聊天或取数执行链路。FastAPI 提供创建、运行、轮询、分页、详情、模板下载和删除接口，React 新增 `/evaluation` 工作台展示汇总指标与逐案例三方 SQL。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy 2、Alembic、Pydantic 2、openpyxl 3、SQLGlot 28、pytest 8、React 18、TypeScript 5、React Router 6、Ant Design 5、Vite 5

## Global Constraints

- 首期只做 SQL 结构与语义评测，不连接数据库，不执行任何用户 SQL。
- 测试集只要求 `需求原文` 和 `真实SQL` 两个必填列。
- 同一评测任务固定 SQL 方言、基准系统时间和本体包版本；首轮基准时间可设为 `2026-08-24`。
- 默认 SQL 方言为 `hive`，解析失败不得使用正则或猜测方言兜底。
- 真实 SQL 分别作为 Legacy SQL 和本体 SQL 的参照，两条候选路径互不作为正确性参照。
- 无法可靠评分的案例进入人工复核，不按零分或满分计入平均结构得分。
- 原始 Excel 不长期保存，需求原文和三方 SQL 不写入应用日志、审计详情、Git 或测试夹具。
- 评测任务不创建聊天消息、`QueryHistory` 或可执行取数任务。
- 单案例失败不得中断后续案例；重复启动已运行任务不得重复消耗模型额度。
- 完成每个独立任务后自动 Git 提交，不推送或合并。
- 完成功能后只运行与本功能直接相关的验证并优先启动 `8001` 后端与 `5199` 前端供用户验收，不进行大范围审查。

---

## File Map

### Python 评测内核

- Create `evaluation/__init__.py`: 评测包公共入口。
- Create `evaluation/contracts.py`: AST 结构、比较结果、生成快照、导入案例和运行摘要的 Pydantic 契约。
- Create `evaluation/sql_structure.py`: SQLGlot 解析、只读边界检查和标准结构提取。
- Create `evaluation/comparison.py`: 六维比较、严格通过、分数与确定性失败归因。
- Create `evaluation/importer.py`: Excel 导入校验和空白模板生成。
- Create `evaluation/generation.py`: 现有 `run_agent` 的无会话评测适配器。
- Create `evaluation/runner.py`: 单任务串行执行、版本锁定、断点继续和汇总。
- Modify `agent/ontology_shadow.py`: 本体包已加载时，让未命中和不支持结果也携带包版本，并支持 Legacy 失败后的独立评测调用。
- Modify `pyproject.toml`: 增加 SQLGlot 依赖并打包 `evaluation*`。

### 数据模型与 API

- Create `models/evaluation_run.py`: 评测任务 ORM。
- Create `models/evaluation_case.py`: 评测案例 ORM。
- Modify `models/__init__.py`: 注册两个模型供业务和 Alembic 使用。
- Create `alembic/versions/e64b7a9c2f10_add_evaluation_runs.py`: 评测任务与案例迁移。
- Create `api/schemas/evaluations.py`: 创建、列表、详情、案例与错误响应 DTO。
- Create `api/routes/evaluations.py`: 模板、导入、运行、轮询、案例和删除接口。
- Modify `api/routes/__init__.py`: 导出评测路由模块。
- Modify `api/main.py`: 注册 `/evaluations` 路由。

### 前端

- Create `frontend/src/features/evaluation/types.ts`: 页面使用的稳定领域类型。
- Create `frontend/src/features/evaluation/api.ts`: 评测 API、上传、下载和错误映射。
- Create `frontend/src/features/evaluation/viewModel.ts`: 指标格式、状态文案和案例筛选纯函数。
- Create `frontend/src/features/evaluation/EvaluationCenter.tsx`: 新建任务、任务列表与轮询。
- Create `frontend/src/features/evaluation/EvaluationRunView.tsx`: 汇总、案例列表和详情抽屉。
- Create `frontend/src/features/evaluation/evaluation.css`: 评测中心视觉与响应式布局。
- Create `frontend/src/pages/Evaluation.tsx`: 路由页面入口。
- Modify `frontend/src/components/navigation.ts`: 增加“评测中心”导航。
- Modify `frontend/src/App.tsx`: 注册 `/evaluation` 与 `/evaluation/:runId`。
- Modify `frontend/vite.config.ts`: 代理 `/evaluations` 到 `8001`。
- Create `frontend/tests/evaluation-view-model.test.ts`: 指标和状态显示契约。

### 验证与项目记录

- Create `tests/evaluation/test_sql_structure.py`: SQL AST 提取契约。
- Create `tests/evaluation/test_comparison.py`: 六维评分和归因契约。
- Create `tests/evaluation/test_importer.py`: Excel 导入与模板契约。
- Create `tests/evaluation/test_runner.py`: 串行、断点和包版本契约。
- Create `tests/test_evaluations.py`: FastAPI 所有权、幂等和删除契约。
- Modify `docs/project-journal/2026-08.md`: 记录评测体系建设难点、解决方式和简历素材。

---

### Task 1: 建立 SQL AST 结构提取契约

**Files:**
- Modify: `pyproject.toml`
- Create: `evaluation/__init__.py`
- Create: `evaluation/contracts.py`
- Create: `evaluation/sql_structure.py`
- Create: `tests/evaluation/test_sql_structure.py`

**Interfaces:**
- Produces: `StructureStatus = Literal["parsed", "unparsed", "unsupported"]`。
- Produces: `JoinSignature`, `PredicateSignature`, `SqlStructure` Pydantic 模型；所有集合型字段用排序后的 tuple，保证 JSON 可复现。
- Produces: `extract_sql_structure(sql: str, dialect: str) -> SqlStructure`。
- Produces: `SqlStructure.is_read_only: bool`、`warnings: tuple[str, ...]` 和 `status`，供 Task 2 判定是否可评分。

- [ ] **Step 1: 写失败测试，锁定标准化与只读边界**

```python
def test_extract_hive_select_normalizes_aliases_and_predicates() -> None:
    structure = extract_sql_structure(
        """
        SELECT u.USER_ID AS id, COUNT(DISTINCT o.ORDER_ID) AS order_count
        FROM DM.D_USER u
        LEFT JOIN DM.F_ORDER o ON u.USER_ID = o.USER_ID
        WHERE u.P_MON = '202607' AND u.STATUS = 'ACTIVE'
        GROUP BY u.USER_ID
        ORDER BY order_count DESC
        LIMIT 100
        """,
        "hive",
    )
    assert structure.status == "parsed"
    assert structure.tables == ("dm.d_user", "dm.f_order")
    assert structure.projections == ("count(distinct dm.f_order.order_id)", "dm.d_user.user_id")
    assert structure.joins[0].join_type == "left"
    assert structure.predicates == (
        PredicateSignature(field="dm.d_user.p_mon", operator="=", values=("202607",)),
        PredicateSignature(field="dm.d_user.status", operator="=", values=("ACTIVE",)),
    )
    assert structure.group_by == ("dm.d_user.user_id",)
    assert structure.distinct is False
    assert structure.limit == 100
```

补充测试：仅大小写、引号、空白和表别名不同的 SQL 得到相同结构；CTE 与单层子查询被展开到稳定表名；`INSERT`、`DROP`、多语句、解析错误和 SQLGlot `Command` 节点不得标记为 `parsed`。

- [ ] **Step 2: 运行 SQL 结构测试并确认缺少模块**

```powershell
pytest tests/evaluation/test_sql_structure.py -q
```

Expected: collection FAIL，提示 `evaluation.sql_structure` 不存在。

- [ ] **Step 3: 增加 SQLGlot 和领域契约**

在 `pyproject.toml` dependencies 增加：

```toml
"sqlglot>=28.6,<29",
```

并在 setuptools include 增加 `"evaluation*"`。`contracts.py` 定义以下稳定字段：

```python
class JoinSignature(BaseModel, frozen=True):
    join_type: str
    left: str
    right: str
    conditions: tuple[str, ...] = ()

class PredicateSignature(BaseModel, frozen=True):
    field: str
    operator: str
    values: tuple[str, ...] = ()

class SqlStructure(BaseModel, frozen=True):
    status: Literal["parsed", "unparsed", "unsupported"]
    is_read_only: bool
    tables: tuple[str, ...] = ()
    projections: tuple[str, ...] = ()
    joins: tuple[JoinSignature, ...] = ()
    predicates: tuple[PredicateSignature, ...] = ()
    having: tuple[PredicateSignature, ...] = ()
    aggregates: tuple[str, ...] = ()
    group_by: tuple[str, ...] = ()
    distinct: bool = False
    order_by: tuple[str, ...] = ()
    limit: int | None = None
    has_star: bool = False
    has_cte: bool = False
    has_subquery: bool = False
    warnings: tuple[str, ...] = ()
```

- [ ] **Step 4: 实现显式方言解析和标准结构提取**

`extract_sql_structure` 使用 `sqlglot.parse`，要求恰好一个 `Select`、`Union`、`Intersect` 或 `Except` 查询根；把 catalog、schema、table、alias 建立为解析上下文，再将列引用回写为物理限定名。比较字符串使用 SQLGlot 节点的规范化 SQL 输出，不保留用户注释。

失败返回必须安全且不包含原 SQL：

```python
return SqlStructure(
    status="unparsed",
    is_read_only=False,
    warnings=("sql_parse_failed",),
)
```

多语句返回 `unsupported/multiple_statements`，写操作返回 `unsupported/non_read_only_statement`，未限定且无法唯一解析来源的列保留为小写字段名并增加 `unresolved_column_source` 警告。

- [ ] **Step 5: 运行聚焦测试与静态检查**

```powershell
pytest tests/evaluation/test_sql_structure.py -q
ruff check evaluation tests/evaluation/test_sql_structure.py
```

Expected: SQL 结构测试全部 PASS，Ruff 无错误。

- [ ] **Step 6: 自动提交**

```powershell
git add -- pyproject.toml evaluation/__init__.py evaluation/contracts.py evaluation/sql_structure.py tests/evaluation/test_sql_structure.py
git commit -m "feat: 建立 SQL 结构提取内核"
```

---

### Task 2: 实现六维比较、评分与失败归因

**Files:**
- Modify: `evaluation/contracts.py`
- Create: `evaluation/comparison.py`
- Create: `tests/evaluation/test_comparison.py`

**Interfaces:**
- Consumes: Task 1 `SqlStructure`、`PredicateSignature`、`JoinSignature`。
- Produces: `DimensionResult(status, score, missing, extra, conflicts)`。
- Produces: `CandidateEvaluation(score, strict_pass, manual_review, dimensions, diagnosis_codes)`。
- Produces: `compare_sql_structures(reference: SqlStructure, candidate: SqlStructure, *, partition_fields: Collection[str] = ()) -> CandidateEvaluation`。
- Produces: `summarize_candidate_results(results: Sequence[CandidateEvaluation]) -> EvaluationSummary`。

- [ ] **Step 1: 写失败测试覆盖权重、严格通过和不可评分分母**

```python
def test_partition_mismatch_is_separate_from_business_predicates() -> None:
    result = compare_sql_structures(
        reference=structure("SELECT USER_ID FROM D_USER WHERE P_MON='202607' AND STATUS='A'"),
        candidate=structure("SELECT USER_ID FROM D_USER WHERE P_MON='202606' AND STATUS='A'"),
        partition_fields={"p_mon"},
    )
    assert result.dimensions["predicates"].status == "matched"
    assert result.dimensions["partition"].status == "mismatched"
    assert result.score == 85
    assert result.strict_pass is False
    assert "partition_mismatch" in result.diagnosis_codes
```

补充测试分别制造：错表、漏字段、多字段、错 JOIN 类型、错关联键、错过滤值、错聚合、错 `DISTINCT`、参照解析失败、候选解析失败和复杂结构警告。验证不适用维度不扣分，无法评分案例不进入平均分分母，汇总分母为零时返回 `None` 而不是 `0.0`。

- [ ] **Step 2: 运行评分测试并确认失败**

```powershell
pytest tests/evaluation/test_comparison.py -q
```

Expected: collection FAIL，提示 `evaluation.comparison` 不存在。

- [ ] **Step 3: 定义稳定比较模型和权重**

```python
DIMENSION_WEIGHTS = {
    "tables": 20,
    "fields": 20,
    "predicates": 20,
    "joins": 15,
    "partition": 15,
    "shape": 10,
}

DimensionStatus = Literal[
    "matched", "partial", "mismatched", "not_applicable", "unscorable"
]
```

`DimensionResult.score` 只允许 `int | None`；`not_applicable` 在总分计算时视为该维度满权重，`unscorable` 使整个候选 `score=None`。`strict_pass=True` 要求六维全部为 `matched/not_applicable`、双方可解析、只读且 warnings 为空。

- [ ] **Step 4: 实现集合比较和确定性归因**

表、字段、JOIN 和查询形态比较使用标准化集合的 missing/extra；过滤条件按 `(field, operator)` 对齐，相同键不同值进入 conflicts；分区字段通过 `partition_fields` 从普通 predicates 中拆出，短名和限定名都用末段字段名匹配。

诊断码按以下固定优先级排序：

```python
DIAGNOSIS_PRIORITY = (
    "reference_parse_failed",
    "candidate_parse_failed",
    "table_mismatch",
    "join_mismatch",
    "partition_mismatch",
    "predicate_mismatch",
    "field_mismatch",
    "query_shape_mismatch",
    "manual_review_required",
)
```

不得生成自由文本猜测；详情文案由前端根据码和结构差异渲染。

- [ ] **Step 5: 运行 Task 1–2 聚焦测试**

```powershell
pytest tests/evaluation/test_sql_structure.py tests/evaluation/test_comparison.py -q
ruff check evaluation tests/evaluation
```

Expected: 全部 PASS，Ruff 无错误。

- [ ] **Step 6: 自动提交**

```powershell
git add -- evaluation/contracts.py evaluation/comparison.py tests/evaluation/test_comparison.py
git commit -m "feat: 实现 SQL 六维评分与归因"
```

---

### Task 3: 建立测试集导入与空白模板下载能力

**Files:**
- Modify: `evaluation/contracts.py`
- Create: `evaluation/importer.py`
- Create: `tests/evaluation/test_importer.py`

**Interfaces:**
- Produces: `ImportedCase(row_number: int, requirement: str, reference_sql: str)`。
- Produces: `WorkbookValidationError(code: str, message: str, row_number: int | None)`；异常消息不得包含单元格内容。
- Produces: `import_evaluation_workbook(content: bytes, *, max_bytes: int) -> tuple[ImportedCase, ...]`。
- Produces: `build_evaluation_template() -> bytes`。

- [ ] **Step 1: 写失败测试覆盖用户现有两列格式**

```python
def test_import_complete_two_column_workbook() -> None:
    content = workbook_bytes(
        sheet="测试案例",
        rows=[("需求原文", "真实SQL"), ("需求一", "SELECT ID FROM T")],
    )
    cases = import_evaluation_workbook(content, max_bytes=1024 * 1024)
    assert cases == (
        ImportedCase(row_number=2, requirement="需求一", reference_sql="SELECT ID FROM T"),
    )
```

补充测试：忽略全空行；任一必填值缺失返回行号；重复表头、缺表头、零案例、超限文件、非 ZIP/XLSX、多个工作表且没有“测试案例”时拒绝；唯一工作表可作为兼容输入；公式单元格不执行公式且拒绝公式类型的必填值；错误文本不包含需求和 SQL。

- [ ] **Step 2: 运行导入测试并确认失败**

```powershell
pytest tests/evaluation/test_importer.py -q
```

Expected: collection FAIL，提示 `evaluation.importer` 不存在。

- [ ] **Step 3: 实现只读 Workbook 解析与限制**

使用 `openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=False)`。文件大小在打开前检查；工作表选择和表头匹配按规格固定；需求与 SQL 去首尾空白后分别限制为 10,000 和 100,000 字符；最多允许 1,000 条案例。异常统一转换为稳定错误码，例如 `invalid_workbook`、`missing_headers`、`missing_required_value`、`too_many_cases`。

- [ ] **Step 4: 生成无业务样例的模板**

`build_evaluation_template` 创建 `测试案例` 和 `填写说明` 两张表。输入表只包含两个表头和空白可填写行；说明表写明必填、每行一条需求、SQL 不会执行、任务级基准时间在页面设置。不得写入表名、字段名、业务需求或 SQL 样例。

- [ ] **Step 5: 运行导入测试和格式检查**

```powershell
pytest tests/evaluation/test_importer.py -q
ruff check evaluation/importer.py tests/evaluation/test_importer.py
```

Expected: 全部 PASS，Ruff 无错误。

- [ ] **Step 6: 自动提交**

```powershell
git add -- evaluation/contracts.py evaluation/importer.py tests/evaluation/test_importer.py
git commit -m "feat: 支持 SQL 评测集导入与模板"
```

---

### Task 4: 持久化评测任务与案例

**Files:**
- Create: `models/evaluation_run.py`
- Create: `models/evaluation_case.py`
- Modify: `models/__init__.py`
- Create: `alembic/versions/e64b7a9c2f10_add_evaluation_runs.py`
- Create: `tests/evaluation/test_models.py`

**Interfaces:**
- Produces: `EvaluationRun` ORM，关系 `cases` 按 `case_number` 排序并 `delete-orphan`。
- Produces: `EvaluationCase` ORM，外键 `run_id` 使用 `ondelete="CASCADE"`。
- Consumes: Task 1–3 的 JSON 可序列化 Pydantic 输出。

- [ ] **Step 1: 写失败模型契约**

测试 `EvaluationRun` 默认状态为 `pending`；案例按序号排序；删除任务级联删除案例；JSON 字段能保存结构、比较和诊断；用户外键和 `(run_id, case_number)` 唯一约束存在。

- [ ] **Step 2: 运行模型测试并确认模型不存在**

```powershell
pytest tests/evaluation/test_models.py -q
```

Expected: collection FAIL，提示无法导入 `EvaluationRun`。

- [ ] **Step 3: 定义任务和案例字段**

`EvaluationRun` 至少包含：`id`、`user_id`、`name`、`dialect`、`system_time`、`status`、`total_cases`、`processed_cases`、`failed_cases`、`package_id`、`package_version`、`package_sha256`、`summary` JSON、`error_code`、`created_at`、`started_at`、`completed_at`。

`EvaluationCase` 至少包含：`id`、`run_id`、`case_number`、`source_row`、`requirement`、`reference_sql`、`legacy_sql`、`ontology_sql`、`generation_status`、`ontology_status`、`ontology_evidence` JSON、`temporal_decisions` JSON、三份 structure JSON、两份 comparison JSON、`diagnosis_codes` JSON、`duration_ms`、`error_code`、`created_at`、`completed_at`。

所有 SQL 和需求字段使用 `Text`；结构化数据使用 SQLAlchemy `JSON`；列表接口依赖字段建立 `(user_id, created_at)` 和 `(run_id, case_number)` 索引。

- [ ] **Step 4: 编写可逆 Alembic 迁移**

迁移 revision 固定为 `e64b7a9c2f10`，down revision 为 `c2e8d4a61f03`。`upgrade()` 先建 `evaluation_runs` 再建 `evaluation_cases` 和索引；`downgrade()` 先删案例再删任务。

- [ ] **Step 5: 运行模型测试并检查迁移 SQL**

```powershell
pytest tests/evaluation/test_models.py -q
alembic upgrade head --sql
ruff check models/evaluation_run.py models/evaluation_case.py tests/evaluation/test_models.py
```

Expected: 模型测试 PASS；离线 SQL 包含两张新表且无数据库连接；Ruff 无错误。

- [ ] **Step 6: 自动提交**

```powershell
git add -- models/evaluation_run.py models/evaluation_case.py models/__init__.py alembic/versions/e64b7a9c2f10_add_evaluation_runs.py tests/evaluation/test_models.py
git commit -m "feat: 持久化 SQL 评测任务"
```

---

### Task 5: 接入现有 Agent 并实现可恢复批量 Runner

**Files:**
- Modify: `evaluation/contracts.py`
- Create: `evaluation/generation.py`
- Create: `evaluation/runner.py`
- Modify: `agent/ontology_shadow.py`
- Modify: `tests/test_ontology_shadow.py`
- Create: `tests/evaluation/test_runner.py`

**Interfaces:**
- Produces: `GenerationSnapshot`，字段为 `legacy_sql`、`legacy_success`、`ontology_sql`、`ontology_status`、`ontology_summary`、`ontology_evidence`、`temporal_decisions`、`package_id`、`package_version`、`package_sha256`、`duration_ms`、`error_code`。
- Produces: `AgentEvaluationAdapter.generate(requirement: str, *, system_time: str) -> GenerationSnapshot`。
- Produces: `EvaluationRunner.run(run_id: int) -> None`。
- Consumes: Task 1 `extract_sql_structure`、Task 2 `compare_sql_structures/summarize_candidate_results`、Task 4 ORM。

- [ ] **Step 1: 写失败测试锁定无会话调用和版本一致性**

使用可注入的 fake generator 和临时数据库会话，验证：案例按序号串行执行；`run_agent` 参数只有需求和统一 `system_time`，history/context 为空；已完成案例跳过；单案例异常保存安全错误码后继续；本体包哈希变化时停止剩余案例并把任务置为 `failed`；重复调用 completed 任务不调用 generator。

在 `tests/test_ontology_shadow.py` 增加契约：只要本体快照已经成功加载，`no_match`、`ambiguous`、`unsupported` 和 `clarification_required` 仍返回同一 `package_id/version/sha256`；运行时未配置或加载失败时 package 保持为空。

- [ ] **Step 2: 运行 Runner 测试并确认失败**

```powershell
pytest tests/evaluation/test_runner.py -q
```

Expected: collection FAIL，提示 `evaluation.runner` 不存在。

- [ ] **Step 3: 实现 Agent 评测适配器**

适配器调用：

```python
output = run_agent(
    requirement,
    system_time=system_time,
    history=[],
    conversation_context=None,
)
```

Legacy SQL 只在 `output["success"]` 为真时采用；优先读取 `output["ontology_shadow"]`。如果 Legacy 生成失败导致 `run_agent` 没有执行影子链路，适配器单独调用 `get_ontology_shadow_service().preview(requirement, None, system_time=system_time)`，确保本体路径仍能独立接受评测且不产生第二次模型调用。捕获异常后仅保存 `type(exc).__name__` 映射出的内部错误码，禁止保存 `str(exc)`。适配器不创建 `QueryHistory`、审计日志或聊天消息。

`OntologyShadowService.preview` 在成功取得 snapshot 后先构造包标识，并把它传入所有后续终态；只有禁用、未配置或 snapshot 加载失败返回空 package。这样 Runner 从首个已加载本体的案例开始就能锁定版本，不依赖 SQL 是否成功生成。

- [ ] **Step 4: 实现逐案例执行事务边界**

Runner 每条案例执行以下固定顺序：标记 running 并提交；生成快照；锁定或校验包哈希；解析三份 SQL；从 `temporal_decisions[*].partition_field` 取得 `partition_fields`；分别比较 Legacy 与本体；合并本体状态码和结构诊断码；保存案例终态并更新进度后提交。

若本体未生成，创建 `score=None`、`strict_pass=False` 的不可评分结果，并把 `ontology_no_match`、`ontology_ambiguous`、`ontology_unsupported` 或 `ontology_unavailable` 映射为首要诊断。真实 SQL 解析失败时两条候选都标记 `reference_parse_failed/manual_review_required`。

- [ ] **Step 5: 实现汇总与断点继续**

所有案例进入终态后，按规格计算分子、分母、百分比、平均分、六维正确率和失败分布，将 JSON 保存到 `EvaluationRun.summary`。服务重启后，`running` 案例重置为 `pending` 再执行，已经 `completed/failed` 的案例跳过；任务级包版本变化和数据库错误使任务进入 `failed`。

- [ ] **Step 6: 运行 Task 1–5 聚焦后端测试**

```powershell
pytest tests/evaluation -q
ruff check evaluation tests/evaluation
```

Expected: 全部 PASS，测试期间 fake generator 调用次数与待处理案例数一致，Ruff 无错误。

- [ ] **Step 7: 自动提交**

```powershell
git add -- evaluation/contracts.py evaluation/generation.py evaluation/runner.py agent/ontology_shadow.py tests/test_ontology_shadow.py tests/evaluation/test_runner.py
git commit -m "feat: 实现可恢复 SQL 批量评测"
```

---

### Task 6: 提供评测任务 API 与权限边界

**Files:**
- Create: `api/schemas/evaluations.py`
- Create: `api/routes/evaluations.py`
- Modify: `api/routes/__init__.py`
- Modify: `api/main.py`
- Create: `tests/test_evaluations.py`

**Interfaces:**
- Produces: `GET /evaluations/template`。
- Produces: `POST /evaluations/import` multipart：`name`、`dialect`、`system_time`、`file`。
- Produces: `POST /evaluations/{run_id}/run`，成功返回 HTTP 202。
- Produces: `GET /evaluations`、`GET /evaluations/{run_id}`。
- Produces: `GET /evaluations/{run_id}/cases`、`GET /evaluations/{run_id}/cases/{case_id}`。
- Produces: `DELETE /evaluations/{run_id}`。

- [ ] **Step 1: 写失败 API 测试**

```python
def test_import_creates_private_pending_run(client, admin_token, workbook_bytes) -> None:
    response = client.post(
        "/evaluations/import",
        headers={"Authorization": f"Bearer {admin_token}"},
        data={"name": "首轮基线", "dialect": "hive", "system_time": "2026-08-24"},
        files={"file": ("cases.xlsx", workbook_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert response.json()["total_cases"] == 1
```

补充测试：未认证返回 401；非法日期、方言、文件、缺值返回稳定 4xx；其他用户读取/运行/删除返回 404；列表不含完整需求和 SQL；详情接口才返回三方 SQL；重复 run 返回当前状态且只启动一个线程；删除级联案例；模板下载可被 openpyxl 打开且没有业务样例。

- [ ] **Step 2: 运行 API 测试并确认路由不存在**

```powershell
pytest tests/test_evaluations.py -q
```

Expected: 首个请求 FAIL with HTTP 404。

- [ ] **Step 3: 定义 DTO 和安全序列化器**

列表 DTO 只包含任务元数据和汇总；案例列表 DTO 只返回序号、状态、分数、严格通过、主诊断和耗时；案例详情 DTO 才包含需求、三方 SQL、结构差异、本体证据和时间决策。所有错误响应使用 `{code, message, row_number?}`，不得回显上传单元格内容。

- [ ] **Step 4: 实现导入、模板与所有权查询**

上传按 64 KiB 分块读取并在超过配置上限时立即拒绝；不把上传内容落盘。导入成功后在一个事务中创建 run 和 cases。`_owned_run(run_id, user, db)` 和 `_owned_case(...)` 同时检查所有权，避免通过案例 ID 越权。

- [ ] **Step 5: 实现幂等后台运行与分页筛选**

`POST /{id}/run` 只允许 `pending` 或服务重启后可恢复的 `failed` 状态；在启动 daemon thread 前用条件更新把任务改为 `running`，受影响行数为零时返回当前状态。案例列表支持 `path=legacy|ontology`、`strict_pass`、`ontology_status`、`diagnosis_code`、`manual_review`、`page`、`page_size`，`page_size` 最大 100。

- [ ] **Step 6: 运行 API 与 Runner 测试**

```powershell
pytest tests/evaluation tests/test_evaluations.py -q
ruff check api/routes/evaluations.py api/schemas/evaluations.py tests/test_evaluations.py
```

Expected: 全部 PASS，Ruff 无错误。

- [ ] **Step 7: 自动提交**

```powershell
git add -- api/schemas/evaluations.py api/routes/evaluations.py api/routes/__init__.py api/main.py tests/test_evaluations.py
git commit -m "feat: 提供 SQL 评测任务接口"
```

---

### Task 7: 建立评测中心前端数据契约与任务入口

**Files:**
- Create: `frontend/src/features/evaluation/types.ts`
- Create: `frontend/src/features/evaluation/api.ts`
- Create: `frontend/src/features/evaluation/viewModel.ts`
- Create: `frontend/src/features/evaluation/EvaluationCenter.tsx`
- Create: `frontend/src/features/evaluation/evaluation.css`
- Create: `frontend/src/pages/Evaluation.tsx`
- Modify: `frontend/src/components/navigation.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/vite.config.ts`
- Create: `frontend/tests/evaluation-view-model.test.ts`

**Interfaces:**
- Produces: `EvaluationRunSummary`、`EvaluationMetric`、`EvaluationCaseSummary`、`EvaluationCaseDetail` TypeScript 类型。
- Produces: `formatMetric(numerator: number, denominator: number): string`，零分母返回“暂无可评分案例”。
- Produces: `evaluationStatusPresentation(status)` 和 `primaryDiagnosisPresentation(code)`。
- Produces: `/evaluation` 任务新建与列表页面。

- [ ] **Step 1: 写失败前端契约**

```typescript
if (formatMetric(3, 7) !== "3/7（42.9%）") {
  throw new Error("metric must include numerator, denominator and percentage");
}
if (formatMetric(0, 0) !== "暂无可评分案例") {
  throw new Error("zero denominator must not be rendered as zero percent");
}
if (primaryDiagnosisPresentation("ontology_no_match").label !== "对象概念未命中") {
  throw new Error("ontology failure must be actionable");
}
```

补充验证 `pending/running/completed/failed` 文案，人工复核不显示为错误零分，导航在 `/evaluation/12` 仍选中评测中心。

- [ ] **Step 2: 编译契约并确认模块不存在**

```powershell
$testOut = Join-Path ([System.IO.Path]::GetTempPath()) 'evaluation-view-model-test.cjs'
& '.\node_modules\.bin\esbuild.cmd' '.\tests\evaluation-view-model.test.ts' --bundle --platform=node --format=cjs --outfile=$testOut
node $testOut
```

Expected: FAIL resolving `viewModel`。

- [ ] **Step 3: 实现稳定前端类型、API 与文案模型**

API 方法固定为：

```typescript
downloadEvaluationTemplate(): Promise<void>
importEvaluation(input: ImportEvaluationInput): Promise<EvaluationRunSummary>
startEvaluation(runId: number): Promise<EvaluationRunSummary>
listEvaluations(): Promise<EvaluationRunSummary[]>
fetchEvaluation(runId: number): Promise<EvaluationRunDetail>
deleteEvaluation(runId: number): Promise<void>
```

上传使用 `FormData`，模板下载从 `Content-Disposition` 读取文件名。错误映射优先使用后端安全 `message`，不把 Axios 整个响应对象展示到页面。

- [ ] **Step 4: 实现新建任务和任务列表**

页面顶部沿用当前高级工作台风格，明确标注“静态结构评测，不执行 SQL”。新建区包含任务名、`.xlsx` 文件、Hive 方言、基准时间、模板下载和额度提醒；默认日期为当天但必须由用户确认后提交。任务列表展示进度、案例数、本体生成率、Legacy/本体严格通过率、平均分、本体版本和创建时间，点击进入 `/evaluation/{id}`。

运行中的页面每 1.5 秒刷新列表；页面卸载或任务无 running 状态时停止定时器。导入成功后立即调用 start，再跳转详情；重复点击按钮期间前端禁用提交。

- [ ] **Step 5: 注册路由、导航和开发代理**

在 `NAV_ITEMS` 中把“评测中心”放在“本体工作台”之后；`App.tsx` 的两个路径共用 `Evaluation` 页面，由页面读取可选 `runId`；Vite 增加：

```typescript
"/evaluations": "http://127.0.0.1:8001",
```

- [ ] **Step 6: 运行前端契约和 production build**

```powershell
$testOut = Join-Path ([System.IO.Path]::GetTempPath()) 'evaluation-view-model-test.cjs'
& '.\node_modules\.bin\esbuild.cmd' '.\tests\evaluation-view-model.test.ts' --bundle --platform=node --format=cjs --outfile=$testOut
node $testOut
npm run build
```

Expected: 契约退出 `0`，TypeScript 与 Vite build 成功，仅允许项目既有的大 chunk 警告。

- [ ] **Step 7: 自动提交**

```powershell
git add -- frontend/src/features/evaluation/types.ts frontend/src/features/evaluation/api.ts frontend/src/features/evaluation/viewModel.ts frontend/src/features/evaluation/EvaluationCenter.tsx frontend/src/features/evaluation/evaluation.css frontend/src/pages/Evaluation.tsx frontend/src/components/navigation.ts frontend/src/App.tsx frontend/vite.config.ts frontend/tests/evaluation-view-model.test.ts frontend/tsconfig.tsbuildinfo
git commit -m "feat: 增加 SQL 评测中心入口"
```

---

### Task 8: 展示汇总指标、案例筛选与三方 SQL 详情

**Files:**
- Modify: `frontend/src/features/evaluation/types.ts`
- Modify: `frontend/src/features/evaluation/api.ts`
- Modify: `frontend/src/features/evaluation/viewModel.ts`
- Create: `frontend/src/features/evaluation/EvaluationRunView.tsx`
- Modify: `frontend/src/features/evaluation/evaluation.css`
- Modify: `frontend/src/pages/Evaluation.tsx`
- Modify: `frontend/tests/evaluation-view-model.test.ts`

**Interfaces:**
- Consumes: Task 6 案例分页与详情 API、Task 7 状态展示函数。
- Produces: `listEvaluationCases(runId, filters)` 和 `fetchEvaluationCase(runId, caseId)`。
- Produces: `/evaluation/:runId` 汇总、案例列表和详情抽屉。

- [ ] **Step 1: 扩展失败契约覆盖筛选和差异文案**

验证筛选参数只发送非空值；`missing/extra/conflicts` 分别显示“缺失/多余/冲突”；`ontology_no_match`、`partition_mismatch`、`reference_parse_failed` 和 `manual_review_required` 显示不同层级与下一步建议；`score=null` 显示“不可评分”而非 0 分。

- [ ] **Step 2: 运行契约并确认新函数不存在**

运行 Task 7 的 esbuild 命令。Expected: FAIL，提示缺少筛选或差异格式函数。

- [ ] **Step 3: 实现任务汇总视图**

顶部展示任务状态、进度、方言、基准时间、本体包版本与删除操作；核心指标同时展示分子、分母和百分比。Legacy 与本体严格通过率、平均分采用成对卡片；六维指标采用紧凑比较表；失败归因使用按数量排序的横向条，不引入图表库。

运行中每 1.5 秒轮询任务详情，`completed/failed` 后停止；任务失败仍展示已经完成案例和安全错误码。

- [ ] **Step 4: 实现案例列表与服务端筛选**

列表列为：案例号、需求摘要、Legacy 得分/严格通过、本体状态、本体得分/严格通过、主失败原因、人工复核和耗时。筛选器支持路径、严格通过、本体状态、失败原因和人工复核；分页改变时重新请求，不在浏览器持有全部敏感案例。

- [ ] **Step 5: 实现三方 SQL 与结构差异详情**

点击案例打开宽抽屉。顶部先显示主失败原因和六维结果，再用三个可切换 SQL 面板展示真实、Legacy、本体 SQL；没有本体 SQL 时展示明确状态，不显示空代码框。下方展示 missing/extra/conflicts、本体概念/字段/关系/规则和时间决策。提供复制单份 SQL，不提供执行按钮。

- [ ] **Step 6: 实现删除确认与安全响应式布局**

删除弹窗明确“会删除需求原文和三方 SQL，无法恢复”；成功后返回任务列表。桌面汇总采用两列，案例表横向滚动，SQL 详情在宽屏三栏、窄屏 Tabs；任何宽度都不截断失败原因和账期值。

- [ ] **Step 7: 运行前端契约和 production build**

```powershell
$testOut = Join-Path ([System.IO.Path]::GetTempPath()) 'evaluation-view-model-test.cjs'
& '.\node_modules\.bin\esbuild.cmd' '.\tests\evaluation-view-model.test.ts' --bundle --platform=node --format=cjs --outfile=$testOut
node $testOut
npm run build
```

Expected: 契约退出 `0`，build 成功，仅允许项目既有的大 chunk 警告。

- [ ] **Step 8: 自动提交**

```powershell
git add -- frontend/src/features/evaluation/types.ts frontend/src/features/evaluation/api.ts frontend/src/features/evaluation/viewModel.ts frontend/src/features/evaluation/EvaluationRunView.tsx frontend/src/features/evaluation/evaluation.css frontend/src/pages/Evaluation.tsx frontend/tests/evaluation-view-model.test.ts frontend/tsconfig.tsbuildinfo
git commit -m "feat: 展示 SQL 评测结果与归因"
```

---

### Task 9: 记录工程实践并启动可验收版本

**Files:**
- Modify: `docs/project-journal/2026-08.md`

**Interfaces:**
- Consumes: Task 1–8 的实现和聚焦验证结果。
- Produces: 可用于复盘和简历的评测体系建设记录；保持 `8001` 与 `5199` 服务运行。

- [ ] **Step 1: 追加项目难点与解决方式**

记录以下内容：静态评测与真实结果正确率的边界；SQL 文本到 AST 的稳定标准化；分区条件与普通口径拆分；不可评分分母处理；本体包版本锁定；敏感 SQL 的存储和日志边界；后台任务幂等与断点继续；如何把失败归因反馈到本体建设优先级。

简历素材突出“搭建本体驱动 Text-to-SQL 的离线评测体系”，避免声称尚未通过真实结果集验证的准确率。

- [ ] **Step 2: 执行最终聚焦验证**

```powershell
pytest tests/evaluation tests/test_evaluations.py tests/test_orchestrator.py tests/test_ontology_shadow.py -q
ruff check evaluation api/routes/evaluations.py api/schemas/evaluations.py models/evaluation_run.py models/evaluation_case.py tests/evaluation tests/test_evaluations.py
npm run build
```

Expected: 指定 Python 测试全部 PASS；Ruff 无错误；前端 build 成功，仅允许项目既有的大 chunk 警告。

- [ ] **Step 3: 执行数据库迁移并启动服务**

在当前开发环境先运行 `alembic upgrade head`。后端继续使用根 `.env` 和：

```text
ONTOLOGY__MANAGEMENT_ROOT=C:\Users\94918\AppData\Local\Temp\ontology-agent-management-dev
```

确认：

```text
http://127.0.0.1:8001/health
http://127.0.0.1:8001/ready
http://127.0.0.1:5199/evaluation
```

后端 `/health` 返回 200，前端经代理下载模板成功，评测中心能选择用户已填写的 Excel。除非用户明确点击开始评测，不替用户运行包含真实测试集的模型调用。

- [ ] **Step 4: 自动提交工程记录**

```powershell
git add -- docs/project-journal/2026-08.md
git commit -m "docs: 记录 SQL 评测体系建设实践"
```

- [ ] **Step 5: 保持服务运行并交给用户验收**

优先请用户体验：模板下载、测试集导入、基准时间设置、任务进度、汇总指标、失败筛选和三方 SQL 详情。用户验收后再根据真实评测结果决定优先补本体、规划器还是编译器。

---

## Implementation Order and Checkpoints

1. Task 1–3 构成纯 Python 评测内核，不依赖数据库或页面，可独立验收 SQL 评分是否可信。
2. Task 4–6 构成可恢复后端评测服务，可通过 API 上传虚拟工作簿并读取结果。
3. Task 7 先交付可见的评测入口和任务进度；Task 8 再交付完整结果分析页面，符合分块改造偏好。
4. Task 9 只做聚焦验证、迁移、工程记录和服务启动，不在用户体验前追加大范围审查。

每个 checkpoint 如果发现 SQLGlot 无法可靠解析用户测试集中的某类 Hive 语法，应把对应案例标记为 `manual_review_required` 并记录不支持结构；不得通过正则兜底或扩大到 SQL 执行方案。
