# Plan: 审批 Agent 企业级能力补齐计划

**Generated**: 2026-07-30  
**Estimated Complexity**: High  
**Scope**: 针对当前审批 Agent 距离企业级项目的差距，制定可分阶段实施的详细解决计划。  
**Explicit Non-Goals**: 本计划暂不改动部署方案；不接入企查查、天眼查等付费 API；免费公共证据源只能在合法、稳定、低频、可解释的前提下使用。

## Overview

当前项目已经具备完整审批链路：Excel 上传、规则召回、证据采集、Classification Agent、Risk Agent、Decision Agent、结果 Excel、人工复核、指标评估和 CI。验证基线也不错：`pytest`、`ruff`、`run_eval` 都能通过。

但企业级审批 Agent 不只是能跑通，还必须满足：

- 谁能上传、谁能查看、谁能复核、谁能下载，都要可控。
- 大批量任务不能堵在一个 HTTP 请求里。
- 人工复核后的 API、数据库、Excel 下载结果必须一致。
- 审批数据、证据、决策、人工操作要能追踪和审计。
- 证据不能只靠单次官网访问，免费来源也要形成可靠的证据链。
- 评估不能只看 mock golden cases，要覆盖真实失败模式。
- 可观测性要能帮助定位“慢在哪里、错在哪里、为什么错”。

本计划分 7 个 Sprint 推进：

1. 身份认证、角色权限、租户边界。
2. 批量任务异步化。
3. 人工复核和结果文件一致性。
4. 数据库结构、迁移和审计日志。
5. 敏感数据和文件治理。
6. 免费公共证据源增强。
7. 评估体系和可观测性增强。

部署改造相关内容本次不做，只保留必要的代码内可观测和配置能力。

## Current Baseline

### 已具备能力

- Excel 上传和解析。
- 真实官网证据 provider。
- Mock evidence provider。
- Classification Agent 支持真实 LLM 和 mock provider。
- LLM 输出 JSON 校验、候选规则 ID、部分降级策略。
- TopK 规则召回已开始向 Top5/Top8 动态召回演进。
- 人工复核任务和复核提交接口。
- 结果 Excel 下载。
- SQLite 本地持久化。
- pytest、ruff、golden eval、Docker build CI。

### 企业级差距

- API 无认证、无授权、无租户隔离。
- 上传接口同步执行完整工作流，无法承载大批量或长耗时任务。
- 人工复核后结果 Excel 可能仍是旧文件。
- SQLite + JSON blob 缺少迁移、外键、索引、查询能力和审计严肃性。
- 原始上传文件、结果文件、证据文本缺少敏感数据治理。
- 免费证据源单一，官网失败时缺少可解释补证渠道。
- 评估集规模和真实覆盖不足。
- 日志、trace、metrics 还不能支撑线上排障和质量分析。

## Prerequisites

- 项目路径：`D:\audit-agent`
- 主要验证命令：
  - `D:\audit-agent\.venv\Scripts\python.exe -m pytest`
  - `D:\audit-agent\.venv\Scripts\python.exe -m ruff check .`
  - `D:\audit-agent\.venv\Scripts\python.exe scripts\run_eval.py --min-accuracy 0.8`
- 本计划不要求购买任何第三方商业 API。
- 免费证据源必须遵守目标网站规则，不绕过验证码、不高频抓取、不规避反爬。
- 本计划不调整 Docker、compose、生产部署结构。

## Sprint 1: 身份认证、角色权限和租户边界

**Goal**: 让审批系统知道“当前是谁”，并能控制不同用户能做什么、看什么。

**Demo/Validation**:

- 未认证用户访问 `/api/audit/upload`、`/api/review/tasks`、下载接口时返回 401。
- 普通录入人员不能提交人工复核。
- 复核人员只能复核自己租户下的任务。
- 下载结果时只能下载自己有权限的 batch。

### Task 1.1: 定义用户上下文模型

- **Location**:
  - `D:\audit-agent\app\domain\models.py`
  - `D:\audit-agent\app\api\schemas.py`
- **Description**: 新增 `CurrentUser` 或 `UserContext`，包含 `user_id`、`tenant_id`、`roles`。
- **Dependencies**: 无
- **Acceptance Criteria**:
  - 用户上下文在 API 层可被依赖注入获取。
  - 角色建议包括：`uploader`、`reviewer`、`admin`、`auditor`。
  - `tenant_id` 后续能写入 batch、case、review_task。
