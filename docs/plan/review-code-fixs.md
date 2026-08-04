# Review: audit-agent 对照桌面 plan.md 的代码审查与修复方案

**生成日期**：2026-07-30  
**规格来源**：`C:\Users\Administrator\Desktop\document\plan.md`  
**项目目录**：`D:\audit-agent`  
**审查方式**：当前仓库没有任何 commit，无法执行 `git diff <fixed-point>...HEAD`，因此本次按“全量代码是否满足 plan.md”进行审查。  

## 1. 验证结果摘要

使用项目虚拟环境验证：

```powershell
D:\audit-agent\.venv\Scripts\python.exe -m pytest
D:\audit-agent\.venv\Scripts\python.exe -m ruff check .
D:\audit-agent\.venv\Scripts\python.exe scripts\run_eval.py
D:\audit-agent\.venv\Scripts\python.exe scripts\demo_trace.py
```

当前结果：

- `pytest`：116 passed。
- `ruff check .`：通过。
- `demo_trace.py`：可展示一条 Agent 链路。
- `run_eval.py`：30 条 golden cases 的 accuracy 为 **56.67%**。

结论：工程测试通过，但业务验收没有通过。后续修改不能死板按 `plan.md` 回退到第一版，而要按“业务目标是否达成、后续优化是否合理、验收指标是否可证明”来判断。

## 1.1 本次修订后的 review 原则

桌面 `plan.md` 是第一版建设蓝图，不是最终不可变接口规范。当前项目已经在第一版基础上做了不少增强，例如：

- 增加了真实 Excel 规则转换脚本。
- 增加了官网 `WebsiteCompanyProvider`。
- 增加了前端静态工作台。
- 增加了批内并发处理。
- 增加了结果 Excel 证据字段。
- 增加了更细的 batch repository 和依赖注入。

这些增强不应该为了“贴合第一版 plan”而回退。本文后续只把以下情况列为必须修复：

1. 影响业务验收指标的真实问题。
2. 破坏核心架构边界的问题，例如 LLM 直接决定审批动作。
3. 影响上线安全、人工复核闭环、可观测性和可维护性的问题。
4. 和 plan 的接口或文件名不一致，但会导致 README、部署、演示命令失败的问题。

如果当前实现比 plan 更合理，处理原则是：**保留优化，补齐文档、兼容接口或测试证明，不回退到第一版。**

## 2. P0 问题：golden cases 准确率不达标

### 2.1 问题描述

桌面 `plan.md` 要求：

- Sprint 13 要输出 `accuracy`。
- 首版门槛要求 golden cases 准确率 `>= 80%`。
- Definition of Done 要求 `python scripts/run_eval.py` 能输出评测指标。

当前执行 `run_eval.py`：

```json
"case_count": 30,
"accuracy": 0.5666666666666667
```

这低于 80% 的最低验收线。

### 2.2 出现原因

1. `evals/golden_cases.json`、`data/rules/category_rules.json`、`data/evidence/mock_company_evidence.json` 三者没有形成强绑定。
2. 规则 JSON 替换或扩展后，部分 golden case 的期望分类路径已经无法在规则库中命中。
3. mock 分类逻辑大量依赖关键词命中，无法稳定区分“证据支持员工录入分类”和“证据支持其他候选分类”。
4. `tests/integration/test_run_eval.py` 只断言存在 `accuracy` 字段，没有断言准确率必须达标。

### 2.3 影响

- 项目不满足首版 Definition of Done。
- 演示时如果说“准确率 >= 80%”会和实际命令输出冲突。
- 后续改规则、证据或 LLM 逻辑时，准确率退化不会被 CI 或测试发现。

### 2.4 最优解决方案

1. 增强 `scripts/run_eval.py`：
   - 增加 `--min-accuracy` 参数，默认 `0.8`。
   - accuracy 低于阈值时返回非 0 退出码。
   - 输出错例列表：`case_id`、`expected_action`、`actual_action`、`reason`。

2. 增强 `tests/integration/test_run_eval.py`：
   - 使用正式 `evals/golden_cases.json` 做集成测试。
   - 断言 `case_count >= 30`。
   - 断言 `accuracy >= 0.8`。
   - 断言四类动作都有覆盖。

3. 对齐评测数据：
   - 为每条 golden case 增加 `expected_reason`。
   - 检查每条 case 的录入分类是否存在于当前规则库。
   - 检查 mock evidence 是否明确支持或不支持期望动作。

