# Day20 LLM Provider 抽象报告

## 今日完成

- 新增 ClassificationProvider 协议。
- 新增 LLMClassificationResult 结构化判断模型。
- 实现 MockClassificationProvider，复用当前确定性审批判断逻辑。
- 实现 OpenAI-compatible provider，支持真实 LLM JSON 判断输出。
- 将 workflow 的分类判断改为依赖 classification_provider。
- 支持通过 LLM_ENABLED 在 mock 和真实 LLM provider 之间切换。
- 增加 LLM 输出 JSON 校验和异常兜底测试。

## 指标结果

- 支持 provider 数量：2
  - mock provider
  - OpenAI-compatible provider
- 结构化输出字段：6 个
- LLM 非法输出拦截：支持
- 默认测试模式：mock
- 10 条标准样例准确率：保持 100%

## 简历表达

    设计并实现审批 Agent 的 LLM Provider 抽象层，支持 mock 规则判断与 OpenAI-compatible 真实模型调用切换；通过结构化 JSON 输出模型和 Pydantic 校验约束 LLM 审批结果，避免模型自由文本输出影响审批稳定性，并保持 10 条标准样例评测准确率 100%。