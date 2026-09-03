# 元数据候选推断与多步骤评测实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在已发布本体只有表、字段和时间策略但缺少关系、口径时，由大模型生成无 SQL 的结构化候选计划，经 Python 校验与确定性编译后输出不可执行的 Hive 建表脚本，并让真实多步骤参考 SQL 能进入结构评测。

**Architecture:** 严格本体链路继续作为最高优先级；新增独立的“元数据候选目录 → 确定性召回 → LLM 结构化推断 → Python 安全校验 → 候选程序编译”链路。候选链路只能引用活动本体快照中的稳定对象和字段，不把推断关系伪装成已确认本体事实，也不写回草稿。评测侧新增完整 Hive 程序解析器，按最终物理源表、字段、关联、过滤、分区和查询形态比较，忽略系统临时表名。

**Tech Stack:** Python 3.13、Pydantic v2、SQLGlot Hive dialect、FastAPI、SQLAlchemy JSON、React/TypeScript、pytest、Vitest。

## 全局约束

- 只读取不可变的已发布本体快照；用户在前台编辑的草稿必须显式发布后才进入智能取数和评测。
- 模型只输出结构化引用、推断理由、置信度和改进建议，不输出 SQL、物理目标表名或目录外标识符。
- 候选程序状态固定为 `inferred_program`，必须标注“LLM 推断、未经本体确认、不可自动执行”。
- 关系未确认可以进入候选计划，但多表计划必须存在字段级等值连接；禁止无条件 JOIN 和笛卡尔积。
- 表族只能由已发布、同数据源、同字段签名且时间策略兼容的对象组成；不得按命名规律补造缺失成员。
- SQL 仅生成 `DROP TABLE IF EXISTS` + `CREATE TABLE AS SELECT`，不追加末尾清理语句，不调用执行接口。
- 候选关系和口径不自动写回本体，只在响应中输出本体改进建议。
- 每个逻辑任务先写失败测试，再做最小实现；每个任务完成后自动 Git 提交，不自动推送或合并。
- 用户可见切片完成后优先启动服务供人工查看，不进行与该切片无关的大范围审查。

## 文件职责

- `ontology_core/inference_models.py`：候选目录、LLM 草案、已校验候选计划、证据和失败合同。
- `ontology_core/metadata_candidates.py`：从 `OntologySnapshot` 构建只读候选目录、相关性排序和同构表族。
- `ontology_core/inference_validation.py`：引用、字段归属、类型、JOIN、过滤来源、表族和时间边界校验。
- `ontology_core/inference_compiler.py`：将已校验候选计划确定性编译为 `CompiledProgram`。
- `tools/llm_client.py`：请求并验证 `InferredProgramDraft` JSON；不接收或返回 SQL。
- `agent/metadata_inference.py`：编排召回、推断、校验和编译，输出候选证据或可行动缺失项。
- `agent/program_generation.py`：在严格本体失败后进入候选链路，并停止默认静默回退到旧 SQL。
- `agent/orchestrator.py`、`api/routes/conversation.py`：透传 `inferred_program`、证据、置信度、未确认项和建议。
- `frontend/src/features/chat/*`：展示候选标签和证据，保持编辑/执行按钮关闭。
- `evaluation/program_structure.py`：解析完整 Hive 建表程序并还原最终源表和步骤依赖。
- `evaluation/program_comparison.py`：程序级结构比较。
- `evaluation/generation.py`、`evaluation/runner.py`：记录生成模式并按程序结构评测。

### Task 1：定义候选推断的封闭数据合同

**Files:**
- Create: `ontology_core/inference_models.py`
- Modify: `ontology_core/__init__.py`
- Create: `tests/ontology_core/test_inference_models.py`

**Core interfaces:**

