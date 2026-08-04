# 简历总结

## 简历 Bullet

- 从零设计并实现企业录入审批 Agent，基于 FastAPI + LangGraph 将批量 Excel 审核拆分为 Evidence、Rule、Classification、Risk、Decision、Explanation 等多 Agent 节点，支持自动通过、自动驳回、证据不足和人工复核分流。
- 设计 EvidencePackage、CandidateRuleSet、ApprovalDecision、AgentAssessment 等领域模型，约束 LLM 只能基于外部证据和内部候选规则输出结构化 JSON，并通过 Risk/Decision Agent 兜底高风险和异常场景。
- 建立 mock 证据源、官网爬虫 provider 雏形、评测脚本、Agent trace、人工复核 API 和 Docker 化交付流程，在 10 条标准样例上实现 100% 准确率、60% 自动处理率、40% 人工复核率，并为 30 条 golden cases 扩展预留评测入口。

## 1 分钟介绍

这个项目解决的是企业内部录入分类需要人工审核的问题。系统读取员工上传的 Excel，采集企业外部证据，召回内部分类规则，再通过多 Agent 工作流判断录入是否合理。低风险记录自动通过或驳回，不确定记录进入人工复核。项目重点不是堆 prompt，而是把确定性代码、LLM 语义判断、风险分层、人工兜底和指标评测组合成一个可追踪的审批系统。

## 5 分钟技术讲解

系统分为 API 层、领域模型层、Agent 层、workflow 层、基础设施层和可观测层。FastAPI 负责上传、下载、批次查询和人工复核接口；LangGraph 负责编排多 Agent 节点；Pydantic 约束输入输出结构；SQLite 保存批次摘要、审批明细、复核任务和 AgentAssessment；openpyxl 负责 Excel 读写。

LLM 只在 Classification Agent 中做语义判断，最终审批动作由 Risk Agent 和 Decision Agent 根据规则生成。这样可以降低模型幻觉风险，也方便测试和解释。

## 面试问答

问：为什么不是 Excel 脚本？

答：脚本只能做字段处理和固定规则匹配，而这个系统会结合外部证据、内部规则、语义判断、风险分层、人工复核和 trace，形成可评测的人机协同审批流程。

问：LLM 错了怎么办？

答：LLM 输出必须经过结构化校验；低置信度、证据不足、分类不存在和高风险记录会进入人工复核；LLM 关闭时 mock provider 仍可跑完整流程。

问：怎么证明有效？

答：用评测集和指标证明，包括 accuracy、auto_handled_rate、review_rate、llm_failure_rate、average_latency_ms 和 AgentAssessment 数量。
