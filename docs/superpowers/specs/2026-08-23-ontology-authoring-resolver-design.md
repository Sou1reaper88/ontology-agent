# 本体编辑工作流与 OntologyResolver 设计

## 1. 背景

Python 本体内核已经能够安全加载版本化 RDF/Turtle 本体包、执行 SHACL 校验，并以原子方式发布不可变快照。当前缺口是：项目尚未定义一套可供业务人员稳定编辑的 RDF 词汇，也没有把图中的概念、属性、关系和规则转换成面向 Agent 的 Python 查询接口。

本阶段优先构建真正影响智能体语义理解的本体内容与 Resolver，不先开发本体编辑前端。前端只是编辑入口之一，不能替代稳定的本体模型、约束和版本契约。

## 2. 目标

本阶段交付以下能力：

1. 定义平台无关的概念、属性、关系、业务规则和物理映射词汇。
2. 支持使用 Protégé 编辑位于应用仓库之外的私有本体包。
3. 提供空白本体包初始化、校验和检查命令。
4. 将有效 RDF 快照解析为不可变 Python DTO。
5. 提供按 URI、短名、显示名称查询及确定性文本检索的 `OntologyResolver`。
6. 为后续 MappingRegistry、QueryPlan、编译器和 Agent 旁路评估建立稳定边界。

## 3. 非目标

本阶段不包含：

- 本体 Web 编辑器。
- Excel、数据库或其他格式导入器。
- 物理映射冲突选择和数据库连接。
- QueryPlan 生成或校验。
- SQL 编译和执行。
- 将现有 Agent 切换到新本体链路。
- 通过 REST API 修改或发布本体文件。
- 在应用仓库中提交真实业务本体、业务样例或测试集。

## 4. 总体架构

```text
Protégé / VS Code
       │
       ▼
外部私有本体仓库
├── manifest.yaml
├── core.ttl
├── domain.ttl
├── rules.ttl
├── mappings.ttl
└── shapes.ttl
       │
       ▼
python -m ontology_core init | validate | inspect
       │
       ▼
OntologyRepository ──发布──> 不可变 RDF 快照
                               │
                               ▼
                       OntologyResolver
                       ├── 标识符查询
                       ├── 概念与属性查询
                       ├── 关系与规则查询
                       └── 确定性文本检索
```

真实本体包由独立私有 Git 仓库或受控目录管理。应用只读取配置指定的目录，不在运行时修改源文件。通用 RDF 词汇、SHACL 约束和空白文件骨架可以作为 Python 包资源发布，但不得包含领域概念、真实表字段、用户数据或业务口径。

## 5. 标准优先的 RDF 词汇

### 5.1 命名与标识

- 每个语义元素使用调用方提供的稳定绝对 URI。
- `rdfs:label` 用于显示名称，可包含语言标签。
- `rdfs:comment` 用于业务说明。
- 项目扩展属性 `oa:shortName` 用于 API、QueryPlan 和人工引用。
- 同一有效本体包内，`oa:shortName` 必须全局唯一。
- Resolver 的首选显示名称按中文标签、无语言标签、其他语言标签的顺序确定；同层级按规范化文本稳定排序。

`oa` 仅代表由本项目定义的通用扩展命名空间，实际 URI 在通用词汇文件中固定，不携带具体客户、平台或数据库信息。

### 5.2 Concept

领域概念使用 `owl:Class`：

- `oa:shortName`：稳定短名。
- `rdfs:label`：显示名称。
- `rdfs:comment`：可选说明。
- `rdfs:subClassOf`：父概念。

概念不得直接包含表名、字段名、SQL 方言或连接配置。

### 5.3 Property 与 Relation

- 数据属性使用 `owl:DatatypeProperty`。
- 概念关系使用 `owl:ObjectProperty`。
- `rdfs:domain` 声明属性或关系的源概念。
- 数据属性使用 XSD 类型作为 `rdfs:range`。
- 对象属性使用目标概念作为 `rdfs:range`。
- 必填、多值、基数等约束由 SHACL 表达，不通过物理数据库字段推断。

Resolver 对外将 `owl:DatatypeProperty` 转换为 `Property` DTO，将 `owl:ObjectProperty` 转换为 `Relation` DTO。

### 5.4 BusinessRule