```python
class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class CandidateObject(FrozenModel):
    ref: SemanticRef
    label: str
    description: str | None
    data_source_ref: str
    physical_namespace: str | None
    physical_name: str
    fields: tuple[CandidateField, ...]
    temporal_policy: CandidateTemporalPolicy | None
    family_ref: str | None = None

class InferredJoinDraft(FrozenModel):
    left_object_ref: SemanticRef
    left_field_ref: SemanticRef
    right_object_ref: SemanticRef
    right_field_ref: SemanticRef
    confidence: Confidence
    evidence: tuple[str, ...]

class InferredProgramDraft(FrozenModel):
    selected_object_refs: tuple[SemanticRef, ...]
    selected_family_refs: tuple[str, ...] = ()
    requested_field_refs: tuple[SemanticRef, ...]
    joins: tuple[InferredJoinDraft, ...] = ()
    filters: tuple[InferredFilterDraft, ...] = ()
    time_expression: str | None = None
    unresolved_items: tuple[str, ...] = ()
    ontology_suggestions: tuple[str, ...] = ()

class ValidatedInferredProgram(FrozenModel):
    package_id: str
    package_version: str
    package_sha256: str
    data_source_ref: str
    dialect: str
    objects: tuple[CandidateObject, ...]
    requested_fields: tuple[CandidateFieldBinding, ...]
    joins: tuple[ValidatedInferredJoin, ...]
    filters: tuple[ValidatedInferredFilter, ...]
    temporal_decisions: tuple[ValidatedInferenceTemporalDecision, ...]
    evidence: InferenceEvidence
```

- [x] 写失败测试：额外字段（`sql`、`target_table`、任意物理标识）被拒绝；对象/字段引用格式、置信度、空依据、重复引用和 JSON 往返符合约束。
- [x] 运行 `D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/ontology_core/test_inference_models.py -q`，确认先失败。
- [x] 实现冻结、`extra="forbid"` 的合同，并只在合同层校验内在结构，不访问本体状态。
- [x] 运行聚焦测试与 `ruff`。
- [x] 自动提交：`feat: 定义元数据候选推断合同`。

### Task 2：构建活动本体候选目录、召回与表族识别

**Files:**
- Create: `ontology_core/metadata_candidates.py`
- Create: `tests/ontology_core/test_metadata_candidates.py`
- Modify: `ontology_core/resolver.py`

**Interfaces:**

```python
class MetadataCandidateCatalog:
    @classmethod
    def from_snapshot(cls, snapshot: OntologySnapshot) -> "MetadataCandidateCatalog": ...
    def retrieve(self, request: str, *, object_limit: int = 8,
                 field_limit_per_object: int = 40) -> CandidateContext: ...
    def object(self, ref: str) -> CandidateObject: ...
    def field(self, ref: str) -> CandidateFieldBinding: ...
    def family(self, ref: str) -> CandidateTableFamily: ...
```

- [x] 写失败测试：召回使用表名、表中文名、表描述、字段名、字段中文名和字段描述；返回稳定排序；物理标识来自映射而非文本猜测。
- [x] 写表族测试：同数据源、同字段名/类型签名、同分区粒度/策略且物理名仅一个地域段不同才成族；指定地市只保留对应成员；全省返回所有已发布成员；缺失 `NB` 时绝不创建 Ningbo 成员。
- [x] 使用简单可解释的归一化词匹配与字段覆盖度评分，不引入向量数据库；保留召回分数和命中片段供模型说明。
- [x] 运行聚焦测试、resolver 回归和 `ruff`。
- [x] 自动提交：`feat: 构建本体元数据候选目录`。

### Task 3：增加 LLM 结构化候选推断调用

**Files:**
- Modify: `tools/llm_client.py`
- Create: `tests/test_metadata_inference_llm.py`

**Interfaces:**

```python
def infer_metadata_program(
    self,
    *,
    system_prompt: str,
    request: str,
    candidates: CandidateContext,
    conversation_context: str | None,
) -> InferredProgramDraft: ...
```

- [ ] 写失败测试：请求中包含需求、候选目录、对话上下文和 JSON Schema；系统提示明确禁止 SQL、目录外引用与事实化表述。
- [ ] 复用现有 `_generate` 和 JSON fence 清理逻辑；Pydantic 验证失败统一转换为不泄露模型原文的 `StructuredPlanningError`。
- [ ] 确认候选目录经过对象/字段上限裁剪，并计入现有上下文 Token 预算，而不是注入 1,270 个字段。
- [ ] 运行聚焦测试、`tests/test_program_planner.py` 和 `ruff`。
- [ ] 自动提交：`feat: 增加结构化元数据推断调用`。