- **Validation**:
  - 新增单元测试验证模型序列化和角色判断。

### Task 1.2: 增加认证依赖

- **Location**:
  - `D:\audit-agent\app\api\dependencies.py`
  - `D:\audit-agent\app\api\routes.py`
- **Description**: 先实现简单企业内网可用的 Bearer Token 或 API Key 认证。Token 到用户上下文的映射可以先从 `.env` 或本地配置读取，后续再接入企业 SSO。
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - 无 token 返回 401。
  - 无效 token 返回 401。
  - 有效 token 生成 `CurrentUser`。
  - 不在日志中打印 token。
- **Validation**:
  - API 单元测试覆盖上传、查询、下载、复核接口的未认证和认证场景。

### Task 1.3: 增加角色权限校验

- **Location**:
  - `D:\audit-agent\app\api\dependencies.py`
  - `D:\audit-agent\app\api\routes.py`
- **Description**: 新增 `require_role()` 或 `require_any_role()`，在不同接口挂载权限。
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - `uploader` 可上传和查看自己租户的批次。
  - `reviewer` 可查看复核任务并提交复核。
  - `auditor` 可只读查看批次、决策和证据。
  - `admin` 可执行所有操作。
- **Validation**:
  - API 测试覆盖 403 场景。

### Task 1.4: 复核接口不再信任前端 reviewer

- **Location**:
  - `D:\audit-agent\app\api\schemas.py`
  - `D:\audit-agent\app\api\routes.py`
  - `D:\audit-agent\app\services\batch_service.py`
- **Description**: `ReviewDecisionRequest` 中删除或弱化 `reviewer` 字段，服务端使用 `CurrentUser.user_id` 写入 reviewer。
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - 前端传入 reviewer 时不会覆盖服务端用户身份。
  - DB 中 `reviewer` 来自认证用户。
- **Validation**:
  - 单元测试：恶意传入 `reviewer=admin`，实际保存仍为当前用户。

### Task 1.5: 批次和任务加入 tenant_id

- **Location**:
  - `D:\audit-agent\app\domain\models.py`
  - `D:\audit-agent\app\infrastructure\batch_repository.py`
  - `D:\audit-agent\app\services\batch_service.py`
- **Description**: batch、case、decision、review_task 记录都要带 `tenant_id`，查询时必须按 `tenant_id` 过滤。
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - A 租户不能查 B 租户 batch。
  - 下载接口也必须校验 batch 所属租户。
- **Validation**:
  - 集成测试覆盖跨租户访问返回 404 或 403。

## Sprint 2: 批量任务异步化

**Goal**: 上传接口不再同步跑完整 Agent 工作流，改为创建任务、后台执行、前端查询进度。

**Demo/Validation**:

- 上传 Excel 后立即返回 `202` 或 `200`，包含 `batch_id` 和状态 `queued`。
- 后台任务执行完成后，查询批次状态为 `succeeded`。
- 任务失败时能看到失败原因，并可重试。

### Task 2.1: 定义 batch_job 状态模型

- **Location**:
  - `D:\audit-agent\app\domain\models.py`
  - `D:\audit-agent\app\api\schemas.py`
- **Description**: 新增状态枚举：`queued`、`running`、`succeeded`、`failed`、`cancelled`。
- **Dependencies**: Sprint 1 可并行
- **Acceptance Criteria**:
  - API 响应里返回 batch 状态。
  - batch summary 能展示状态、开始时间、结束时间、错误摘要。
- **Validation**:
  - 模型测试。

### Task 2.2: 上传接口只创建任务

- **Location**:
  - `D:\audit-agent\app\api\routes.py`
  - `D:\audit-agent\app\services\upload_service.py`
  - `D:\audit-agent\app\services\batch_service.py`
- **Description**: 把当前 `upload_audit_excel()` 中的长流程拆出为 `run_batch_job(batch_id)`。上传接口只保存文件、创建 batch_job，返回 batch_id。
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - 上传接口不直接调用 `build_audit_workflow().invoke()`。
  - 旧同步流程保留为内部 service，方便测试。
- **Validation**:
  - API 测试断言上传快速返回 queued。

### Task 2.3: 本地后台执行器

- **Location**:
  - `D:\audit-agent\app\services\batch_job_service.py`
  - `D:\audit-agent\app\api\routes.py`
