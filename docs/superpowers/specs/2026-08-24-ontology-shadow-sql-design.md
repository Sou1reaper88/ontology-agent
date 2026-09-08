# 本体驱动 SQL 影子模式设计

## 目标

把已经完成的 Python 本体内核接入现有聊天 SQL 链路，形成用户可直接验收的最小闭环：同一个自然语言问题保留现有 SQL，同时生成一份本体驱动 SQL，并展示两者差异及本体证据。

首期只验证“本体语义能否决定查询计划和 SQL”，本体 SQL 仅预览、复制，不允许自动执行。真实业务效果在用户提供测试集后评估。

## 方案比较

### 方案 A：在现有聊天中增加影子链路（采用）

现有 Agent 正常完成后，独立运行本体规划与编译，并把结果作为结构化影子结果附加到消息中。前端在同一条回答里并排展示旧 SQL、本体 SQL、差异和证据。

优点是可见、可对比、不影响现有链路；失败时可以安全降级。代价是短期内同时维护 legacy 与 ontology 两套结果。

### 方案 B：直接用本体链路替换现有 SQL 生成

界面和数据结构最简单，但首期本体覆盖率未知，未命中的问题会直接降低现有可用性，也无法直观看出新旧差异。

### 方案 C：单独建设本体 SQL Playground

实现隔离、演示直观，但没有进入真实聊天流程，只能证明编译器可运行，不能证明 Agent 已经本体驱动。

## 可验收结果

配置一个 Git 忽略的本机脱敏本体包后，用户在聊天页输入能够命中该包的问题，应看到：

1. 原有 Agent SQL，行为保持不变并保留原执行按钮。
2. 本体驱动 SQL，明确标记为“影子预览”，仅允许复制。
3. SQL 差异摘要，包括表、字段和过滤条件的变化。
4. 本体证据，包括命中的概念、属性、业务规则、数据源和物理映射。
5. 一条新的链路步骤“本体规划与编译”，显示命中、跳过或失败状态。

本体 SQL 必须从本体包中的物理映射和规则产生，不能从 legacy SQL 改写，也不能在生产代码中硬编码演示表名、字段名或业务条件。

## 架构

```text
自然语言问题 ───────────────→ 现有 Agent ─────→ legacy SQL
       │
       └→ 本体包 → OntologyResolver → QueryPlan → SqlCompiler
                                                    │
                                                    └→ ontology SQL

legacy SQL + ontology SQL + evidence → ShadowComparison → 消息 trace → 聊天对比面板
```

### 1. 本体运行时

新增应用层 `OntologyRuntime`，从配置项 `ONTOLOGY__PACKAGE_PATH` 指定的外部目录加载本体包。它复用 `OntologyRepository` 和 `OntologyResolver`，按包摘要缓存不可变快照。

- 未配置路径：返回 `disabled`，不影响 legacy Agent。
- 包不存在或校验失败：返回安全诊断，不暴露本机路径和原始 RDF 内容。
- 首期修改本体包后通过重启服务重新加载；在线发布和热更新不在本期范围。

本地演示包位于 `.local/ontology-packages/`，整个 `.local/` 加入 Git 忽略。生产代码和提交历史中不包含演示表名、字段名、业务规则或密钥。

### 2. 与平台无关的查询计划

新增不可变 `QueryPlan`，只表达语义，不包含某一种数据库的 SQL 文本：

- 主概念和数据源；
- 选中的属性；
- 物理对象及字段绑定；
- 结构化过滤表达式；
- 命中的规则和关系；
- 形成计划的证据。

`OntologyPlanner.plan(query, resolver)` 使用确定性规则匹配概念、属性和启用的物理映射：中文/英文 label、short name 或 URI 标识符在问题中命中；同分歧义时返回 `ambiguous`，不擅自选择。首期只处理单一主概念、单数据源和该概念上的属性、规则；多表 JOIN 留给后续版本。

### 3. 可替换编译器接口

定义 `SqlCompiler` 协议：

