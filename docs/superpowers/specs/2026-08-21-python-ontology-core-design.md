# Python 本体内核首期重构设计

## 1. 背景与目标

当前项目已经具备表结构读取、字段注释、表关系、逻辑定义和 SQL 生成能力，但“本体对象”基本等同于物理表，本体检索、物理映射和 SQL 校验集中在 `DbOntologyClient` 中。业务概念与 Hive/MySQL 表结构尚未解耦，也缺少正式的 RDF/OWL 模型与 SHACL 约束。

首期重构建立一个纯 Python 的正式本体内核，使用 RDFLib 处理 RDF/OWL，使用 pySHACL 执行约束验证。新内核同时提供 Python SDK 和 REST API，并为后续多数据库、多 SQL 方言、多编译器改造提供稳定边界。

首期采用旁路接入，不替换现有 Agent、HiveSQL 生成、执行和前端行为。

## 2. 设计原则

1. 本体包是业务语义的唯一事实源，使用 Git 版本管理。
2. 业务概念、属性、关系和规则不依赖某个物理数据库或 SQL 方言。
3. 物理数据源和字段映射独立建模；同一语义属性可以映射到不同平台。
4. Python SDK 是业务实现入口，REST API 是 SDK 的薄封装。
5. 对外只暴露 Pydantic 数据模型，不泄漏 RDFLib 内部类型。
6. 现有链路保持兼容，首期不进行破坏性切换。
7. 生产代码中不硬编码电信对象、真实表名、字段名和业务口径。
8. 每个独立逻辑改动经测试验证后创建 Git 提交。

## 3. 首期范围

### 3.1 包含

- RDF/OWL 本体包加载与序列化。
- SHACL 约束加载与校验。
- 概念、属性、关系、业务规则和物理映射的读取模型。
- 本体包版本、摘要和加载状态。
- 线程安全的只读本体快照。
- Python SDK。
- REST API。
- MySQL 元数据到本体包的确定性导入能力。
- QueryPlan 数据契约及结构校验，不包含查询生成和 SQL 编译。
- 匿名、可替换的测试夹具和契约测试框架。

### 3.2 不包含

- LLM 生成 QueryPlan。
- 新 SQL 编译器。
- HiveSQL、PostgreSQL SQL、MySQL SQL 或 Spark SQL 的真实多编译器实现。
- 现有 Agent 切换到新本体服务。
- 真实 Hive/Impala 执行器。
- 本体可视化编辑器。
- 多用户在线编辑、审批和发布工作流。
- 将全部业务事实数据复制到 RDF 图存储。

## 4. 总体架构

```text
调用方 / 前端 / Agent
        │
        ├─ REST API
        └─ Python SDK
               │
               ▼
        OntologyService
        ├─ OntologyRepository
        ├─ OntologyValidator
        ├─ OntologyResolver
        ├─ MappingRegistry
        └─ QueryPlanValidator
               │
               ▼
       ontology-packages/
       └─ <package>/
          ├─ manifest.yaml
          ├─ core.ttl
          ├─ domain.ttl
          ├─ mappings.ttl
          ├─ rules.ttl
          └─ shapes.ttl
```

### 4.1 OntologyRepository

职责：

- 根据包路径和清单加载本体文件。
- 合并核心、领域、映射、规则和约束图。
- 计算内容摘要并记录包版本。
- 构建不可变的有效快照。
- 保留最后一个有效快照，避免错误版本破坏运行服务。

Repository 不负责业务搜索、物理映射选择和查询计划验证。

### 4.2 OntologyValidator

职责：

- 执行 RDF 解析校验。
- 使用 pySHACL 验证结构约束。
- 将 pySHACL 报告转换为稳定的 Pydantic 错误对象。
- 支持导入前验证和应用启动验证。

### 4.3 OntologyResolver

职责：

- 按 URI、短名和显示名称读取概念。
- 查询概念属性、父类、子类和关系。
- 查询与概念关联的业务规则。
- 提供确定性的文本搜索结果；首期不依赖 LLM 和向量数据库。

### 4.4 MappingRegistry

职责：

- 根据概念、属性和数据源解析激活的物理映射。
- 检测缺失映射和冲突映射。
- 返回与数据库无关的 `PhysicalMapping` DTO。
- 不生成 SQL，也不建立数据库连接。

### 4.5 QueryPlanValidator

职责：

