# 审批 Agent 架构说明

## 业务目标

系统用于审核员工在 Excel 中录入的企业分类是否合理。它读取批量记录，采集企业外部证据，召回内部分类规则，并通过多 Agent 工作流输出自动通过、自动驳回、证据不足或人工复核。

## 多 Agent 分工

- Evidence Agent：采集企业外部证据，输出 EvidencePackage 和证据质量分。
- Rule Agent：召回 Top-K 内部候选规则，判断员工录入路径是否存在。
- Classification Agent：判断外部证据是否支持员工录入分类。
- Risk Agent：根据证据质量、规则召回和语义判断做风险分层。
- Decision Agent：根据确定性决策规则生成最终 ApprovalDecision。
- Explanation Agent：生成审核员内部说明和录入员工反馈。

## LangGraph 流程

```text
START
  -> evidence_agent
  -> rule_agent
  -> classification_agent
  -> risk_agent
  -> decision_agent
  -> explanation_agent
  -> create_review_tasks
  -> build_metrics
  -> END
```

## 关键设计

- LLM 只负责语义判断，不直接控制最终流程。
- 最终动作由 Decision Agent 使用确定性规则生成。
- 每个 Agent 都输出 AgentAssessment，包含状态、置信度、发现信息、结构化输出和耗时。
- LLM 关闭时使用 mock provider，系统仍可完整运行。
- 证据不足、分类不存在、高风险记录会进入人工复核。