业务规则使用 `oa:BusinessRule` 个体，至少包含：

- `oa:shortName`、`rdfs:label` 和可选 `rdfs:comment`。
- `oa:appliesTo`：适用概念。
- `oa:usesProperty`：引用的数据属性。
- `oa:usesRelation`：引用的对象关系。
- `oa:condition`：可选结构化条件树根节点。
- `oa:status` 和 `oa:priority`：状态与优先级。

条件树首期只允许通用逻辑节点 `AllOf`、`AnyOf`、`Not`，以及比较节点 `Eq`、`Ne`、`Gt`、`Gte`、`Lt`、`Lte`、`In`、`Between`、`IsNull`。比较左值引用属性 URI，右值只能是 RDF 字面量或参数引用，不接受任意 SQL 文本。

本阶段负责读取和验证条件结构，不执行规则，也不把规则编译成 SQL。

### 5.5 DataSource 与 PhysicalMapping

本阶段定义并解析基础映射 DTO，但不实现映射选择策略：

- `oa:DataSource` 使用稳定逻辑 ID、平台类型、可选方言和能力标签。
- `oa:PhysicalMapping` 指向一个概念、属性或关系及一个逻辑数据源。
- 映射可包含物理命名空间、对象名、字段名、JOIN 路径、优先级和启用状态。
- 本体包不得保存主机地址、端口、账号、密码、令牌或其他连接凭据。

映射冲突选择、缺失映射处理和数据源能力匹配由后续 `MappingRegistry` 负责。

## 6. Python DTO 与 Resolver 契约

新增不可变 Pydantic DTO：

- `Concept`
- `Property`
- `Relation`
- `BusinessRule`
- `RuleExpression`
- `DataSource`
- `PhysicalMapping`

DTO 只包含标准 Python 类型、URI 字符串和元组，不暴露 RDFLib 的 `Graph`、`URIRef`、`Literal` 或可修改集合。

`OntologyResolver` 首期公开同步只读接口：

```python
list_concepts()
get_concept(identifier)
search_concepts(text)
list_properties(concept_id)
resolve_property(concept_id, property_id)
list_relations(concept_id)
list_rules(concept_id)
```

Resolver 在快照发布后一次性构建只读索引，请求期间不重复遍历 RDF 图。每个 Resolver 实例绑定一个确定快照，后续发布新快照不会改变已有实例的读取结果。

标识符查询顺序：

1. 绝对 URI 精确匹配。
2. `oa:shortName` 精确匹配。
3. 首选显示名称精确匹配。

文本检索顺序：

1. URI 或短名精确匹配。
2. 显示名称精确匹配。
3. 短名前缀匹配。
4. 显示名称包含匹配。
5. 描述包含匹配。

文本在比较前执行 Unicode NFKC 规范化、去除两端空白和不区分大小写比较。结果按匹配等级、规范化短名、URI 排序，从而保证重复运行和跨进程结果一致。首期不依赖 LLM、分词器、向量数据库或外部搜索服务。

## 7. 编辑与发布工作流

### 7.1 初始化

规范命令为：

```text
python -m ontology_core init <目录> --package-id <ID> --base-uri <URI> [--version <版本>]
```

可选安装控制台别名 `ontology-core`。实现使用 Python 标准库参数解析，不为首期 CLI 引入额外框架。

`--version` 默认使用 `0.1.0`。`init` 创建清单、项目通用词汇、SHACL 约束和空白领域文件。目标目录非空时默认拒绝覆盖。生成结果不包含业务样例或真实平台名称。

### 7.2 Protégé 编辑

- 在 Classes 视图编辑概念和继承关系。
- 在 Data Properties 视图编辑数据属性。
- 在 Object Properties 视图编辑概念关系。
- 在 Individuals 视图编辑规则、逻辑数据源和物理映射。
- 通用词汇和 SHACL 约束默认只读，修改时需要显式版本升级和代码审查。

项目提供独立编辑指南，说明模块边界、稳定 URI、短名、语言标签和禁止存储的信息。

### 7.3 校验与检查

```text
python -m ontology_core validate <目录> [--json]
python -m ontology_core inspect <目录> [--json] [--list-identifiers]
```