### 2.5 涉及文件

- `D:\audit-agent\scripts\run_eval.py`
- `D:\audit-agent\tests\integration\test_run_eval.py`
- `D:\audit-agent\evals\golden_cases.json`
- `D:\audit-agent\data\rules\category_rules.json`
- `D:\audit-agent\data\evidence\mock_company_evidence.json`

### 2.6 验收标准

- `python scripts/run_eval.py` 输出 `accuracy >= 0.8`。
- 人为改错一个 expected action 后，`run_eval.py` 会失败。
- 测试能阻止低准确率代码进入交付状态。

## 3. P0 问题：LLM 仍然拥有最终审批动作

### 3.1 问题描述

桌面 `plan.md` 明确要求：

- Classification Agent：LLM 只做语义判断，不控制流程。
- LLM 输出字段应包括 `result`、`confidence`、`matched_level1`、`matched_level2`、`matched_level3`、`evidence_quotes`、`reason`、`suggestion`。
- Decision Agent：最终审批规则集中写在 `app/domain/decisions.py`，不要散在 prompt 里。

当前实现中：

- `LLMClassificationResult` 包含 `action`。
- prompt 要求 LLM 输出 `approved | rejected | needs_more_evidence | needs_human_review`。
- Decision Agent 大多数情况下直接返回 `classification_result.action`。

### 3.2 出现原因

开发过程中把“语义分类结果”和“最终审批结论”混成了一个模型。这样实现速度快，但破坏了 plan 中的核心边界：LLM 只能提供语义判断，最终动作必须由确定性代码生成。

### 3.3 影响

- LLM 幻觉可能直接影响最终审批动作。
- 很难向面试官解释“业务规则不在 prompt 里”。
- 高风险、低置信度、分类编造等情况无法在统一决策层被稳定兜底。

### 3.4 最优解决方案

1. 重命名并重建 LLM 输出模型：

```python
class SemanticClassificationResult(BaseModel):
    """LLM 只输出语义判断，不输出最终审批动作。"""

    result: str
    confidence: int
    matched_level1: str = ""
    matched_level2: str = ""
    matched_level3: str = ""
    evidence_quotes: list[str] = []
    reason: str
    suggestion: str = ""
```

2. 修改 prompt：
   - 删除 `action`、`risk_score`、`needs_review`。
   - 要求 LLM 只判断证据是否支持员工录入分类。
   - 要求 LLM 只能从候选规则里选择匹配分类。

3. 增加候选规则合法性校验：
   - LLM 返回的 matched 分类必须存在于 `CandidateRuleSet.candidates`。
   - 编造分类时，Classification Agent 输出 failed assessment，Decision Agent 转人工复核。

4. 把最终审批动作集中到 `app/domain/decisions.py`：
   - `decide_final_action(evidence, rules, semantic_result, risk)`。
   - Decision Agent 只调用这个确定性函数，不直接信任 LLM action。

### 3.5 涉及文件

- `D:\audit-agent\app\agents\llm_classification_provider.py`
- `D:\audit-agent\app\agents\classification_agent.py`
- `D:\audit-agent\app\agents\decision_agent.py`
- `D:\audit-agent\app\domain\decisions.py`
- `D:\audit-agent\tests\unit\test_llm_classification_provider.py`
- `D:\audit-agent\tests\unit\test_classification_agent.py`
- `D:\audit-agent\tests\unit\test_risk_decision_explanation_agents.py`

### 3.6 验收标准

- LLM 输出模型不再包含 `action` 字段。
- prompt 不再要求模型输出最终审批动作。
- `domain/decisions.py` 有最终决策函数和单元测试。
- LLM JSON 失败、缺字段、编造分类时，单条记录进入人工复核，整批不失败。

## 4. P1 问题：Excel 读取和建单缺少统一 trace，不强制回退成第一版 Intake Agent

### 4.1 问题描述

桌面 `plan.md` 要求：

- Agent 分工包含 Intake Agent。
- LangGraph 工作流包含 `read_excel`、`create_cases`、`collect_evidence`、`retrieve_rules`、`classify_semantics` 等节点。

当前实现：

