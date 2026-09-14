# 智能体通用语义修复执行计划

> 按用户已批准的 C-2516 排查结论依序实施，不重复确认，不新增框架。

**目标：** 自然对话能够精确传递修改，生成链路能够承载布尔条件，并提供可解释的失败证据。

**架构：** 保留当前对话工具调用与统一关系计划；递归过滤树沿推断、元数据绑定、统一计划、编译器传递。严格保留左连接及排除连接的匹配边界，不接收模型原始 SQL。未提交的构建缓存和本地诊断文件不纳入本轮提交。

## 顺序

- [x] 1. 在 `inference_models.py`、`inference_validation.py`、`inference_to_relational.py`、`relational_plan.py`、`relational_compiler.py` 支持 `all_of/any_of/not` 与 `children`；叶节点保留旧格式。每个叶节点必须绑定真实元数据，跨来源条件仅在明确 WHERE 范围求值；不能安全放入 ON 的条件拒绝而不拆散。添加合成数据定向回归，先观察缺失功能失败。
- [x] 2. `llm_client.py` 保留不含输入值的校验位置和错误类型，`metadata_inference.py` 传递安全诊断。对话异常区分 HTTP 状态、超时和响应契约；不公开密钥、内部推理或完整模型响应，不自动重试。
- [x] 3. `metadata_candidates.py` 在暴露表族时召回其全部成员，但不强制模型选择该表族；指定地市可继续选单表。候选缺口诊断列出缺失引用，不误报需用户重新发布。
- [x] 4. `conversation_agent.py` 将历史上下文与本轮输入分开，通过工具描述和提示词明确本轮意图优先、局部修改不扩大范围；继续由 LLM 自然判断，不写关键词路由。提示失败不等于授权重新生成。
- [x] 5. `inference_validation.py` 从整合需求解析明确时间，再用模型时间表达补充，防止把明确账期标成默认或遗漏。保留有限范围与冲突检查。
- [x] 6. 执行涉及模块的定向回归，记录模拟与真实模型验证的区别。更新项目日志，commit/push，重启当前服务以供前台验收。

**验证命令：** `.venv/Scripts/python.exe -m pytest tests/ontology_core/test_inference_to_relational.py tests/ontology_core/test_relational_plan.py tests/ontology_core/test_relational_compiler.py tests/ontology_core/test_metadata_candidates.py tests/test_metadata_inference.py tests/test_conversation_agent.py -q`。只执行本轮相关模块，不调用付费模型，不执行业务 SQL。
