# Plan: Code Review Fixes

**Generated**: 2026-07-30
**Estimated Complexity**: High

## Overview

本方案用于修复本次代码 review 中发现的核心问题。当前项目的单元测试和 lint 已经通过，但业务验收没有通过：`scripts/run_eval.py` 在 30 条 golden cases 上的准确率只有 56.67%，低于首版验收标准 `accuracy >= 80%`。

修复思路分为三层：

1. 先修业务效果门禁，确保准确率、评测集和规则数据口径一致。
2. 再修 Agent 架构边界，确保 LLM 只做语义判断，最终审批动作由确定性代码控制。
3. 最后补齐上线安全和部署配置，避免路径泄露、mock 配置误上生产、人工复核状态不可追踪等问题。

## Prerequisites

- 使用项目虚拟环境运行命令：`D:\audit-agent\.venv\Scripts\python.exe`。
- 当前有效需求文档：
  - `D:\audit-agent\docs\business-workflow.md`
  - `D:\audit-agent\docs\acceptance-criteria.md`
  - `D:\audit-agent\docs\real-excel-audit-plan.md`
- 当前评测集：`D:\audit-agent\evals\golden_cases.json`。
- 当前规则文件：`D:\audit-agent\data\rules\category_rules.json`。
- 当前 mock 证据文件：`D:\audit-agent\data\evidence\mock_company_evidence.json`。

## Sprint 1: 修复业务验收门禁

**Goal**: 让项目能明确证明首版业务效果达标，避免“测试通过但 Agent 不好用”。

**Demo/Validation**:
- 执行 `python scripts/run_eval.py` 后，准确率必须大于等于 80%。
- 低于阈值时命令应失败，不能只打印指标。
- 输出中能看到错例列表，方便快速定位。

### Problem 1.1: Golden cases 准确率只有 56.67%

**出现原因**:

- `evals/golden_cases.json`、`data/rules/category_rules.json`、`data/evidence/mock_company_evidence.json` 三者口径没有严格绑定。
- 真实规则 JSON 替换 demo 规则后，部分 golden case 的期望分类路径可能已经不在规则库中，系统因此返回 `needs_human_review`。
- 部分 rejected 场景被关键词命中后直接 approved，说明 mock 分类逻辑对“证据支持哪个分类”判断过粗。
- 当前测试只验证代码能跑通，没有验证业务准确率达标。

**影响**:

- 项目无法满足 `accuracy >= 80%` 的首版验收标准。
- 简历或演示中写 100% 准确率会和实际命令输出冲突。
- 后续改规则或证据时，业务效果可能继续退化但没人发现。

**最优解决方案**:

1. 为评测集建立版本口径：
   - `golden_cases.json` 中每条 case 必须能说明期望动作、期望依据和关联规则路径。
   - 规则文件更新后，同步检查 golden cases 的分类路径是否还存在。
   - mock evidence 更新后，同步检查每条证据是否明确支持或不支持期望动作。

2. 增强 `scripts/run_eval.py`：
   - 增加 `--min-accuracy` 参数，默认值为 `0.8`。
   - 当 accuracy 低于阈值时退出码为 1。
   - 输出 mismatch 列表，字段包括 `case_id`、`expected_action`、`actual_action`、`reason`。

3. 新增集成测试：
   - 在 `tests/integration/test_run_eval.py` 中断言 `accuracy >= 0.8`。
   - 断言 `case_count >= 30`。
   - 断言四类审批动作都至少覆盖 1 条。

**Location**:

- `D:\audit-agent\scripts\run_eval.py`
- `D:\audit-agent\tests\integration\test_run_eval.py`
- `D:\audit-agent\evals\golden_cases.json`
- `D:\audit-agent\data\rules\category_rules.json`
- `D:\audit-agent\data\evidence\mock_company_evidence.json`

**Acceptance Criteria**:

- `python scripts/run_eval.py` 输出 `accuracy >= 0.8`。
- 人为把期望值改错后，`python scripts/run_eval.py` 会失败。
- 错例能直接定位到 case_id 和原因。

## Sprint 2: 重构 LLM 和 Decision Agent 的职责边界

**Goal**: 让系统符合“LLM 不直接决定审批动作”的业务原则。

**Demo/Validation**:
- LLM 输出不再包含最终审批动作 `approved/rejected/needs_*`。
- Decision Agent 独立根据规则、证据、风险、LLM 语义判断生成最终审批动作。
- LLM 异常、JSON 不合法、编造分类时，整批 batch 不失败，单条进入人工复核。

### Problem 2.1: LLM 当前直接输出审批动作

**出现原因**:

- `LLMClassificationResult` 当前包含 `action` 字段。
- prompt 要求 LLM 输出 `approved | rejected | needs_more_evidence | needs_human_review`。
- `DecisionAgent._final_action()` 大多数情况下直接返回 `classification_result.action`。
- 这让 LLM 实际拥有了最终审批权，和业务文档中“LLM 只做语义判断”的定位冲突。

**影响**:

- LLM 幻觉或误判会直接影响最终审批动作。
- 系统解释上会变弱：很难证明最终动作是确定性规则生成的。
- 面试或评审时容易被质疑“这只是让模型直接审批”。

**最优解决方案**:

1. 新增语义判断模型，例如：

```python
class SemanticClassificationResult(BaseModel):
    """LLM 只输出语义判断，不输出最终审批动作。"""

    supports_entered_category: bool
    matched_rule_level1: str = ""
    matched_rule_level2: str = ""
    matched_rule_level3: str = ""
    confidence: int
    evidence_summary: str
    conflict_reason: str = ""
    suggested_rule_level1: str = ""
    suggested_rule_level2: str = ""
    suggested_rule_level3: str = ""
```

2. 修改 prompt：
   - 删除 `action`、`risk_score`、`needs_review`。
   - 要求 LLM 只能在候选规则中选择匹配项。
   - 要求 LLM 输出“证据是否支持员工录入分类”。

3. 修改 `DecisionAgent`：
   - 证据不足：确定性代码返回 `needs_more_evidence`。
   - 分类路径不存在：确定性代码返回 `needs_human_review`。
   - LLM 支持录入分类且风险低：返回 `approved`。
   - LLM 不支持录入分类且风险低，并有明确建议：返回 `rejected`。
   - LLM 置信度低、候选规则冲突、高风险：返回 `needs_human_review`。

4. 增加候选分类合法性校验：
   - 如果 LLM 返回的建议分类不在 candidate rules 中，强制转人工复核。
   - 记录原因：`LLM 返回了候选规则之外的分类`。

**Location**:

- `D:\audit-agent\app\agents\llm_classification_provider.py`
- `D:\audit-agent\app\agents\classification_agent.py`
- `D:\audit-agent\app\agents\decision_agent.py`
- `D:\audit-agent\app\agents\risk_agent.py`
- `D:\audit-agent\tests\unit\test_llm_classification_provider.py`
- `D:\audit-agent\tests\unit\test_risk_decision_explanation_agents.py`

**Acceptance Criteria**:

- LLM 输出模型中不再存在 `action` 字段。
- Decision Agent 单元测试覆盖四类最终动作。
- LLM 返回候选规则之外的分类时，最终动作是 `needs_human_review`。
- LLM 调用失败时，单条记录进入人工复核，batch 不失败。

### Problem 2.2: 高风险自动驳回没有兜底

**出现原因**:

- 当前 `DecisionAgent` 只拦截 `HIGH + approved`。
- 如果分类结果是 `rejected`，即使风险等级是 high，也会自动驳回。
- 自动驳回对员工影响更直接，需要比自动通过更谨慎。

**影响**:

- 证据冲突、LLM 低置信度、规则异常时，系统可能错误自动驳回。
- 人工复核安全阀没有覆盖所有高风险场景。

**最优解决方案**:

- 修改决策规则：只要 `risk_level == HIGH`，最终动作都应是 `needs_human_review`，除非是明确的 `needs_more_evidence`。
- 对 `MEDIUM + rejected` 增加策略开关：
  - 保守模式：转人工复核。
  - 自动化模式：允许自动驳回，但必须有建议分类和高置信度。

**Location**:

- `D:\audit-agent\app\agents\decision_agent.py`
- `D:\audit-agent\tests\unit\test_risk_decision_explanation_agents.py`

**Acceptance Criteria**:

- `HIGH + approved` 转人工复核。
- `HIGH + rejected` 转人工复核。
- `needs_more_evidence` 保持证据不足动作。
- 单元测试覆盖以上组合。

## Sprint 3: 修复评测和脚本可运行性

**Goal**: 让 README 中写的命令在干净环境和本机环境都可稳定运行。

**Demo/Validation**:
- `python -m pytest`、`python -m ruff check .`、`python scripts/run_eval.py`、`python scripts/demo_trace.py` 均按文档可运行。
- 使用错误 Python 环境时，文档能提示先激活 `.venv`。

### Problem 3.1: 系统 Python 直接运行会缺依赖

**出现原因**:

- 本机 `python` 指向 Python 3.14，项目虚拟环境是 Python 3.11。
- 系统 Python 没有安装 `pydantic-settings` 和 `ruff`。
- README 没强调“所有命令必须在 `.venv` 激活后运行”。