- 验证 QueryPlan 引用的概念、属性、关系和规则是否存在。
- 验证指定数据源是否具有所需物理映射。
- 返回结构化问题列表。
- 不负责自然语言理解和 SQL 编译。

## 5. 本体元模型

### 5.1 Concept

表示领域业务概念，至少包含：

- URI。
- 稳定短名。
- 显示名称。
- 可选描述。
- 父概念集合。
- 状态与版本信息。

概念不得直接携带 Hive、MySQL 或 PostgreSQL 表名。

### 5.2 Property

表示概念属性，至少包含：

- URI。
- 所属概念。
- 显示名称。
- RDF/XSD 数据类型。
- 是否必填、是否多值等语义约束。

### 5.3 Relation

表示概念间关系，至少包含：

- URI。
- 源概念。
- 目标概念。
- 显示名称。
- 可选方向、基数和描述。

关系表达业务语义，不等同于 SQL JOIN。JOIN 字段属于物理映射层。

### 5.4 BusinessRule

表示可引用、可组合的业务规则，至少包含：

- URI。
- 适用概念。
- 显示名称与说明。
- 结构化条件表达。
- 引用的属性和关系。
- 版本与状态。

首期只读取和验证规则结构，不把自然语言条件直接拼接为 SQL。

### 5.5 DataSource

表示一个逻辑数据源，至少包含：

- 稳定数据源标识。
- 平台类型，例如 Hive、PostgreSQL、MySQL、Spark。
- 可选方言和能力标签。

本体包不存储连接密码、令牌或网络地址等敏感配置。

### 5.6 PhysicalMapping

表示语义元素到物理结构的映射，至少包含：

- 数据源标识。
- 概念或属性 URI。
- 物理命名空间、对象名和字段名。
- JOIN 映射或关系路径。
- 分区、类型转换等可选提示。
- 生效状态和优先级。

映射只描述物理落点，不包含某个编译器生成的完整 SQL。

## 6. SHACL 约束

首期至少验证：

- 每个概念具有唯一 URI、短名和显示名称。
- 每个属性具有所属概念和合法数据类型。
- 每个关系具有存在的源概念和目标概念。
- 每条业务规则引用的属性和关系存在。
- 每条物理映射具有数据源和合法目标。
- 同一数据源、同一语义元素不能存在多个同优先级激活映射。
- 数据源标识不得携带密码等连接凭据。
- QueryPlan 使用的元素必须属于当前本体包版本。

## 7. Python SDK

SDK 使用同步、只读接口，避免把当前 FastAPI 和 Agent 强制改为异步。首期公开：

```python
ontology.load(package_ref)
ontology.validate(package_ref)
ontology.get_package_info()
ontology.get_concept(concept_id)
ontology.list_concepts()
ontology.search_concepts(text)
ontology.resolve_property(concept_id, property_id)
ontology.list_relations(concept_id)
ontology.list_rules(concept_id)
ontology.resolve_mappings(element_id, data_source_id)
ontology.validate_query_plan(query_plan)
```

返回值全部为不可变或按值复制的 Pydantic DTO。调用方不得获得可修改的共享 RDF Graph。

## 8. REST API

REST API 使用版本化前缀 `/ontology/v1`，首期包含：

```text
GET  /ontology/v1/packages/current
POST /ontology/v1/packages/validate
GET  /ontology/v1/concepts
GET  /ontology/v1/concepts/{concept_id}
POST /ontology/v1/search
GET  /ontology/v1/concepts/{concept_id}/relations
GET  /ontology/v1/concepts/{concept_id}/rules
GET  /ontology/v1/mappings
POST /ontology/v1/query-plans/validate
```

REST 路由只完成认证、请求转换和响应映射，业务逻辑由 Python SDK 服务实现。现有 `/ontology` 管理接口首期保留，避免 API 行为变化。

## 9. QueryPlan 契约

首期定义但不生成 QueryPlan。最小结构包含：

- 本体包版本。
- 目标概念。
- 投影属性。
- 过滤条件。
- 关系路径。
- 聚合和分组。
- 时间范围。
- 目标数据源。

条件表达必须使用结构化操作符，不接受可直接执行的任意 SQL 片段。未来 LLM、规则引擎和人工调用方都输出同一 QueryPlan；不同编译器消费相同计划。

## 10. 数据导入与兼容

### 10.1 MySQL 导入

提供显式运行的导入器，将当前 MySQL 元数据转换为候选本体包：