### Task 4：实现 Python 候选安全校验和时间决策

**Files:**
- Create: `ontology_core/inference_validation.py`
- Create: `tests/ontology_core/test_inference_validation.py`
- Reuse: `ontology_core/temporal.py`

**Interfaces:**

```python
class InferenceValidationResult(FrozenModel):
    plan: ValidatedInferredProgram | None
    diagnostics: tuple[ProgramDiagnostic, ...]
    missing_information: tuple[str, ...]

class MetadataInferenceValidator:
    def validate(self, draft: InferredProgramDraft, *, catalog: MetadataCandidateCatalog,
                 system_time: datetime, request: str,
                 snapshot: OntologySnapshot) -> InferenceValidationResult: ...
```

- [ ] 写失败测试：目录外引用、字段归属错误、跨数据源、类型不兼容 JOIN、多表无 JOIN、连接图不连通、无依据过滤、冲突账期、无界时间和不兼容表族均拒绝。
- [ ] 写通过测试：字段名/描述相似的等值 JOIN 可作为未确认候选；关系置信度最高降为 `medium`；默认时间复用已发布表策略并解析系统时间 T-2/上月。
- [ ] 过滤值只能来自用户原文、已发布规则，或可定位的字段元数据证据；模型理由不能单独成为值来源。
- [ ] 无安全计划时返回具体缺失信息（缺哪张表、哪个关联键、哪项口径），不调用旧 SQL 伪造结果。
- [ ] 运行聚焦测试、temporal 回归和 `ruff`。
- [ ] 自动提交：`feat: 校验候选关系口径与账期`。

### Task 5：确定性编译候选 Hive 建表程序

**Files:**
- Create: `ontology_core/inference_compiler.py`
- Modify: `ontology_core/program_models.py`
- Create: `tests/ontology_core/test_inference_compiler.py`

**Interfaces:**

```python
class HiveInferenceCompiler:
    def compile(self, plan: ValidatedInferredProgram, *, program_id: str) -> CompiledProgram: ...
```

- [ ] 写失败测试：单表过滤、双表等值关联、指定城市单成员、全省同构表族 `UNION ALL`、字段投影和默认分区生成精确 SQL。
- [ ] 目标表名继续使用 `ProgramTableNamer`；源表/字段只从已校验绑定获取；标识符统一引用，值统一按类型构造 SQLGlot Literal。
- [ ] 表族先生成一个系统中间步骤，各成员投影同一字段集合并各自带分区条件，再由后续步骤消费；不生成目录外成员。
- [ ] 复用 `HiveProgramCompiler.validate_program` 验证 DROP/CREATE 配对、依赖顺序、无悬空临时表和源表不成为目标表。
- [ ] 在 `ProgramCompilationEvidence` 增加可序列化的候选依据、置信度、未确认项和本体建议，不把候选关系写入 `relations`（该字段只保留已确认本体 URI）。
- [ ] 运行聚焦测试、现有 program compiler 回归和 `ruff`。
- [ ] 自动提交：`feat: 编译候选 Hive 取数程序`。

### Task 6：接入 run_agent、会话 API 与候选展示

**Files:**
- Create: `agent/metadata_inference.py`
- Modify: `agent/program_generation.py`
- Modify: `agent/orchestrator.py`
- Modify: `api/routes/conversation.py`
- Modify: `frontend/src/features/chat/types.ts`
- Modify: `frontend/src/features/chat/messagePresentation.ts`
- Modify: `frontend/src/features/chat/MessageTimeline.tsx`
- Modify: `frontend/src/features/chat/chat-components.css`
- Create: `tests/test_metadata_inference.py`
- Modify: `tests/test_program_generation.py`
- Modify: `tests/test_orchestrator.py`
- Modify: `frontend/tests/chat-program-presentation.test.ts`