- 没有 `app/agents/intake_agent.py`。
- `read_audit_excel()` 和 `create_audit_cases_with_errors()` 在 `app/api/routes.py` 中直接执行。
- LangGraph 从已经创建好的 `cases` 开始，只覆盖 Evidence、Rule、Classification、Risk、Decision、Explanation、Review、Metrics。
- 当前实现已经增强了真实 Excel 行级容错，坏行可以转人工复核，这比第一版 plan 更进一步，不应该回退。

### 4.2 出现原因

为了快速跑通上传接口，并支持真实 Excel 行级容错，把 Excel 解析和建单逻辑放在 API route 中同步执行。这个方向本身可以保留，真正的问题是 trace 和业务编排边界不够清晰。

### 4.3 影响

- 缺字段、脏数据、Excel 解析异常目前不容易作为统一 AgentAssessment 进入 trace。
- `demo_trace.py` 无法展示 plan 中完整的审批生命周期。
- 后续如果要做 checkpoint、异步任务或任务恢复，API route 中的前置逻辑复用成本较高。

### 4.4 最优解决方案

不要求必须照第一版新增一个形式上的 `IntakeAgent`。推荐两种方案，优先方案 A：

**方案 A：保留当前 service，实现统一 intake trace**

1. 保留 `read_audit_excel()` 和 `create_audit_cases_with_errors()`。
2. 新增 `build_intake_assessment()`，把有效行、坏行、错误原因写入 AgentAssessment。
3. API route 继续做上传入口，但把建单结果交给一个 application service，减少 route 体积。

**方案 B：如果后续要做异步任务，再新增 IntakeAgent**

1. 新增 `IntakeAgent`。
2. 将 Excel 行转 case 的逻辑迁移进去。
3. workflow 增加 `read_excel_node` 和 `create_cases_node`。

无论选哪种，都必须保留当前行级容错：
   - 坏行不能导致整批失败。
   - 坏行转 `needs_human_review` 或 `needs_more_evidence`。

### 4.5 涉及文件

- `D:\audit-agent\app\agents\intake_agent.py`
- `D:\audit-agent\app\workflow\nodes.py`
- `D:\audit-agent\app\workflow\state.py`
- `D:\audit-agent\app\api\routes.py`
- `D:\audit-agent\tests\unit\test_intake_agent.py`
- `D:\audit-agent\tests\unit\test_workflow_nodes.py`

### 4.6 验收标准

- trace 或 assessments 中能看到 Excel 读取、有效行数量、坏行数量、坏行原因。
- Excel 坏行继续不会导致整批失败。
- API route 不再堆积过多业务细节，核心编排进入 service 或 workflow。

## 5. P2 问题：API 路由和第一版 plan 不一致，但不要求回退

### 5.1 问题描述

桌面 `plan.md` 要求：

- 上传接口：`POST /api/audit/batches`
- 下载接口：`GET /api/audit/batches/{batch_id}/download`
- 状态接口：`GET /api/audit/batches/{batch_id}`

当前实现：

- 上传接口是 `POST /api/audit/upload`。
- 下载接口是 `GET /api/audit/batches/{batch_id}/result`。
- 状态接口只返回批次摘要，不返回处理进度、各状态数量、是否可下载。

### 5.2 出现原因

实现时采用了更直观的 upload/result 命名，并且已经形成了可用闭环。接口名和第一版 plan 不一致本身不是 bug，真正需要关注的是：README、前端、测试、部署文档是否统一，以及 batch 状态是否足够表达任务进度。

### 5.3 影响

- 如果 README 或演示仍按 plan 写 `/api/audit/batches`，用户会调用失败。
- 当前 batch 状态信息偏摘要，不够支撑“任务状态式审批系统”的讲法。
- 如果未来要对外开放 API，需要稳定命名并避免频繁破坏兼容。

### 5.4 最优解决方案

推荐不要删除或回退当前接口。采用兼容增强：

1. 保留当前接口：
   - `POST /api/audit/upload`
   - `GET /api/audit/batches/{batch_id}/result`

2. 如果需要对齐 plan 或外部使用，再新增别名接口：
   - `POST /api/audit/batches` 复用上传逻辑。
   - `GET /api/audit/batches/{batch_id}/download` 复用下载逻辑。

3. README 和前端只保留一套主推荐接口，避免两套口径混乱。

4. 增强批次状态响应：
   - `total_count`
   - `processed_count`
   - `status_counts`
   - `review_task_count`
   - `download_ready`
   - `download_url`

### 5.5 涉及文件