```python
class SqlCompiler(Protocol):
    def compile(self, plan: QueryPlan) -> CompiledQuery: ...
```

首期提供确定性的 `GenericSqlCompiler`，只编译本体明确提供的 namespace、object name、field name 和结构化规则表达式。编译器不接触自然语言，也不读取 legacy SQL。后续 Hive、PostgreSQL、MySQL 等实现通过 dialect 注册表接入，不改变 Planner 和 Agent 接口。

首期支持 `eq/ne/gt/gte/lt/lte/in/between/is_null/all_of/any_of/not`；缺少字段映射、对象映射或不支持的规则时返回 `unsupported`，不生成猜测 SQL。

### 4. 影子服务与 Agent 接入

`OntologyShadowService.preview(query, legacy_sql)` 组合运行时、Planner、编译器和差异计算，返回结构化 `OntologyShadowResult`：

- `status`: `generated | no_match | ambiguous | unsupported | unavailable`；
- `ontology_sql`；
- `summary` 和结构化差异；
- `evidence`；
- 包 ID、版本和摘要短标识，不返回本机路径。

现有 `run_agent` 在 legacy 输出完成后调用影子服务。影子链路的任何异常都转换为安全的 `unavailable` 结果，不能改变 legacy SQL 的成功状态。

结果存入现有消息 `trace` JSON 的 `ontology_shadow` 步骤，避免本期引入数据库迁移。历史消息 API 从 trace 提取结构化结果；实时轮询继续使用同一个步骤对象。

### 5. 前端展示

聊天页新增 `OntologyComparison` 组件：

- 左侧显示“现有 Agent SQL”，保留执行、编辑和复制能力；
- 右侧显示“本体驱动 SQL（影子预览）”，只显示复制按钮；
- 下方显示表、字段、条件差异，以及本体证据标签；
- `no_match/ambiguous/unsupported/unavailable` 显示明确原因和下一步，不伪造 SQL；
- 没有配置本体包时不影响现有消息布局，只在链路步骤中显示未启用状态。

## 数据与安全边界

- 演示本体包不进入 Git，不在 Python、TypeScript 或配置默认值中硬编码业务样例。
- 本体包继续经过现有 URI、SHACL、凭据和资源预算校验。
- 本体 SQL 首期没有执行入口，不能创建 `QueryHistory`。
- 影子错误不能包含文件路径、原始 RDF、凭据或用户信息。
- 只使用发布快照中的结构化模型，不让 LLM直接拼接物理映射。

## 测试策略

严格采用测试驱动：先看到失败，再实现最小代码。

1. Planner 单元测试：命中、无命中、歧义、缺失映射、启用映射优先级。
2. Compiler 单元测试：字段/表编译、所有首期操作符、字面量转义、无映射 fail closed、方言注册接口。
3. Shadow 服务测试：不读取 legacy SQL 生成本体 SQL；异常降级；差异和证据确定性。
4. Agent 测试：legacy 成功不被影子失败影响；trace 包含影子步骤。
5. API 测试：实时和历史消息都返回同一结构化影子结果，且不会生成可执行 query ID。
6. 前端以 TypeScript build 和浏览器手工验收为准：双栏 SQL、差异、证据、状态降级均可见。
7. 完整 Python 测试、Ruff、Black、前端 build 和 `git diff --check` 作为提交前门禁。

## 本期不做

- 不替换 legacy SQL，不自动执行本体 SQL。
- 不做多表 JOIN、代价优化和数据库 schema 探测。
- 不做在线本体编辑、上传、发布和热更新。
- 不把自然语言理解交给 LLM；首期只用可解释的确定性匹配。
- 不用本地演示包的数据宣称真实业务准确率。

## 下一阶段

用户提供测试集后，建立批量对比评测：表命中率、字段命中率、规则覆盖率、SQL 可执行率、人工接受率和 legacy/ontology 差异分类。届时再决定扩大 Planner 能力、增加 JOIN 规划或接入特定数据库编译器。