- `validate` 执行清单、路径、Turtle、SHACL 和语义引用校验。
- `inspect` 只对有效包输出版本、摘要和各类元素数量；只有显式传入 `--list-identifiers` 才输出稳定标识列表。它始终不打印完整描述、规则字面量或物理名称。
- 成功退出码为 `0`，输入或校验失败为非零。
- `--json` 输出稳定机器可读结构，便于 CI 和后续前端复用。

### 7.4 版本与运行

1. 编辑者运行本地校验和检查。
2. 人工审查本体差异。
3. 将本体包提交到独立私有 Git 仓库。
4. 应用通过环境变量读取已检出的包目录。
5. 只有通过全部校验的候选包才能替换当前快照。
6. 重载失败时保留最后一个有效快照。

本阶段不实现在线写入、自动覆盖、审批或远程发布接口。

## 8. 校验与错误处理

pySHACL 负责图结构约束，补充的 Python 语义校验负责不适合单纯 SHACL 表达或需要稳定聚合报告的规则，包括全局短名唯一性、引用解析、条件树合法性和确定性错误排序。

新增稳定错误码：

- `concept_not_found`
- `property_not_found`
- `ambiguous_identifier`
- `invalid_rule_expression`
- `invalid_ontology_reference`

继续复用：

- `package_not_found`
- `ontology_parse_error`
- `ontology_validation_error`

CLI 可以显示本地文件路径、焦点节点和具体违规信息。未来 REST 层只能返回脱敏信息，不暴露服务器绝对路径、连接配置或业务内容。错误列表按错误码、语义元素 URI、字段路径和消息稳定排序。

## 9. 测试设计

### 9.1 基线前置处理

在功能实现前，先定位并以独立提交修复当前全量测试中的历史乱码失败。该修复不与 Resolver 功能混合，确保后续验收基于绿色测试基线。

### 9.2 单元测试

- RDF 节点到各 DTO 的转换。
- 概念继承、属性归属、关系方向和规则引用。
- 多语言标签选择和 Unicode 规范化。
- URI、短名和显示名称查询。
- 检索分级、排序和跨进程确定性。
- 重复短名、悬空引用和非法条件树。
- Resolver 与快照之间的隔离性。

### 9.3 CLI 契约测试

- `init` 生成完整、可校验且不含业务样例的空白包。
- 非空目录不会被意外覆盖。
- `validate` 的退出码、文本输出和 JSON 错误结构稳定。
- `inspect` 的统计、版本和摘要与 Repository 一致。
- 输出不包含连接凭据或未请求的完整业务内容。

### 9.4 安全与数据约束

- 测试只使用 `example.invalid` 命名空间和中性虚构概念。
- 测试夹具位于测试目录或临时目录，不作为生产默认本体加载。
- 用户后续提供的测试集通过外部路径参数化接入，不复制到生产代码。
- 提交前扫描禁止出现的真实表名、字段名、用户数据和业务敏感口径。

## 10. 验收标准

1. 用户可以初始化一个不含业务样例的外部本体包，并在 Protégé 中打开和保存。
2. 有效包通过 CLI 校验，无效包返回稳定、可定位的结构化错误。
3. `inspect` 可以安全展示版本、摘要和元素统计。
4. Resolver 能正确返回概念、属性、关系和规则 DTO。
5. URI、短名、显示名称查询及文本检索具有确定性结果。
6. 数据库和 SQL 方言信息只存在于映射层，领域概念保持平台无关。
7. 新包加载失败时不会替换最后一个有效快照。
8. 不修改现有 Agent、SQL 编译器、执行器和前端运行行为。
9. 新增测试通过，修复后的全量测试基线保持绿色。
10. 设计、基线修复、词汇、DTO、Resolver、CLI、文档和测试形成独立 Git 提交。

## 11. 后续顺序

完成本阶段后按以下顺序继续：

1. `MappingRegistry`：映射选择、冲突和数据源能力。
2. `QueryPlan` 与验证器：稳定智能体到编译器的中间表示。
3. 现有 Agent 旁路适配器：使用外部测试集比较新旧链路。
4. REST API：对外提供稳定只读能力。
5. 前端状态页和编辑器：在接口稳定后提供可视化入口。

前端、Excel 和数据库导入最终都只作为同一本体包的编辑或导入入口，不改变 RDF/OWL 事实源和 Resolver 契约。