- `D:\audit-agent\app\api\routes.py`
- `D:\audit-agent\app\api\schemas.py`
- `D:\audit-agent\tests\integration\test_upload_api.py`
- `D:\audit-agent\tests\integration\test_download_api.py`
- `D:\audit-agent\tests\integration\test_batch_status_api.py`
- `D:\audit-agent\README.MD`

### 5.6 验收标准

- 当前接口继续可用。
- 文档、前端、测试中的接口口径统一。
- 如新增 plan 别名接口，必须复用同一套实现，不复制业务逻辑。
- 批次查询能告诉用户任务是否可下载。

## 6. P2 问题：LangGraph 当前是批处理汇总图，是否拆条件路由取决于后续需求

### 6.1 问题描述

桌面 `plan.md` 要求工作流包含：

- `route_by_decision`
- `auto_approve`
- `auto_reject`
- `create_review_task`
- `request_more_evidence`

当前实现：

- `app/workflow/routing.py` 有 `route_decision()`。
- `graph.py` 没有 `add_conditional_edges()`。
- 当前图是线性节点：Decision -> Explanation -> create_review_tasks -> build_metrics。
- 当前实现已经支持四类审批动作和 review task 生成，因此不需要为了形式对齐 plan 立即拆回第一版路由。

### 6.2 出现原因

当前实现把四类动作都收敛到后处理节点中统一汇总，这对批量同步审批更简单。它不是错误，只是 trace 中看不到 `auto_approve`、`auto_reject`、`request_more_evidence` 这些独立业务节点。

### 6.3 影响

- 如果只做批量同步审批，当前线性图可以保留。
- 如果后续要给不同动作挂不同副作用，例如通知员工、创建补证任务、自动写回系统，则当前结构扩展性不足。
- demo trace 的业务表达力弱一些，看不出四类动作的不同路由。

### 6.4 最优解决方案

分两步处理：

1. 短期不强拆 graph：
   - 保留当前 fan-out/fan-in 和汇总节点。
   - 在 `explanation_agent` 或 metrics 中补充动作路由统计。
   - `route_decision()` 保留为可测试的纯函数。

2. 只有当后续需要不同动作触发不同副作用时，再加入条件路由：
   - `decision_agent` 后进入 `route_by_decision`。
   - 根据动作路由到 `auto_approve`、`auto_reject`、`request_more_evidence`、`create_review_task`。
   - 确保 decisions、review_tasks、trace_events 不丢失。

### 6.5 涉及文件

- `D:\audit-agent\app\workflow\graph.py`
- `D:\audit-agent\app\workflow\routing.py`
- `D:\audit-agent\app\workflow\nodes.py`
- `D:\audit-agent\tests\unit\test_workflow_routing.py`
- `D:\audit-agent\tests\integration\test_workflow_graph.py`

### 6.6 验收标准

- 短期：四类审批动作有明确统计和测试覆盖。
- 短期：`route_decision()` 单元测试覆盖四类动作。
- 长期：如果引入条件路由，`demo_trace.py` 可以看到不同 route 节点。

## 7. P1 问题：存储层能力还缺任务状态和可查询 trace，不要求表名回退

### 7.1 问题描述

桌面 `plan.md` 要求 SQLite 表包括：

- `batches`
- `cases`
- `decisions`
- `review_tasks`
- `agent_traces`

并要求任务状态接口返回：

- 总数。
- 已处理数。
- 各状态数量。
- 是否可下载。

当前实现：

- 使用 `audit_batches`、`audit_cases`、`audit_decisions`、`review_tasks`、`agent_assessments`。
- 没有独立 `agent_traces` 表。
- 批次状态接口只返回摘要字段，无法表达处理进度和下载状态。

### 7.2 出现原因

当前系统是同步执行，上传请求结束时 batch 已处理完，所以没有优先实现“任务状态机”。另外，当前表名比第一版 plan 更贴近具体业务，不需要为了 plan 改回 `batches/cases/decisions` 这种泛名。

### 7.3 影响

- 用户不能知道任务跑到哪一步。
- 如果以后变成异步批处理，当前 schema 不够用。
- trace 只能在 workflow 返回或日志中看，不利于按 batch/case 查询。

### 7.4 最优解决方案

保留当前 repository 和表名，补能力，不回退：

1. 增加批次状态字段：
   - `status`
   - `processed_count`
   - `failed_count`
   - `download_ready`
   - `updated_at`

