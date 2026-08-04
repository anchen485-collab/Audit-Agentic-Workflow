# Plan: Classification Agent 可靠性优化

**Generated**: 2026-07-30  
**Estimated Complexity**: Medium  
**Scope**: 针对 Classification Agent 执行失败、证据不足误导展示、LLM 输出不稳定、配置错误延迟暴露等问题制定实现计划。

## Overview

当前审批 Agent 中，Classification Agent 会把外部证据、员工录入分类、候选规则交给 LLM 做语义判断。实际运行中出现了几类问题：

- 官网证据质量为 0 时仍调用 LLM，LLM 会根据企业名称或候选关键词猜测分类，导致原因文案和最终动作不一致。
- LLM 返回 `matched_level1/matched_level2/matched_level3` 时容易返回不完整路径，或返回候选规则之外的分类，触发 `LLMOutputError`。
- Agent 兜底后 Excel 只展示“Classification Agent 执行失败，默认转入人工复核”，没有展示真实错误原因。
- LLM 配置错误，例如 401 Unauthorized，会在批量处理每条数据时才暴露，浪费时间且污染结果。
- 证据不足、LLM 异常、人工复核三类情况在结果文件中混在一起，不利于审核人员判断下一步动作。

本计划按“先减少无效 LLM 调用，再稳定 LLM 输出协议，再改善可观测性和配置校验”的顺序推进。每个 Sprint 都能单独验证，并且不改变现有上传、批量处理、结果下载主流程。

## Prerequisites

- 项目路径：`D:\audit-agent`
- Python 虚拟环境：`D:\audit-agent\.venv`
- 主要验证命令：
  - `D:\audit-agent\.venv\Scripts\python.exe -m pytest`
  - `D:\audit-agent\.venv\Scripts\python.exe -m ruff check .`
  - `D:\audit-agent\.venv\Scripts\python.exe scripts\run_eval.py --min-accuracy 0.8`
