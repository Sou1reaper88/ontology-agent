# DeepSeek Flash Token 能力档案修复设计

## 目标

当前运行模型名为 `deepseek-flash`，但本地能力档案只识别旧名称
`deepseek-v4-flash`，导致未显式配置 Token 参数时错误回退到
32,768 输入 / 4,096 输出。

依据 DeepSeek 官方文档，`deepseek-flash` 的上下文长度为 1,000,000
Token，最大输出为 384K（393,216）Token。

## 方案

- 将现有模型能力档案中的 `deepseek-v4-flash` 更新为 `deepseek-flash`。
- 不保留 `deepseek-v4-flash` 兼容项。
- 将项目部署配置与相关测试同步改为 `deepseek-flash`。
- 不修改当前本地运行时 API 模型名。
- 显式配置的 `maxInputTokens`、`maxOutputTokens` 仍优先于模型默认值。

不增加通用别名系统，不修改上下文压缩算法，也不处理评测中心。

## 验证

先增加回归测试并确认当前实现失败，再做最小实现，使以下行为通过：

1. `deepseek-flash` 未配置上限时解析为 1,000,000 / 393,216。
2. 旧名称 `deepseek-v4-flash` 按未知模型处理，不再享有专用档案。
3. 未知模型继续使用安全默认值。
4. 显式配置继续覆盖模型档案。

参考：https://api-docs.deepseek.com/quick_start/pricing/