2. 二选一补充可查询 trace：
   - 方案 A：复用 `agent_assessments`，增加按 batch_id/case_id 查询接口。
   - 方案 B：新增 `agent_traces` 表，保存节点级 trace event。

   如果当前 `agent_assessments` 已能满足排查，就优先方案 A，避免过早拆表。

3. 如果新增 `agent_traces` 表，字段建议：
   - `trace_id`
   - `batch_id`
   - `case_id`
   - `node_name`
   - `status`
   - `duration_ms`
   - `input_summary_json`
   - `output_summary_json`
   - `error`

4. 增加状态查询 service：
   - 聚合 decisions、cases、review_tasks、result_file。
   - 返回 plan 要求的任务状态字段。

### 7.5 涉及文件

- `D:\audit-agent\app\infrastructure\database.py`
- `D:\audit-agent\app\infrastructure\batch_repository.py`
- `D:\audit-agent\app\services\batch_service.py`
- `D:\audit-agent\app\api\schemas.py`
- `D:\audit-agent\app\api\routes.py`
- `D:\audit-agent\tests\unit\test_batch_repository.py`
- `D:\audit-agent\tests\integration\test_batch_status_api.py`

### 7.6 验收标准

- 可按 batch_id 查询任务状态。
- 可按 batch_id 或 case_id 查询 AgentAssessment/trace。
- 批次完成后能明确表达 `download_ready = true` 或等价字段。
- 不要求把现有表名改回第一版 plan。

## 8. P1 问题：人工复核不能真正覆盖 Agent 结论

### 8.1 问题描述

桌面 `plan.md` 要求：

- 人工提交复核结论。
- 人工结论可以覆盖 Agent 结论。
- 结果导出包含 Agent 结论、人工结论、证据、建议。

当前实现：

- `POST /api/review/tasks/{task_id}/decision` 只更新 review task 的 `final_action`。
- 原始 `audit_decisions` 不会生成被人工覆盖后的最终结论。
- 结果 Excel 是上传时生成的，人工复核后不会重新导出或体现人工结论。

### 8.2 出现原因

当前人工复核更像“任务备注”，还没有成为审批最终状态的一部分。

### 8.3 影响

- 审核员提交结果后，下载的 Excel 仍可能是旧的 Agent 结论。
- 无法统计人工覆盖率、Agent 错误率。
- 人工复核闭环没有真正闭合。

### 8.4 最优解决方案

1. 人工提交时保存覆盖关系：
   - `agent_action`
   - `final_action`
   - `reviewer`
   - `reviewed_at`
   - `review_comment`

2. 增加最终结果查询：
   - 如果有人工结论，优先展示人工结论。
   - 没有人工结论，展示 Agent 结论。

3. 下载结果时动态生成或重新生成 Excel：
   - `审批明细` 同时包含 `Agent 结论` 和 `人工最终结论`。

### 8.5 涉及文件

- `D:\audit-agent\app\services\batch_service.py`
- `D:\audit-agent\app\infrastructure\batch_repository.py`
- `D:\audit-agent\app\infrastructure\excel_writer.py`
- `D:\audit-agent\app\services\result_file_service.py`
- `D:\audit-agent\tests\integration\test_review_decision_api.py`
- `D:\audit-agent\tests\e2e\test_audit_batch_flow.py`

### 8.6 验收标准

- 人工复核完成后再次下载 Excel，能看到人工最终结论。
- 人工结论不会覆盖丢失 Agent 原始结论。
- 非法 final_action 会返回 422。

## 9. P2 问题：业务指标不完整

### 9.1 问题描述

桌面 `plan.md` 要求 `run_eval.py` 输出：

- `accuracy`
- `auto_approval_rate`
- `auto_rejection_rate`
- `human_review_rate`
- `insufficient_evidence_rate`
- `llm_failure_rate`
- `average_latency_ms`

当前 `run_eval.py` 输出中只有 `accuracy` 和部分 review/auto handled 指标，没有完整字段。

### 9.2 出现原因

当前指标主要服务于开发阶段验证，没有严格按 plan 中的汇报指标设计。

### 9.3 影响

- 简历成果里的指标不能完全由系统生成。
- 无法长期观察自动通过、自动驳回、证据不足、LLM 失败等关键业务变化。

### 9.4 最优解决方案

1. 新增 `app/observability/metrics.py`。
2. 实现 `calculate_audit_metrics()`：
   - 从 decisions 统计四类动作比例。
   - 从 assessments 统计 LLM/classification 失败率。
   - 从 trace 或 assessments 计算平均单条耗时。