- 主要涉及文件：
  - `D:\audit-agent\app\agents\classification_agent.py`
  - `D:\audit-agent\app\agents\llm_classification_provider.py`
  - `D:\audit-agent\app\agents\base.py`
  - `D:\audit-agent\app\agents\decision_agent.py`
  - `D:\audit-agent\app\domain\decisions.py`
  - `D:\audit-agent\app\domain\models.py`
  - `D:\audit-agent\app\infrastructure\excel_writer.py`
  - `D:\audit-agent\app\api\dependencies.py`
  - `D:\audit-agent\app\infrastructure\settings.py`
  - `D:\audit-agent\tests\unit\`
  - `D:\audit-agent\tests\e2e\`

## Sprint 1: 证据不足前置拦截

**Goal**: 证据质量为 0 或证据不充分时，不再调用 LLM，直接生成可解释的 `insufficient_evidence` 语义结果。

**Demo/Validation**:

- 构造一条官网访问失败、`quality_score=0`、`snippets=[]` 的用例。
- 运行 Classification Agent 后应返回 `result=insufficient_evidence`。
- 不应调用真实 LLM provider。
- Excel 中原因应明确说明“官网访问失败/证据为空”，而不是“Classification Agent 执行失败”或“语义上符合候选规则”。

### Task 1.1: 增加证据不足短路逻辑

- **Location**: `D:\audit-agent\app\agents\classification_agent.py`
- **Description**: 在 `_classify()` 调用 `self.provider.classify()` 前，先调用 `has_sufficient_evidence(evidence)`。如果不充分，直接返回 `SemanticClassificationResult(result="insufficient_evidence")`。
- **Dependencies**: 无
- **Acceptance Criteria**:
  - 证据不足时不会访问 LLM。
  - 返回结果包含 `case_id`、`confidence`、`reason`、`suggestion`。
  - `reason` 优先包含 `evidence.errors` 中的官网失败原因。
- **Validation**:
  - 新增单元测试：`test_classification_agent_skips_llm_when_evidence_insufficient`
  - 使用 fake provider 记录调用次数，断言调用次数为 0。

### Task 1.2: 统一证据不足原因生成

- **Location**: `D:\audit-agent\app\agents\classification_agent.py`
- **Description**: 新增私有函数 `_build_insufficient_evidence_reason(evidence)`，按优先级生成中文原因。
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - 有 `evidence.errors` 时展示第一条或合并后的错误，例如“官网访问失败：502 Bad Gateway”。
  - 无错误但 `business_scope` 为空时展示“未采集到有效业务描述”。
  - 无错误但 `snippets` 为空时展示“未抽取到有效业务片段”。
- **Validation**:
  - 新增 3 个单元测试覆盖不同证据不足原因。

### Task 1.3: 修正最终动作和原因不一致问题

- **Location**: `D:\audit-agent\app\agents\decision_agent.py`
- **Description**: 当最终动作被硬规则判为 `NEEDS_MORE_EVIDENCE` 时，`reason` 应优先使用证据不足原因，而不是沿用 LLM 的支持性解释。
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - `action=needs_more_evidence` 时，审批原因不出现“符合候选规则”“支持员工录入分类”这类通过性表达。
  - 如果证据错误存在，审批原因包含证据错误摘要。
- **Validation**:
  - 新增单元测试：LLM 返回 supports，但证据质量为 0 时，最终原因仍为证据不足。

## Sprint 2: LLM 输出协议改为候选规则 ID

**Goal**: 避免 LLM 编造分类路径，改为只允许返回候选规则编号或空值。

**Demo/Validation**:

- Prompt 中候选规则显示为 `candidate_rule_id`。
- LLM 输出 `matched_candidate_rule_id`。
- 系统用 ID 回查候选规则，而不是信任 LLM 返回的中文路径。

### Task 2.1: 给候选规则生成稳定候选 ID

- **Location**: `D:\audit-agent\app\agents\llm_classification_provider.py`
- **Description**: 在构造 prompt 时，为每条 `candidate_rules.candidates` 生成本次请求内稳定 ID，例如 `rule_1`、`rule_2`、`rule_3`。
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Prompt 中每条候选规则包含 ID、完整分类路径、关键词。
  - ID 只在本次 LLM 请求内使用，不要求写入规则库。
- **Validation**:
  - 单元测试断言 `_build_classification_prompt()` 包含 `rule_1` 和对应分类路径。

### Task 2.2: 扩展语义结果模型

- **Location**: `D:\audit-agent\app\agents\llm_classification_provider.py`
- **Description**: 在 `SemanticClassificationResult` 中新增 `matched_candidate_rule_id: str = ""`。保留旧的 `matched_level1/2/3` 字段一段时间用于兼容，但新逻辑优先使用 ID。
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - 新字段可被 Pydantic 正常解析。
  - 旧测试仍可通过，新增测试覆盖 ID 模式。
- **Validation**:
  - 新增模型解析测试。

### Task 2.3: 调整候选规则校验逻辑

- **Location**: `D:\audit-agent\app\agents\llm_classification_provider.py`
- **Description**: `_validate_candidate_rule()` 改为优先校验 `matched_candidate_rule_id` 是否存在于本次候选 ID 集合中。不存在则抛 `LLMOutputError`，为空则表示无法匹配，不抛异常。
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - LLM 返回 `rule_1` 时通过校验。
  - LLM 返回 `rule_999` 时失败。
  - LLM 返回空 ID 且 `result=uncertain/insufficient_evidence` 时不失败。
- **Validation**:
  - 修改 `D:\audit-agent\tests\unit\test_llm_classification_provider.py`。

### Task 2.4: 决策层基于候选 ID 查找规则

- **Location**:
  - `D:\audit-agent\app\domain\decisions.py`
  - `D:\audit-agent\app\agents\decision_agent.py`
- **Description**: 决策和建议生成时优先使用 `matched_candidate_rule_id` 找候选规则。旧路径仅作为兼容 fallback。
- **Dependencies**: Task 2.3
- **Acceptance Criteria**:
  - `conflicts_with_entered_category` 且 ID 命中候选规则时可以自动驳回。
  - ID 不存在或为空时进入人工复核，不再表现为 Agent 执行失败。
- **Validation**:
  - 新增决策层单元测试。

## Sprint 3: LLM 输出降级策略

**Goal**: 对不完整路径、旧字段、非法但可理解的输出做温和降级，减少“Agent 执行失败”的比例。

**Demo/Validation**:

- LLM 返回不完整分类路径时，不抛系统失败，转为 `uncertain`。
- LLM 返回旧字段 `action/needs_review` 时，能给出明确错误类型，必要时降级为人工复核。

### Task 3.1: 定义 LLM 输出错误分类

- **Location**: `D:\audit-agent\app\domain\errors.py`
- **Description**: 增加或细化错误类型，例如 `LLMInvalidJsonError`、`LLMInvalidCandidateError`、`LLMProviderAuthError`。
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - 不同错误能被日志和 Excel 区分。
  - 不影响现有 `LLMOutputError` 调用方。
- **Validation**:
  - 单元测试覆盖错误类型和 `action_for_error()` 映射。

### Task 3.2: 不完整候选路径降级为 uncertain

- **Location**: `D:\audit-agent\app\agents\llm_classification_provider.py`
- **Description**: 如果 LLM 只返回了部分 `matched_level`，且没有有效 `matched_candidate_rule_id`，不要直接抛错。将结果修正为 `uncertain`，并追加原因“LLM 未返回完整候选规则”。
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - `卫生和社会工作 / /` 不再导致 Agent failed。
  - 最终动作进入 `needs_human_review`。
  - Agent assessment 状态可以是 `success`，但 output 包含 `normalization_warning`。
- **Validation**:
  - 单元测试复现当前数据库中的失败样例。

### Task 3.3: 非法 JSON 错误保持失败但增强信息

- **Location**:
  - `D:\audit-agent\app\agents\llm_classification_provider.py`
  - `D:\audit-agent\app\agents\base.py`
- **Description**: 对无法解析 JSON 的输出保留 failed 状态，但记录错误类型、原始输出摘要、处理建议。
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Excel 和 assessment 中能看到“LLM 输出不是合法 JSON”。
  - raw_text 最多保存前 500 字，避免结果文件过大。
- **Validation**:
  - 单元测试模拟 LLM 返回非法 JSON。

## Sprint 4: Excel 和 API 增加真实错误展示

**Goal**: 让审核人员能区分“业务证据不足”和“Agent 系统异常”。

**Demo/Validation**:

- 下载结果 Excel 后，明细页出现“Agent状态”“Agent错误原因”或等价列。
- 对 Classification Agent 失败的记录，能看到真实异常，例如“LLM 返回了候选规则之外的分类”。

### Task 4.1: 在领域模型中保留 Agent 错误摘要

- **Location**: `D:\audit-agent\app\domain\models.py`
- **Description**: 评估是否在 `ApprovalDecision` 增加 `agent_status`、`agent_error` 字段；如果不想污染决策模型，则在 Excel writer 入参中增加 `assessments` 映射。
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - 能从 workflow 结果传递 classification assessment 的错误信息到导出层。
  - 不破坏现有 API schema。
- **Validation**:
  - 单元测试验证字段序列化。

### Task 4.2: 结果 Excel 增加错误列

- **Location**: `D:\audit-agent\app\infrastructure\excel_writer.py`
- **Description**: 在审批明细中增加列：
  - `Classification Agent 状态`
  - `Classification Agent 错误原因`
  - `证据不足类型`
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - 官网失败显示为“官网访问失败”。
  - LLM 候选规则错误显示为“LLM 返回候选规则之外的分类”。
  - 非法 JSON 显示为“LLM 输出无法解析”。
- **Validation**:
  - 修改 `D:\audit-agent\tests\unit\test_excel_writer.py`。

### Task 4.3: API 返回错误摘要

- **Location**:
  - `D:\audit-agent\app\api\schemas.py`
  - `D:\audit-agent\app\api\routes.py`
  - `D:\audit-agent\app\infrastructure\batch_repository.py`
- **Description**: 在批次详情或决策详情接口中返回 Agent 错误摘要，前端可直接展示。
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - 前端无需解析 Excel 即可看到失败原因。
  - 不暴露 API Key、完整 prompt、完整 LLM 原文等敏感内容。
- **Validation**:
  - 修改 API 单元测试和 e2e 测试。

## Sprint 5: LLM 配置启动前校验

**Goal**: LLM API Key、base_url、model 配错时，在服务启动或首次依赖创建时快速失败，不让批处理跑到一半才失败。

**Demo/Validation**:

- 设置错误 API Key，启动或调用健康检查时能得到明确提示。
- 设置 `LLM_ENABLED=false` 时不校验 LLM 连接。

### Task 5.1: 增加 LLM 配置静态校验

- **Location**:
  - `D:\audit-agent\app\infrastructure\settings.py`
  - `D:\audit-agent\app\api\dependencies.py`
- **Description**: 当 `LLM_ENABLED=true` 时，校验 `LLM_API_KEY`、`LLM_MODEL`、`LLM_BASE_URL` 非空且 URL 格式合理。
- **Dependencies**: 无，可与 Sprint 1 并行
- **Acceptance Criteria**:
  - 缺少 API Key 时给出中文错误。
  - 缺少 model 时给出中文错误。
  - `LLM_ENABLED=false` 时不要求这些字段。
- **Validation**:
  - 新增 settings 单元测试。

### Task 5.2: 增加 LLM 连接探测

- **Location**:
  - `D:\audit-agent\app\agents\llm_classification_provider.py`
  - `D:\audit-agent\app\api\dependencies.py`
- **Description**: 给 `OpenAICompatibleClassificationProvider` 增加轻量 `health_check()`。可以调用模型列表接口，或发起一个最小 chat completions 请求。
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - 401 显示“认证失败，请检查 LLM_API_KEY 是否属于当前 LLM_BASE_URL”。
  - 403 显示“权限不足或模型无权限”。
  - 429 显示“限流或额度不足”。
  - 网络错误显示“无法连接 LLM 服务”。
- **Validation**:
  - 使用 fake http_get/http_post 模拟不同 HTTP 状态。

### Task 5.3: 增加健康检查接口

- **Location**:
  - `D:\audit-agent\app\api\routes.py`
  - `D:\audit-agent\app\api\schemas.py`
- **Description**: 增加 `/health/llm` 或扩展现有健康检查，返回 LLM 配置状态。生产环境不要返回 API Key。
- **Dependencies**: Task 5.2
- **Acceptance Criteria**:
  - 配置正确时返回 `ok=true`。
  - 配置错误时返回错误类型和中文建议。
  - 不泄漏密钥。
- **Validation**:
  - API 单元测试覆盖成功和失败。

## Sprint 6: 端到端回归和指标收敛

**Goal**: 用真实批量样例验证优化效果，确保失败率下降、解释更清楚、结果动作一致。

**Demo/Validation**:

- 使用包含官网失败、LLM 候选规则错误、非法 JSON、配置错误的样例运行测试。
- 对比优化前后 Classification Agent failed 数量。

### Task 6.1: 构建回归样例

- **Location**:
  - `D:\audit-agent\tests\fixtures\`
  - `D:\audit-agent\tests\e2e\test_audit_batch_flow.py`
- **Description**: 增加固定样例覆盖：
  - 官网 502
  - 官网 403
  - 证据质量为 100 但不支持分类
  - LLM 返回候选规则外 ID
  - LLM 返回不完整旧路径
  - LLM 返回非法 JSON
- **Dependencies**: Sprint 1 到 Sprint 5
- **Acceptance Criteria**:
  - 每种失败都有明确错误类型。
  - 不应再用一个兜底文案覆盖所有问题。
- **Validation**:
  - 运行 e2e 测试。

### Task 6.2: 更新评估指标

- **Location**:
  - `D:\audit-agent\app\observability\metrics.py`
  - `D:\audit-agent\scripts\run_eval.py`
- **Description**: 增加或细化指标：
  - `classification_agent_failure_rate`
  - `llm_invalid_candidate_count`
  - `llm_invalid_json_count`
  - `evidence_unavailable_count`
  - `evidence_content_insufficient_count`
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - 运行 eval 后能看到不同失败类型数量。
  - 失败类型可以用于后续优化优先级判断。
- **Validation**:
  - 修改 metrics 单元测试。
  - 运行 `scripts\run_eval.py --min-accuracy 0.8`。

### Task 6.3: 最终回归验证

- **Location**: 全项目
- **Description**: 完成所有修改后运行完整验证。
- **Dependencies**: 所有前置任务
- **Acceptance Criteria**:
  - `pytest` 通过。
  - `ruff check .` 通过。
  - `run_eval.py --min-accuracy 0.8` 通过。
  - 截图中的同类问题能解释清楚：官网失败为证据不足，不再出现“明明支持却证据不足”的展示矛盾。
- **Validation**:
  - 执行完整验证命令。

## Testing Strategy

- **单元测试优先**：
  - Classification Agent 证据不足短路。
  - LLM provider 对候选 ID 的解析和校验。
  - 不完整路径降级。
  - 非法 JSON 错误摘要。
  - Settings 对 LLM 配置的静态校验。

- **集成测试补充**：
  - 使用 fake LLM provider 模拟不同返回。
  - 使用 fake website provider 模拟官网访问失败、空文本、有效文本。

- **端到端测试兜底**：
  - 上传 Excel 后下载结果 Excel。
  - 检查审批动作、审批原因、证据错误、Agent 错误列是否一致。

- **人工验收重点**：
  - 审核人员是否能一眼区分“官网访问失败”和“LLM 输出异常”。
  - 同样的员工录入分类，如果结果不同，Excel 是否解释了真正差异。

## Potential Risks & Gotchas

- **风险：过早短路可能减少 LLM 的纠错机会**  
  缓解：只在证据确实不足时短路，例如质量分低于 60、无业务描述、无证据片段。证据充足但分类不确定时仍交给 LLM。

- **风险：候选 ID 只在本次 prompt 内有效，不能跨请求复用**  
  缓解：ID 只用于 LLM 输出回查，不写入数据库作为长期业务 ID。如果未来规则库有稳定 ID，再迁移为规则库 ID。

- **风险：兼容旧字段会让模型协议复杂**  
  缓解：保留一个过渡期。新逻辑优先使用 `matched_candidate_rule_id`，旧 `matched_level1/2/3` 只作为 fallback，并在指标里统计旧字段使用次数。

- **风险：Excel 增加列会影响已有测试和用户表格习惯**  
  缓解：只在结果 Excel 末尾追加列，不改变已有列顺序。测试更新时保持旧列仍存在。

- **风险：启动时 LLM health check 可能拖慢本地开发**  
  缓解：仅在 `LLM_ENABLED=true` 且生产/联调环境执行强校验。本地可通过配置关闭连接探测。

- **风险：真实 LLM 输出仍可能不稳定**  
  缓解：使用更严格 prompt、候选 ID、结构化校验、降级策略和指标监控共同兜底。

## Rollback Plan

- Sprint 1 可通过恢复 Classification Agent 调用 provider 的旧路径回滚。
- Sprint 2 的候选 ID 协议应保留旧路径 fallback，出现问题时可临时切回 `matched_level1/2/3` 校验。
- Sprint 4 的 Excel 新增列只追加在末尾，回滚时删除新增列写入逻辑，不影响原有结果字段。
- Sprint 5 的 health check 可通过环境变量关闭，例如新增 `LLM_HEALTH_CHECK_ENABLED=false`。
- 每个 Sprint 单独提交，出现问题时按提交粒度回滚。

## Suggested Implementation Order

1. 先做 Sprint 1，立刻解决“证据质量 0 仍调用 LLM”和“原因与动作矛盾”的问题。
2. 再做 Sprint 4 的最小版本，先把真实错误展示出来，方便后续调试。
3. 做 Sprint 2 和 Sprint 3，降低 LLM 输出导致的 Agent failed。
4. 做 Sprint 5，把 LLM 配置错误前置暴露。
5. 最后做 Sprint 6，用指标和 e2e 固化质量。

