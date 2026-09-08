# Shared one-shot prompt implementation

已确认需求：把聊天页“上下文”改为“提示词”；所有用户共享且均可新建、编辑、删除；一次只选一条；仅影响下一轮的全部模型调用，发送后自动取消；模板后续修改不改变已开始轮次；无需内置样例。

实现：SavedPrompt独立表与认证后的共享CRUD；MessageSend仅传prompt_id，服务器在接受消息时读取并复制内容给后台任务。ContextAssembler只把本轮副本作为persistent_prompt组装，旧Conversation.context停止注入但保留存储兼容。前端Modal提供列表、单选和CRUD，发送202后清空选择，删除二次确认。

验证：先写失败测试确认接口缺失、选择未传递和旧上下文常驻；实现后32项提示词/对话/上下文测试通过，前端执行TypeScript检查和生产构建，Alembic单head且开发库迁移成功。不调用真实模型、不执行SQL。