3. `run_eval.py` 和 API upload 统一使用同一套 metrics。

### 9.5 涉及文件

- `D:\audit-agent\app\observability\metrics.py`
- `D:\audit-agent\app\workflow\nodes.py`
- `D:\audit-agent\scripts\run_eval.py`
- `D:\audit-agent\tests\unit\test_metrics.py`
- `D:\audit-agent\tests\integration\test_run_eval.py`

### 9.6 验收标准

- `run_eval.py` 输出 plan 要求的全部指标。
- API 上传响应中的 metrics 和 eval 指标口径一致。

## 10. P3 问题：入口文件和 Docker 启动命令偏离第一版 plan，属于文档兼容问题

### 10.1 问题描述

桌面 `plan.md` 多处使用：

- `app/main.py`
- `uvicorn app.main:app --reload`

当前实现：

- FastAPI 应用在 `app/api/app.py`。
- Docker 使用 `uvicorn app.api.app:app`。
- `app/main.py` 不存在。

### 10.2 出现原因

实现时把 API app 放到了 `app/api/` 下，这本身不是错误，也不需要回退。只有当 README、Docker、部署文档或面试演示命令不统一时，它才会变成使用问题。

### 10.3 影响

- 如果用户按桌面 plan 执行 `uvicorn app.main:app --reload` 会失败。
- 如果 README 已经统一写 `app.api.app:app`，则可以不改代码。
- 如果想降低沟通成本，可以加一个轻量兼容入口。

### 10.4 最优解决方案

二选一，不强制：

**方案 A：增加兼容入口**

- 新增 `app/main.py`。
- 内容只做一件事：从 `app.api.app` 导出 `app`。
- Docker 和 README 统一改为 `uvicorn app.main:app`。

**方案 B：保留当前优化结构，统一所有文档**

- 保留 `app/api/app.py`。
- 修改 plan 相关落地文档、README、deployment。

如果只是项目自用，方案 B 足够。如果希望别人按通用 FastAPI 入口快速理解，方案 A 更友好。

### 10.5 涉及文件

- `D:\audit-agent\app\main.py`
- `D:\audit-agent\Dockerfile`
- `D:\audit-agent\README.MD`
- `D:\audit-agent\docs\deployment.md`

### 10.6 验收标准

- README、Dockerfile、deployment 中的启动入口一致。
- 如果新增 `app/main.py`，则 `uvicorn app.main:app --reload` 可以启动。
- 如果不新增，则文档不能再要求用户运行 `app.main:app`。

## 11. P2 问题：CI 缺失

### 11.1 问题描述

桌面 `plan.md` Sprint 17 要求 `.github/workflows/ci.yml`：

- 安装依赖。
- `ruff check .`。
- `python -m pytest`。
- 构建 Docker 镜像。

当前项目没有 `.github/workflows/ci.yml`。

### 11.2 出现原因

项目处于本地开发完成阶段，还没有进入远程仓库和 CI 交付阶段。

### 11.3 影响

- 代码质量完全依赖本地手动运行。
- 评测准确率和 Docker 构建不会被自动保护。
- 多人协作时容易把不可运行版本合进去。

### 11.4 最优解决方案

新增 CI workflow：

```yaml
name: ci

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: python -m pip install -e ".[dev]"
      - run: python -m ruff check .
      - run: python -m pytest
      - run: python scripts/run_eval.py --min-accuracy 0.8
      - run: docker build -t audit-agent .
```

### 11.5 涉及文件

- `D:\audit-agent\.github\workflows\ci.yml`
- `D:\audit-agent\scripts\run_eval.py`

### 11.6 验收标准

- push 或 PR 自动运行 lint、test、eval、docker build。
- accuracy 低于 80% 时 CI 失败。

## 12. P2 问题：端到端测试目录存在但没有 e2e 流程测试

### 12.1 问题描述

桌面 `plan.md` 要求：

- `tests/e2e/test_audit_batch_flow.py`
- 流程覆盖上传样例 Excel、查询 batch 状态、查询复核任务、提交人工复核、下载结果。

当前项目没有完整 e2e 流程测试。

### 12.2 出现原因

当前测试偏单元和集成，API 端到端闭环没有单独沉淀成 e2e 用例。

### 12.3 影响