- **Description**: 在不改部署的前提下，先用 FastAPI `BackgroundTasks` 或应用内线程池实现轻量后台执行。后续如果要上生产队列，再替换这一层接口。
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - job 从 queued 变为 running，再变为 succeeded/failed。
  - job 异常不会让上传请求 500。
  - 同一 batch 不会重复执行。
- **Validation**:
  - 集成测试轮询状态直到完成。

### Task 2.4: 批次进度接口

- **Location**:
  - `D:\audit-agent\app\api\routes.py`
  - `D:\audit-agent\app\api\schemas.py`
  - `D:\audit-agent\app\static\app.js`
- **Description**: 增加 `/api/audit/batches/{batch_id}/status`，返回总数、已处理数、失败数、当前阶段。
- **Dependencies**: Task 2.3
- **Acceptance Criteria**:
  - 前端可以展示“排队中/处理中/已完成/失败”。
  - 失败时展示错误摘要。
- **Validation**:
  - API 测试和前端轻量验证。

### Task 2.5: Case 级重试入口

- **Location**:
  - `D:\audit-agent\app\services\batch_job_service.py`
  - `D:\audit-agent\app\api\routes.py`
- **Description**: 对证据失败、LLM 失败、单条 case 失败提供重试能力。
- **Dependencies**: Task 2.4
- **Acceptance Criteria**:
  - 可重试单条 case。
  - 可重试整个 failed batch。
  - 重试不会覆盖人工复核已完成的结论。
- **Validation**:
  - 单元测试覆盖幂等和重复提交。

## Sprint 3: 人工复核和结果 Excel 一致性

**Goal**: API、数据库、下载 Excel 三者始终一致，尤其是人工复核提交后。

**Demo/Validation**:

- 提交人工复核后，查询决策 API 能看到人工结论。
- 再次下载 Excel，明细页也能看到人工最终结论和复核时间。

### Task 3.1: 持久化证据包或结果生成上下文

- **Location**:
  - `D:\audit-agent\app\infrastructure\database.py`
  - `D:\audit-agent\app\infrastructure\batch_repository.py`
- **Description**: 结果 Excel 重建需要 evidence 和 assessment，目前 evidence 主要在工作流内存中。新增 `evidence_packages` 表或把 evidence payload 持久化到 batch details。
- **Dependencies**: Sprint 1 或 2 可并行
- **Acceptance Criteria**:
  - 每个 case 的 `EvidencePackage` 可从 DB 读取。
  - result Excel 可以只基于 DB 重建。
- **Validation**:
  - repository 单元测试覆盖保存和读取 evidence。

### Task 3.2: 下载时动态生成结果 Excel

- **Location**:
  - `D:\audit-agent\app\services\result_file_service.py`
  - `D:\audit-agent\app\api\routes.py`
- **Description**: `download_audit_result()` 不再无条件返回旧文件。可选策略：
    1. 每次下载从 DB 生成临时 Excel。
    2. 复核后标记 result file dirty，下载时重建。
  推荐先用 dirty 标记，兼顾性能和一致性。
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - 人工复核后下载文件包含最新人工结论。
  - 不会下载到不存在或旧版本文件。
- **Validation**:
  - e2e：复核后下载 Excel，用 openpyxl 断言人工最终结论。

### Task 3.3: 复核提交事务化

- **Location**:
  - `D:\audit-agent\app\infrastructure\batch_repository.py`
- **Description**: `complete_review_task()` 同时更新 review_task、decision、batch summary、result dirty 标记，必须在同一个事务里完成。
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - 任一更新失败时整体回滚。
  - 重复提交已完成任务时要幂等或返回明确错误。
- **Validation**:
  - 单元测试模拟重复提交和异常回滚。

### Task 3.4: 增加复核审计事件

- **Location**:
  - `D:\audit-agent\app\domain\models.py`
  - `D:\audit-agent\app\infrastructure\batch_repository.py`
- **Description**: 每次人工复核都记录不可覆盖的 `review_audit_log`，包含 old_action、new_action、reviewer、time、reason。
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - 后续修改复核结论时保留历史。
  - 审计员可查询某条 case 的人工操作历史。
- **Validation**:
  - repository 测试覆盖多次操作历史。

## Sprint 4: 数据库结构和审计能力

**Goal**: 从“本地 JSON 存储”升级为“可查询、可迁移、可审计”的业务数据层。暂不要求切换 PostgreSQL，但先把代码结构准备好。

**Demo/Validation**:

- 数据库 schema 有版本号。
- 关键字段有结构化列和索引。
- 查询不再只能解析 JSON blob。

### Task 4.1: 增加 schema version 和迁移框架

- **Location**:
  - `D:\audit-agent\app\infrastructure\database.py`
  - `D:\audit-agent\app\infrastructure\migrations\`
- **Description**: 先实现轻量 SQLite migration：`schema_migrations` 表记录版本，每次启动按版本执行迁移。
- **Dependencies**: 无
- **Acceptance Criteria**:
  - 新库可从 0 初始化到最新版本。
  - 旧库可增量迁移。
- **Validation**:
  - 集成测试用临时旧库执行迁移。

### Task 4.2: 结构化核心字段

- **Location**:
  - `D:\audit-agent\app\infrastructure\database.py`
  - `D:\audit-agent\app\infrastructure\batch_repository.py`
- **Description**: 对高频查询字段建立结构化列：`tenant_id`、`batch_id`、`case_id`、`employee_name`、`company_name`、`action`、`status`、`needs_review`、`created_at`。
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - 列表和筛选不依赖 JSON 解析。
  - JSON payload 仍保留完整对象，用于兼容和扩展。
- **Validation**:
  - repository 查询测试。

### Task 4.3: 添加外键、索引和唯一约束

- **Location**: `D:\audit-agent\app\infrastructure\database.py`
- **Description**: 为 batch/case/decision/review_task/assessment/evidence 增加外键关系和索引。
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - 同一 batch 内 case 唯一。
  - review_task 必须关联存在的 case。
  - 按 batch_id、tenant_id、status 查询有索引。
- **Validation**:
  - SQLite `PRAGMA foreign_keys=ON` 测试。

### Task 4.4: 抽象 Repository 接口

- **Location**:
  - `D:\audit-agent\app\infrastructure\batch_repository.py`
  - `D:\audit-agent\app\services\batch_service.py`
- **Description**: 把 SQLite 细节封装在 repository 实现里，service 不直接关心数据库类型，为未来 PostgreSQL 留接口。
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - service 层只依赖 repository 协议。
  - 测试可以注入 fake repository。
- **Validation**:
  - 单元测试覆盖 service 不依赖真实 SQLite。

## Sprint 5: 敏感数据和文件治理

**Goal**: 上传文件、结果文件、证据文本、日志都按敏感数据处理。

**Demo/Validation**:

- 上传文件通过 MIME 和文件头校验。
- 下载行为写入审计日志。
- 过期文件可被清理。
- 日志不输出敏感全文。

### Task 5.1: 强化上传校验

- **Location**:
  - `D:\audit-agent\app\services\upload_service.py`
  - `D:\audit-agent\tests\integration\test_file_security.py`
- **Description**: 除 `.xlsx` 后缀外，校验文件头是否为 zip/xlsx 格式，并限制 sheet 数、行数、列数。
- **Dependencies**: 无
- **Acceptance Criteria**:
  - 伪造后缀的文本文件被拒绝。
  - 超过最大行数的 Excel 被拒绝。
  - 错误信息友好。
- **Validation**:
  - 文件安全测试。

### Task 5.2: 文件访问审计

- **Location**:
  - `D:\audit-agent\app\api\routes.py`
  - `D:\audit-agent\app\infrastructure\batch_repository.py`
- **Description**: 每次下载结果 Excel 时记录审计事件：user_id、tenant_id、batch_id、time、ip、user_agent。
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - 审计员可查询下载历史。
  - 审计日志不可被普通复核操作覆盖。
- **Validation**:
  - API 测试覆盖下载后审计记录存在。

### Task 5.3: 文件生命周期管理

- **Location**:
  - `D:\audit-agent\scripts\cleanup_storage.py`
  - `D:\audit-agent\app\infrastructure\settings.py`
- **Description**: 增加配置：上传文件保留天数、结果文件保留天数、是否保留原始证据全文。
- **Dependencies**: 无
- **Acceptance Criteria**:
  - cleanup 脚本只删除过期文件。
  - 不删除仍在 running 的 batch 文件。
- **Validation**:
  - 单元测试用临时目录模拟过期文件。

### Task 5.4: 日志脱敏

- **Location**:
  - `D:\audit-agent\app\observability\logging.py`
  - 各 Agent 和 API 日志调用点
- **Description**: 对企业名称、官网 URL、LLM 原文、证据长文本做截断或脱敏，日志只保留 case_id、batch_id、错误类型。
- **Dependencies**: 无
- **Acceptance Criteria**:
  - 不在日志中输出完整 Excel 内容。
  - 不输出 API Key、token、完整 prompt。
- **Validation**:
  - 单元测试验证脱敏函数。

## Sprint 6: 免费公共证据源增强

**Goal**: 在不使用企查查、天眼查等付费 API 的前提下，增加免费、可解释、低风险的证据来源，让官网访问失败时仍有补证能力。

**Demo/Validation**:

- 官网失败时，可以尝试 ICP 备案、公开信用站点或搜索结果摘要等免费证据。
- 每条证据都记录来源、URL、抓取时间、可信度和错误原因。
- 不绕过验证码、不高频访问、不违反目标站点规则。

### 免费证据源分层

| 来源 | 用途 | 稳定性 | 注意事项 |
| --- | --- | --- | --- |
| 企业官网 | 主业务介绍、产品服务、医院科室等 | 中 | 站点可能 403/502/SSL 失败 |
| 工信部 ICP 备案系统 | 校验域名主体、网站名称、备案主体 | 中 | 页面查询可能有限制，不作为高频 API |
| 国家企业信用信息公示系统 | 校验企业名称、经营状态、基础工商信息 | 中低 | 可能有验证码或登录限制，不绕过 |
| 信用中国及地方信用站点 | 行政许可、处罚、公示信息 | 中 | 地方站点结构差异大 |
| 搜索引擎公开摘要 | 官网失败时补充候选证据 | 中低 | 摘要必须标记低可信，不能单独自动通过高风险结论 |
| 政府/医院/学校/协会官网页面 | 特定行业佐证 | 中 | 优先采集官方域名页面 |

### Task 6.1: 设计 EvidenceProvider 插件协议

- **Location**:
  - `D:\audit-agent\app\agents\evidence_agent.py`
  - `D:\audit-agent\app\infrastructure\website_provider.py`
  - `D:\audit-agent\app\infrastructure\evidence_provider.py`
- **Description**: 把证据采集拆成多个 provider，统一返回 `EvidencePackage` 或 `EvidenceSourceResult`。
- **Dependencies**: 无
- **Acceptance Criteria**:
  - 官网 provider、mock provider 都实现统一协议。
  - 新 provider 可独立失败，不影响其他 provider。
- **Validation**:
  - 单元测试用 fake provider 验证聚合。

### Task 6.2: 增加 EvidenceAggregator

- **Location**:
  - `D:\audit-agent\app\services\evidence_service.py`
  - `D:\audit-agent\app\infrastructure\evidence_aggregator.py`
- **Description**: 新增聚合器：先查官网，失败或质量低时再尝试免费补充来源。
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - 每个来源有 timeout、重试次数、可信等级。
  - 聚合结果保留所有来源的 errors。
  - 质量分由多来源共同计算。
- **Validation**:
  - 单元测试覆盖官网失败但免费来源补证成功。

### Task 6.3: ICP 备案查询证据源

- **Location**:
  - `D:\audit-agent\app\infrastructure\icp_provider.py`
- **Description**: 规划接入工信部 ICP/IP 地址/域名信息备案管理系统的公开查询结果，用于校验域名备案主体和网站名称。实现时必须低频、缓存、遵守页面规则；如果存在验证码或无法稳定访问，则返回 `provider_unavailable`，不绕过。
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - 输入域名，输出备案主体、网站名称、来源 URL、抓取时间。
  - 无法访问时不抛系统异常，只返回证据源失败。
  - ICP 结果只作为主体一致性证据，不直接判断业务分类。
- **Validation**:
  - 使用 fake HTML fixture 测试解析，不依赖真实网络。

### Task 6.4: 国家企业信用信息公示系统补证规划

- **Location**:
  - `D:\audit-agent\app\infrastructure\public_credit_provider.py`
- **Description**: 规划对国家企业信用信息公示系统的公开查询能力。由于该系统可能有验证码、地区入口和访问限制，首版只做“人工可点击证据链接”和“低频可访问页面摘要”，不做强依赖。
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - 结果中能提供查询入口和企业名称。
  - 如果页面不可机器读取，返回“需人工核验”的证据项。
  - 不绕过验证码。
- **Validation**:
  - 单元测试覆盖不可自动读取时的降级结果。

### Task 6.5: 信用中国/地方信用站点补证

- **Location**:
  - `D:\audit-agent\app\infrastructure\credit_china_provider.py`
- **Description**: 对信用中国及地方信用站点做轻量补证规划，主要用于行政许可、处罚、公示信息。首版不要做全量爬取，只做配置化入口和可访问页面摘要。
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - 证据中标明来源是国家/地方信用站点。
  - 站点结构不支持时不影响主流程。
- **Validation**:
  - fake HTML 解析测试。

### Task 6.6: 搜索结果摘要补证

- **Location**:
  - `D:\audit-agent\app\infrastructure\search_evidence_provider.py`
- **Description**: 在没有付费 API 的前提下，如果使用搜索结果，只把它作为低可信补充证据。可以先设计接口和 mock，不在生产默认开启。
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - 搜索摘要证据 `trust_level=low`。
  - 不能单独触发自动通过。
  - 必须保存搜索关键词、摘要、来源链接。
- **Validation**:
  - 决策测试：只有低可信搜索摘要时进入人工复核。

### Task 6.7: 证据可信度和决策门槛

- **Location**:
  - `D:\audit-agent\app\domain\models.py`
  - `D:\audit-agent\app\services\evidence_service.py`
  - `D:\audit-agent\app\domain\decisions.py`
- **Description**: 增加证据可信度：`high`、`medium`、`low`。自动通过必须至少有一个 medium/high 证据源支持。
- **Dependencies**: Task 6.2
- **Acceptance Criteria**:
  - 官网业务文本可为 medium/high。
  - ICP 只作为主体一致性，不单独支持分类。
  - 搜索摘要为 low，不单独自动通过。
- **Validation**:
  - 决策单元测试覆盖不同证据组合。

## Sprint 7: 评估体系和可观测性增强

**Goal**: 让项目能持续知道质量是否变好、错误集中在哪里、真实运行是否稳定。

**Demo/Validation**:

- eval 能输出分场景准确率。
- metrics 能统计证据来源成功率。
- trace 能定位每条 case 的耗时和失败原因。

### Task 7.1: 扩展 golden cases 标签

- **Location**:
  - `D:\audit-agent\evals\golden_cases.json`
  - `D:\audit-agent\scripts\run_eval.py`
- **Description**: 给每条 golden case 增加标签：行业、证据类型、期望动作、失败类型、多分类、官网失败等。
- **Dependencies**: 无
- **Acceptance Criteria**:
  - eval 输出总体 accuracy 和分标签 accuracy。
  - 低于阈值时显示最差标签。
- **Validation**:
  - integration test 覆盖标签统计。

### Task 7.2: 增加真实失败样例集

- **Location**:
  - `D:\audit-agent\evals\`
- **Description**: 建立专门集合：
  - 官网 403/502/timeout。
  - SSL 失败。
  - 官网可访问但无业务文本。
  - LLM 返回非法 JSON。
  - LLM 候选规则外输出。
  - 员工多细分分类。
- **Dependencies**: 无
- **Acceptance Criteria**:
  - 每类至少 5 条样例。
  - 每类都有期望动作。
- **Validation**:
  - `run_eval.py` 新增 `--suite failure_modes`。

### Task 7.3: 证据源指标

- **Location**:
  - `D:\audit-agent\app\observability\metrics.py`
  - `D:\audit-agent\app\agents\evidence_agent.py`
- **Description**: 增加每个证据源的成功率、失败率、平均耗时、超时次数。
- **Dependencies**: Sprint 6
- **Acceptance Criteria**:
  - 指标包括 `website_success_rate`、`icp_success_rate`、`public_credit_success_rate`。
  - metrics 输出不包含敏感证据全文。
- **Validation**:
  - metrics 单元测试。

### Task 7.4: 结构化 trace 输出

- **Location**:
  - `D:\audit-agent\app\observability\trace.py`
  - `D:\audit-agent\app\workflow\nodes.py`
- **Description**: TraceEvent 增加结构化字段：`case_id`、`batch_id`、`agent_name`、`error_code`、`stage`。
- **Dependencies**: 无
- **Acceptance Criteria**:
  - 单条 case 能串起 evidence/rule/classification/risk/decision。
  - trace 查询可以按 case_id 返回完整链路。
- **Validation**:
  - trace 单元测试和 API 测试。

### Task 7.5: CI 质量门槛增强

- **Location**:
  - `D:\audit-agent\.github\workflows\ci.yml`
  - `D:\audit-agent\pyproject.toml`
- **Description**: 在不改部署的前提下，增强代码质量门槛。
- **Dependencies**: 无
- **Acceptance Criteria**:
  - 增加 coverage 阈值，例如 80%。
  - 增加 secret scanning 或至少检查 `.env` 不进入提交。
  - 增加 eval 分 suite 执行。
- **Validation**:
  - CI 本地命令可运行。

## Testing Strategy

- **单元测试**：
  - 权限校验。
  - batch job 状态机。
  - 复核事务和 Excel dirty 标记。
  - migration。
  - evidence aggregator。
  - 免费证据源 fake HTML 解析。
  - 证据可信度决策门槛。

- **集成测试**：
  - 认证上传、查询、下载、复核全链路。
  - 跨租户访问隔离。
  - 复核后下载 Excel 一致性。
  - 后台任务完成后查询状态。

- **E2E 测试**：
  - 上传真实模板。
  - 等待 batch succeeded。
  - 查看决策和复核任务。
  - 提交复核。
  - 下载 Excel 并检查人工结论。

- **评估测试**：
  - `golden_cases` 总体准确率。
  - `failure_modes` 分场景准确率。
  - 规则召回率。
  - 证据源成功率。

## Potential Risks & Gotchas

- **认证会影响现有测试**  
  缓解：测试中注入 fake user；未认证场景单独测；本地开发可用 `DEV_AUTH_ENABLED=false`，但默认安全。

- **异步任务会让测试变复杂**  
  缓解：保留同步执行函数，API 走异步，测试可直接调用 service 或轮询状态。

- **SQLite 并发能力有限**  
  缓解：本计划暂不要求改部署和数据库类型，但 repository 接口要为未来 PostgreSQL 留出口。

- **免费公共证据源不稳定**  
  缓解：全部 provider 可失败、可降级、可缓存；不把单个免费来源作为硬依赖。

- **公共网站可能有验证码或访问限制**  
  缓解：不绕过验证码；不可自动采集时转为“人工核验证据链接”。

- **低可信搜索摘要可能误导自动审批**  
  缓解：搜索摘要只作为 low trust，不能单独自动通过。

- **结果文件动态生成可能变慢**  
  缓解：dirty 标记 + 缓存生成文件；复核后只重建受影响 batch。

## Rollback Plan

- Sprint 1 认证可以通过测试配置关闭，但生产默认开启。
- Sprint 2 异步化保留同步 service，出现问题时临时切回同步执行。
- Sprint 3 Excel 动态生成可回滚为固定文件，但必须保留 API 一致性测试。
- Sprint 4 migration 每个版本独立，失败时可回滚到上一 schema 版本。
- Sprint 6 免费证据源全部通过配置开关控制，任何来源不稳定都能单独关闭。
- Sprint 7 指标和 eval 增强不影响主流程，可独立回滚。

## Suggested Implementation Order

1. 先做 Sprint 3：人工复核后 Excel 一致性，收益最大且风险可控。
2. 做 Sprint 1：认证、角色、租户边界，这是企业级上线硬门槛。
3. 做 Sprint 2：异步任务化，让系统能承载真实批量。
4. 做 Sprint 4：数据库迁移和结构化字段，为权限、审计、查询打基础。
5. 做 Sprint 5：文件和敏感数据治理。
6. 做 Sprint 6：免费证据源增强，但默认先保守开启。
7. 做 Sprint 7：评估和可观测性，把质量持续固化。

## Final Acceptance Criteria

- 未认证用户不能上传、查询、下载、复核。
- 不同租户之间不能互相查看 batch、case、review_task、result file。
- 上传接口不再长时间阻塞完整 Agent 工作流。
- batch 有明确状态和进度。
- 人工复核后，API 和下载 Excel 保持一致。
- 关键业务数据有结构化字段、迁移版本、索引和审计日志。
- 上传文件和结果文件有校验、访问审计和保留策略。
- 官网失败时可以尝试免费证据源补证，但不依赖付费 API。
- 低可信证据不会单独触发自动通过。
- eval 能按失败类型和证据来源输出质量指标。

## References

- 工信部 ICP/IP 地址/域名信息备案管理系统：`https://beian.miit.gov.cn/`
- 国家企业信用信息公示系统：国家市场监督管理总局主办的经营主体信用信息公示和查询服务。
- 信用中国及地方信用平台：用于公开信用信息、公示信息、行政许可和行政处罚等补充证据。