- 表转换为物理对象及候选领域概念。
- 字段转换为属性候选及物理映射。
- `ontology_relations` 转换为关系候选和 JOIN 映射。
- `ontology_logical_defs` 转换为业务规则候选。
- 字段和表描述转换为注释。

导入器必须：

- 幂等。
- 对相同输入生成稳定 URI。
- 确定性排序和序列化。
- 先写入指定输出目录，再校验整个候选包。
- 不在应用启动时自动覆盖 Git 中的本体包。
- 不把数据库凭据写入输出。

导入生成的是候选结果，需要经人工审查和 Git 提交后成为事实源。

### 10.2 现有 Agent 兼容

首期不修改 `DbOntologyClient` 的运行行为。后续通过独立兼容适配器将 `OntologyService` 的 DTO 转换为现有 `ttl_def` 结构，再逐步切换 Agent。兼容适配器不是首期正式 API，不允许反向污染本体元模型。

## 11. 加载、并发与失败处理

- 应用启动时加载并验证配置指定的本体包。
- 只有验证通过的图才能发布为当前快照。
- 重载失败时保留最后一个有效快照。
- 请求只读取共享快照，不在请求期间修改 Graph。
- 快照记录包版本、SHA-256 摘要、加载时间和来源。
- 首期不支持通过 REST 直接修改本体文件。

统一错误码包括：

```text
package_not_found
ontology_parse_error
ontology_validation_error
concept_not_found
property_not_found
mapping_not_found
ambiguous_mapping
invalid_query_plan
unsupported_data_source
```

错误响应包含 `code`、`message`、`details` 和可选的 `violations`，不包含堆栈、数据库凭据或敏感样例值。

## 12. 测试设计

### 12.1 单元测试

- 包加载、文件合并和内容摘要。
- URI 和稳定标识处理。
- 概念、属性、关系、规则解析。
- 映射选择、缺失与冲突处理。
- QueryPlan 验证。
- 错误对象转换。

### 12.2 SHACL 测试

- 缺少显示名称。
- 属性数据类型非法。
- 关系引用不存在概念。
- 规则引用不存在属性。
- 映射缺少数据源。
- 激活映射冲突。

### 12.3 契约测试

- Python SDK 与 REST API 对相同输入返回语义一致的数据。
- 错误码与 HTTP 状态稳定。
- 本体包版本和摘要可追踪。
- 用户后续提供的测试集以参数化外部数据方式接入。

### 12.4 导入测试

- 使用临时数据库替身或匿名输入夹具。
- 验证确定性 URI、排序和序列化。
- 验证重复导入结果一致。
- 验证导入失败不会覆盖有效包。

生产代码、默认本体包和提交到仓库的测试数据不得包含真实电信表名、字段名、用户数据或业务口径。自动化测试使用虚构的中性概念；临时文件在测试结束后清理。

## 13. 首期验收标准

1. 本体包能够被 RDFLib 正确加载和确定性序列化。
2. 本体包能够通过 pySHACL 校验，非法包返回结构化违规信息。
3. Python SDK 可以查询概念、属性、关系、规则和物理映射。
4. REST API 提供相同能力和稳定错误响应。
5. MySQL 导入器可重复生成一致的候选本体内容。
6. 同一语义属性可以配置多个数据源映射，而核心代码不依赖具体平台。
7. QueryPlan 可以独立验证，但不会在首期生成或编译。
8. 新增功能具有自动化测试，现有测试不回归。
9. 现有 Agent、前端、SQL 生成和执行链路行为保持不变。
10. 本体包、日志和错误中不泄漏连接凭据或真实测试数据。

## 14. Git 与交付约定

- 设计、依赖、核心模型、校验器、API、导入器和测试分别形成小而可审查的逻辑提交。
- 每次提交前运行与改动范围匹配的测试和静态检查。
- 不自动提交用户已有的无关改动。
- 不自动推送远程仓库；如需推送，由用户另行授权。

## 15. 后续演进方向

首期完成后，按独立设计和实施计划逐步推进：

1. 自然语言到 QueryPlan 的受约束生成。
2. 本体驱动的概念链接和规则解析。
3. 编译器协议与 HiveSQL 编译器迁移。
4. PostgreSQL、MySQL、Spark SQL 等编译器插件。
5. 数据源能力发现、成本评估和查询计划优化。
6. 现有 Agent 从 `DbOntologyClient` 切换到新本体服务。

每一阶段都以 QueryPlan 和本体服务的稳定接口为边界，避免再次把业务语义绑定到某个数据库平台。
