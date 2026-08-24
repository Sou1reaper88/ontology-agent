# 本体驱动数据查询 Agent：职业素材记录

> 本文只汇总已验证事实。计划中的能力必须保留“计划”或“设计中”标记，不能直接用于简历成果描述。

## 项目定位

面向企业结构化数据查询场景的本体驱动 Agent。目标是把自然语言需求、业务概念、数据源映射和查询编译解耦，为后续支持多数据库和多 SQL 方言建立统一语义层。

## 当前阶段

- 已完成现有项目架构和本体能力审查。
- 已识别“本体对象等同物理表”“职责集中于单一客户端”“规则与字段硬编码”等架构问题。
- 已完成纯 Python 正式本体内核设计。
- 已实现 RDFLib + pySHACL 本体包内核、不可变 DTO、安全清单加载、内容摘要和失败重载保护。
- 已交付本体包解析、不可变语义目录、快照绑定的 Python `OntologyResolver`，以及外部空白包 `init` / `validate` / `inspect` CLI。
- 已实现平台无关 `QueryPlan`、确定性 Planner、可替换 `SqlCompiler` 协议和 SQL 影子服务，并接入现有 Agent、对话 API 与前端对比面板。
- 当前采用影子模式保留 legacy 可执行 SQL；本体 SQL 仅预览和复制，真实业务准确率等待用户测试集评估。

## 可用于阶段汇报的表述

主导本体驱动查询 Agent 的语义层重构设计，将业务概念、物理数据映射和查询编译拆分为独立边界；选型 Python RDFLib 与 pySHACL 构建 RDF/OWL 本体及约束验证体系，并设计统一 QueryPlan 契约，为后续多数据库、多 SQL 方言扩展奠定基础。

实现纯 Python 本体包与语义解析边界，支持版本化 RDF/OWL 加载、SHACL 约束校验、内容摘要、失败重载保护、冻结 DTO 和确定性 Resolver；通过 `init` / `validate` / `inspect` 支持外部私有包的最小编辑闭环。Task 7 最终回归为 `228 passed, 2 skipped`；该数字是该阶段执行结果，不代表后续规划能力已完成。

将正式本体内核接入存量 SQL Agent：以 `OntologyPlanner -> QueryPlan -> SqlCompiler` 解耦自然语言语义选择与数据库方言编译，通过影子模式在同一聊天消息中展示 legacy SQL、本体 SQL、差异和可追溯证据，同时保持原执行链路不变。该阶段全量回归为 `424 passed, 2 skipped`，前端 production build 通过；业务准确率将在用户测试集上单独量化。

## 面试故事草稿：从元数据增强到正式本体

### Situation

原系统依赖数据库表注释和关系配置辅助 LLM 生成 HiveSQL，能够完成原型验证，但业务概念与物理表强绑定，难以扩展到其他数据库和编译器。

### Task

在继续使用 Python、保持现有业务链路稳定的前提下，设计一套正式、可校验、可版本化且平台无关的本体内核。

### Action

- 阅读 Agent 编排、本体客户端、权限、执行和测试代码，梳理真实边界。
- 区分业务概念、关系、规则、数据源和物理映射。
- 对比 Python RDF 工具、Java 本体服务、MySQL-first 和 GraphRAG 路线。
- 选择 RDFLib + pySHACL，交付不可变快照、结构化错误契约和 Python `OntologyResolver`；将 REST API、MappingRegistry 与 QueryPlan 保留为后续边界。
- 使用旁路接入策略控制重构风险，保留后续兼容适配空间。
- 将旁路策略落地为可见的 SQL 影子模式：本体链路独立生成 SQL，结果写入现有 trace JSON，并在前端展示概念、属性、规则、数据源和物理映射证据。
- 设计平台无关查询计划与 `SqlCompiler` 协议，使新增数据库方言不需要修改自然语言 Planner 或 Agent API。
- 通过 TDD 实现安全清单加载、SHACL 报告 DTO 化、内容寻址摘要、原子快照发布、标记型语义解析与确定性 Resolver。
- 针对嵌套字典可变性和路径穿越边界进行独立代码审查，增加修复前失败、修复后通过的回归测试。
- 在审查中继续识别 RDFLib lexical form 规范化、URN 形式凭据谓词绕过、外部包初始化 TOCTOU 与 Windows junction 风险；用独立 lexical sink、URI local-name 归一化、随机 staging、原子 rename 和 fail-closed 清理策略补齐回归测试。

### Result

已完成从正式本体内核到 SQL 产品链路的首个闭环：外部本体包、确定性 Resolver、平台无关 QueryPlan、可替换编译器、Agent 影子接入和前端双 SQL 对比均已交付；全量回归为 `424 passed, 2 skipped`。本体 SQL 暂不自动执行，当前成果证明架构闭环和可解释性，不把本机演示结果表述为真实业务准确率。

## 转型能力映射

- 风控数据分析中的业务口径梳理 → RDF/OWL 概念、关系和版本化语义事实。
- 数据质量规则与异常排查 → SHACL 可执行约束、结构化违规报告和稳定错误契约。
- 指标血缘与结果复核 → 内容摘要、Git 提交边界、RED/GREEN 证据和失败回滚。
- 从分析脚本走向 Agent 工程 → 分离 LLM 意图理解、确定性语义内核、查询编译和执行器职责。
- 风控场景的对抗性边界意识 → 对 URI 凭据绕过、字面量保真、并发初始化与失败回滚建立可复现的安全回归证据。

## 后续需要持续收集的证据

- 自动化测试数量、通过率和回归情况。
- SHACL 捕获的无效本体案例。
- 新旧本体接口的代码耦合度变化。
- 新增数据源或编译器所需改动范围。
- 性能基线、加载耗时和 API 响应时间。
- 关键 Git 提交与 ADR 链接。
