# 正式取数默认物化结果表设计

## 目标

正式取数需求默认交付可落表的 Hive SQL，而不是裸 `SELECT`。普通问答仍不生成 SQL；只有用户明确要求仅查询、预览或不建表时，才允许交付只读查询。

## 决策

采用“模型判断意图，Python 校验交付形态”。不增加关键词解析器，也不由 Python 判断业务需求。对话模型继续负责理解自然语言、调用本体工具和编写 SQL，并在最终结构化回答中声明 `delivery_mode`：

- `table`：默认模式，正式取数使用；
- `query`：仅当用户明确要求只查询、预览或不建表时使用。

`delivery_mode` 缺失时按 `table` 处理，避免旧模型响应或偶发漏字段退回裸查询。

## SQL 交付合同

`table` 模式至少包含一个完整物化步骤：

```sql
DROP TABLE IF EXISTS temp_oa_<本轮ID>_result_table;

CREATE TABLE temp_oa_<本轮ID>_result_table AS
SELECT ...;
```

复杂需求可以创建中间表。每个目标必须使用本轮 `temp_oa_<本轮ID>_` 临时命名空间，并严格采用 `DROP TABLE IF EXISTS` 与 `CREATE TABLE AS SELECT` 配对；最后一个物化目标必须是 `_result_table`。不生成末尾清理语句，不覆盖已发布业务源表，不执行脚本。

`query` 模式只允许只读查询，不允许物化步骤。若模型声明的模式与 SQL 形态不一致，保留模型原 SQL，但降级为不可执行草稿并展示具体原因，不由 Python 重写 SQL。

## 数据流

1. 当前对话模型根据本轮用户原文和历史上下文选择 `delivery_mode`。
2. 模型按现有 Function Calling 流程读取本体元数据并编写 SQL。
3. `validate_sql` 继续执行现有 Hive、字段、分区和安全校验。
4. 最终交付校验在现有校验结果上检查 `delivery_mode` 与程序形态，不新增模型调用。
5. 前端沿用现有 `authored_program`、`authored_query` 和 `authored_draft` 展示，无需数据库迁移或 UI 改造。

## 改动范围

- 更新 `agent/conversation_agent.py` 的系统提示词和最终回答合同。
- 在最终交付处校验 `delivery_mode` 与 `CompiledProgram` 是否一致。
- 更新合成模型响应辅助函数及会话能力测试。
- 不修改本体、评测中心、前端、SQL 执行器或旧独立作者链路。

## 验证

测试先证明当前正式取数仍接受裸 `SELECT`，再实现默认物化约束。覆盖以下场景：

1. 默认或显式 `table` 配合裸 `SELECT` 时降级为草稿；
2. `table` 配合合法 `DROP/CREATE` 程序时成功；
3. 显式 `query` 配合只读查询时成功；
4. `query` 配合建表程序时降级为草稿；
5. 普通问答无 SQL 时不受交付模式影响；
6. 现有 CTE、占位符、工具预算和外部表安全规则保持通过。

实现后重启共享后端，以一条已确认业务口径的正式取数需求复测，确认生成结果表脚本但不执行。

## 边界

物化合同只能保证脚本交付形式、安全边界和结果表存在，不能证明业务口径正确。结果表名称仍使用本轮程序 ID，用户未来若需要指定固定目标表名，应另行设计授权与覆盖策略，本次不预留接口。