- 上传、审批、复核、下载之间的组合问题不容易被发现。
- 人工复核覆盖最终结果这类跨模块问题不会被测试抓到。

### 12.4 最优解决方案

新增 `tests/e2e/test_audit_batch_flow.py`：

1. 用模板生成样例 Excel。
2. 调用上传接口。
3. 查询 batch 状态。
4. 查询 review tasks。
5. 对一条任务提交人工结论。
6. 下载结果 Excel。
7. 读取 Excel，确认 Agent 结论和人工结论都存在。

### 12.5 涉及文件

- `D:\audit-agent\tests\e2e\test_audit_batch_flow.py`
- `D:\audit-agent\tests\fixtures\`
- `D:\audit-agent\app\api\routes.py`
- `D:\audit-agent\app\infrastructure\excel_writer.py`

### 12.6 验收标准

- 无真实 LLM、无真实网络也能跑完整 e2e。
- e2e 覆盖上传、状态、复核、下载。

## 13. Standards Review

### 13.1 当前做得好的地方

- 分层结构基本清晰：`domain`、`agents`、`services`、`infrastructure`、`workflow`、`api` 已拆开。
- 测试数量较充分，当前已有 116 个测试通过。
- 文件上传有大小限制和后缀限制。
- 下载接口有 batch_id 路径穿越校验。
- 证据采集、规则召回、分类判断、风险、决策、解释都已有 AgentAssessment。

### 13.2 代码味道和工程问题

1. **Primitive Obsession：人工复核动作是裸字符串**
   - `ReviewDecisionRequest.final_action` 是 `str`。
   - 建议改为枚举，避免非法值落库。

2. **Divergent Change：API route 承担过多职责**
   - `upload_audit_excel()` 同时保存文件、读 Excel、建 case、加载规则、调用 workflow、生成 Excel、保存数据库、拼响应。
   - 建议把上传编排收敛到 application service 或 workflow node。

3. **已完成的合理增强：WebsiteProvider 和静态工作台应保留**
   - 官网 provider、真实 Excel 支持、前端静态工作台属于第一版之后的合理增强，不应该按第一版 plan 删除。
   - 当前建议不是回退这些能力，而是给它们补测试、文档和配置开关，确保 mock 模式和真实模式都稳定。

4. **命名口径不统一**
   - plan 用 `company_provider.py`、`storage.py`、`app/main.py`。
   - 当前用 `evidence_provider.py`、`batch_repository.py/database.py`、`app/api/app.py`。
   - 当前拆分可以保留。只需要统一 README、部署文档、测试和演示命令，不要让用户按过期 plan 命令失败。

## 14. 推荐修复顺序

1. 修 `run_eval.py` 门禁和错例输出。
2. 对齐 golden cases、规则、mock evidence，把 accuracy 拉到 80% 以上。
3. 重构 LLM 输出 schema，删除 LLM 的最终审批动作。
4. 把最终决策规则集中到 `domain/decisions.py`，同时保留当前 Risk/Decision/Explanation 多 Agent 拆分。
5. 增加高风险兜底：高风险自动通过和自动驳回都转人工复核。
6. 保留当前真实 Excel 行级容错，补 intake trace 或 application service，不强制新增形式化 IntakeAgent。
7. 保留当前 API，必要时新增 `/api/audit/batches` 和 `/download` 作为兼容别名，不复制业务逻辑。
8. 增强 batch 状态和 AgentAssessment/trace 查询能力，不强制改表名。
9. 让人工复核结果真正进入最终导出结果。
10. 补齐 metrics、CI、e2e。
11. 保留 WebsiteProvider、前端静态工作台、批内并发等后续优化，为它们补测试和文档。

## 15. 最终验收清单

修复后交付前必须满足：

- `python -m pytest` 全部通过。
- `ruff check .` 通过。
- `python scripts/demo_trace.py` 能展示从 intake 到 decision 的完整链路。
- `python scripts/run_eval.py` 输出完整指标，且 `accuracy >= 0.8`。
- README 中声明的 uvicorn 启动命令能启动，不强制必须是 `app.main:app`。
- README 中声明的上传接口能上传 Excel 并生成 batch。
- `GET /api/audit/batches/{batch_id}` 或等价状态接口能看到状态。
- README 中声明的下载接口能下载结果。
- 人工复核提交后，结果 Excel 能看到人工最终结论。
- Docker 镜像能构建。
- CI 能自动执行 lint、test、eval、docker build。