**影响**:

- 新同事或面试演示时直接复制命令会失败。
- 容易误以为项目测试不过。

**最优解决方案**:

- README 和部署文档统一写清楚：
  - Windows 本地先执行 `.\.venv\Scripts\Activate.ps1`。
  - 或直接使用 `D:\audit-agent\.venv\Scripts\python.exe -m pytest`。
- 增加 `scripts/check_env.py`：
  - 检查 Python 版本是否为 3.11。
  - 检查关键依赖是否存在。
  - 输出清晰修复建议。

**Location**:

- `D:\audit-agent\README.MD`
- `D:\audit-agent\docs\deployment.md`
- `D:\audit-agent\scripts\check_env.py`

**Acceptance Criteria**:

- README 命令在 `.venv` 激活后全部可运行。
- 未激活虚拟环境时，`check_env.py` 能提示原因。

## Sprint 4: API 安全和数据治理

**Goal**: 减少上线后的信息泄露和数据状态不一致。

**Demo/Validation**:
- API 不再返回服务端文件路径。
- 人工复核提交会校验最终动作是否合法。
- 提交人工复核后，能追踪人工结论和原 Agent 结论的差异。

### Problem 4.1: API 返回内部文件路径

**出现原因**:

- `AuditUploadResponse` 和 `AuditBatchSummaryResponse` 直接返回 `result_file`、`input_file`。
- 这些字段对前端没有必要，只适合服务端内部追踪。

**影响**:

- 暴露服务端目录结构。
- 如果将来部署到 Linux 或容器，会把内部路径暴露给调用方。

**最优解决方案**:

- 上传响应只返回：
  - `batch_id`
  - `case_count`
  - `decision_count`
  - `review_task_count`
  - `metrics`
  - `download_url`
- 批次列表只返回业务摘要，不返回 `input_file` 和 `result_file`。
- 如果内部排障需要路径，只在日志或管理接口中返回。

**Location**:

- `D:\audit-agent\app\api\schemas.py`
- `D:\audit-agent\app\api\routes.py`
- `D:\audit-agent\tests\unit\test_audit_api.py`

**Acceptance Criteria**:

- 普通 API 响应不包含本地文件系统路径。
- 下载仍然通过 `/api/audit/batches/{batch_id}/result` 工作。

### Problem 4.2: 人工复核最终动作缺少校验

**出现原因**:

- `ReviewDecisionRequest.final_action` 是普通字符串。
- `complete_review_task()` 直接保存传入值。
- 当前没有限制 `approved/rejected/unable_to_decide` 等合法值。

**影响**:

- 前端或调用方传错值也会落库。
- 后续统计人工复核质量时会出现脏数据。

**最优解决方案**:

- 将 `final_action` 改为枚举。
- 支持合法值：
  - `approved`
  - `rejected`
  - `needs_more_evidence`
  - `unable_to_decide`
- 保存人工复核结果时记录：
  - `reviewer`
  - `final_action`
  - `reviewed_at`
  - `original_agent_action`

**Location**:

- `D:\audit-agent\app\api\schemas.py`
- `D:\audit-agent\app\infrastructure\batch_repository.py`
- `D:\audit-agent\app\services\batch_service.py`
- `D:\audit-agent\tests\unit\test_batch_repository.py`

**Acceptance Criteria**:

- 非法 `final_action` 返回 422。
- 人工复核完成后，任务状态为 `completed`。
- 数据库 payload 中包含 `reviewed_at`。

## Sprint 5: 部署配置和生产防误用

**Goal**: 避免用 demo/mock 配置启动生产服务。

**Demo/Validation**:
- Docker compose 默认读取 `.env`。
- 缺少 `.env` 或生产环境仍使用 mock 时，有明确提示。

### Problem 5.1: docker-compose 默认加载 `.env.example`

**出现原因**:

- `docker-compose.yml` 中 `env_file` 指向 `.env.example`。
- `.env.example` 是模板，不应该作为真实运行配置。
- 当前模板默认 `LLM_ENABLED=false`、`COMPANY_PROVIDER=mock`。

**影响**:

- 容器部署时可能误用 mock provider。
- 真实 LLM 和 website provider 不会生效。
- 演示真实审批时容易出现“看似部署成功，实际跑 demo 数据”的问题。

**最优解决方案**:

- `docker-compose.yml` 改为加载 `.env`。
- `.env.example` 保留模板用途。
- `docs/deployment.md` 增加步骤：
  - 复制 `.env.example` 为 `.env`。
  - 配置 `COMPANY_PROVIDER`。
  - 配置 `LLM_ENABLED`、`LLM_API_KEY`、`LLM_MODEL`。