- [ ] 写失败测试覆盖优先级：严格 `program` 成功时不调用推断；严格链路因缺关系/口径失败且存在对象元数据时调用推断；推断成功返回 `inferred_program`；推断不安全时返回缺失信息；只有显式兼容开关才允许旧链路回退。
- [ ] `ProgramGenerationResult` 增加推断证据字段，`_program_payload` 和 `ProgramSummary` 完整透传；活动快照在推断到编译间变化时中止。
- [ ] 前端在 SQL 面板显示橙色“候选推断”标签、置信度、依据、未确认项和“如何补充本体”；候选程序与确认程序一样不能编辑、不能执行，只能复制。
- [ ] 响应正文自然说明这是候选结果，不增加硬编码问答分支；所有会话输入输出仍由现有上下文工程提供给本轮模型调用。
- [ ] 运行 Python/前端聚焦测试和构建。
- [ ] 自动提交：`feat: 接入元数据候选推断链路`。
- [ ] 重启后端与前端，优先请用户用已发布的补表本体查看首个可见版本。

### Task 7：解析并比较完整多步骤 Hive 程序

**Files:**
- Create: `evaluation/program_structure.py`
- Create: `evaluation/program_comparison.py`
- Create: `tests/evaluation/test_program_structure.py`
- Create: `tests/evaluation/test_program_comparison.py`
- Modify: `evaluation/contracts.py`
- Modify: `evaluation/generation.py`
- Modify: `evaluation/runner.py`
- Modify: `tests/evaluation/test_runner.py`

- [ ] 写失败测试：解析 2–8 条 DROP/CTAS、识别系统临时表依赖、提取最终物理源表、字段、JOIN、普通过滤、分区过滤与结果形态；拒绝 DML、悬空临时表和非配对 DDL。
- [ ] 程序结构比较忽略临时目标表名称及步骤编号，按最终来源和依赖拓扑比较；单条只读查询继续兼容为单步骤程序。
- [ ] `GenerationSnapshot` 记录 `generation_mode` 和推断证据；汇总分别统计确认本体生成率、候选推断生成率、安全拒绝率和各结构维度命中率。
- [ ] 不覆盖历史评测任务；补表或发布新版本后创建新任务与基线对比。
- [ ] 运行完整 evaluation 测试和 `ruff`。
- [ ] 自动提交：`feat: 支持多步骤取数程序评测`。

### Task 8：端到端验收、文档与服务交付

**Files:**
- Modify: `docs/ontology-authoring.md`
- Modify: `docs/project-journal/2026-09.md`
- Modify as needed: API/frontend evaluation presentation files

- [ ] 使用合成 fixture 验收：只有表字段元数据且无关系/口径时能生成可校验的候选程序；没有可验证 JOIN 时给出缺失信息；不调用执行接口；不修改草稿。
- [ ] 用户完成表描述并发布后，新建评测任务运行真实 7 条测试集，保存新 run，不改动旧 run #2。
- [ ] 记录基线与新结果：源表集合、字段、JOIN、分区、生成模式和不可评分原因；真实需求和真实 SQL 不写入 Git 文档。
- [ ] 更新项目难点记录：大表元数据裁剪、未确认语义与可用性的边界、同构分表族、程序级评测。
- [ ] 运行风险相关测试：
  - `D:\Projects\ontology-agent\.venv\Scripts\python.exe -m pytest tests/ontology_core tests/evaluation tests/test_program_generation.py tests/test_orchestrator.py tests/test_conversation.py tests/test_execute.py -q`
  - `npm test -- --run`（`frontend`）
  - `npm run build`（`frontend`）
- [ ] 自动提交：`docs: 记录候选推断与程序评测结果`。
- [ ] 重启服务，报告访问地址、活动本体版本、评测 run id 和剩余缺失表/关系，不自动推送 GitHub。

## 实施顺序与人工检查点

1. Task 1–5 先完成纯 Python 候选内核，不读取或覆盖前台草稿。
2. Task 6 完成后立即启动服务，让用户先看候选 SQL、依据和不可执行标识。
3. 用户确认可见效果后再执行 Task 7 的多步骤评测升级。
4. 用户补完表描述并发布活动版本后，才运行真实测试集并完成 Task 8。