- 在应用启动时增加配置检查：
  - `APP_ENV=production` 且 `COMPANY_PROVIDER=mock` 时输出 warning 或拒绝启动。

**Location**:

- `D:\audit-agent\docker-compose.yml`
- `D:\audit-agent\.env.example`
- `D:\audit-agent\docs\deployment.md`
- `D:\audit-agent\app\infrastructure\settings.py`

**Acceptance Criteria**:

- Docker 文档不再建议直接使用 `.env.example` 作为运行配置。
- 生产环境误用 mock provider 时有明确提示。

## Sprint 6: 补齐可观测和报表指标

**Goal**: 让项目能解释“为什么通过/驳回/复核”，并用指标证明业务价值。

**Demo/Validation**:
- 结果 Excel 包含证据信息、风险原因、LLM 语义判断摘要。
- eval 输出包含四类动作比例和 LLM 失败率。

### Problem 6.1: 指标不够完整

**出现原因**:

- 当前 metrics 主要统计 review 和 auto handled。
- 业务文档要求统计 `auto_approval_rate`、`auto_rejection_rate`、`insufficient_evidence_rate`、`llm_failure_rate`、`average_latency_ms`。
- 当前没有把 LLM failed assessment 聚合成 `llm_failure_rate`。

**影响**:

- 简历和项目汇报中的指标无法全部由系统自动产出。
- 无法长期观察 Agent 质量变化。

**最优解决方案**:

- 扩展 `calculate_review_metrics()` 或新增 `calculate_audit_metrics()`。
- 按 `ApprovalDecision.action` 统计四类动作比例。
- 从 `AgentAssessment` 中统计 classification_agent failed 数量，计算 `llm_failure_rate`。
- 输出平均单条耗时。

**Location**:

- `D:\audit-agent\app\services\review_service.py`
- `D:\audit-agent\app\workflow\nodes.py`
- `D:\audit-agent\scripts\run_eval.py`
- `D:\audit-agent\tests\unit\test_review_service.py`

**Acceptance Criteria**:

- `run_eval.py` 输出包含业务文档要求的核心指标。
- 指标字段命名和文档一致。

## Testing Strategy

每个 Sprint 修完后都必须运行：

```powershell
D:\audit-agent\.venv\Scripts\python.exe -m pytest
D:\audit-agent\.venv\Scripts\python.exe -m ruff check .
D:\audit-agent\.venv\Scripts\python.exe scripts\run_eval.py
D:\audit-agent\.venv\Scripts\python.exe scripts\demo_trace.py
```

最终验收要求：

- 单元测试和集成测试全部通过。
- `ruff check .` 通过。
- `run_eval.py` 的 `case_count >= 30`。
- `run_eval.py` 的 `accuracy >= 0.8`。
- 四类审批动作都有覆盖。
- LLM 失败不会导致整批 batch 失败。
- API 响应不暴露内部路径。

## Potential Risks & Gotchas

- **规则文件和 golden cases 口径不一致**：这是准确率下降的最大原因。修复时不要只改算法，要同步校验规则、证据、期望动作。
- **过度依赖关键词**：简单关键词命中容易把 rejected 判成 approved。建议在 mock 分类里也模拟“候选规则支持”和“员工录入分类支持”的差异。
- **LLM 输出模型变更影响大量测试**：先新增新模型并兼容旧 mock，再逐步替换测试。
- **高风险全转人工会降低自动处理率**：这是安全和效率的取舍。首版应优先安全，等评测稳定后再引入可配置策略。
- **Docker 配置修改会影响本地演示**：文档里保留 local mock 启动方式，但不要让生产默认使用 mock。

## Rollback Plan

- 规则和 golden cases 修改前先保留当前版本备份。
- LLM 输出模型重构时保留旧 `MockClassificationProvider` 测试用例，确认新旧行为差异。
- 如果 Decision Agent 重构导致准确率明显下降，先回退到旧逻辑，再单独修规则和评测集。
- Docker 配置变更如果影响本地运行，可以临时通过 `docker compose --env-file .env.example up` 启动 demo，但文档中应标注这只适合本地演示。

## Recommended Execution Order

1. 先修 `run_eval.py` 门禁和错例输出。
2. 对齐 `golden_cases`、规则和 mock evidence，把准确率拉回 80% 以上。
3. 重构 LLM 语义输出模型和 Decision Agent。
4. 增加高风险自动驳回兜底。
5. 修 API 路径泄露和人工复核校验。
6. 修 Docker 配置和部署文档。
7. 补齐业务指标和 CI 门禁。
