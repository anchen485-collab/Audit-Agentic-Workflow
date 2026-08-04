# Plan: 真实 Excel 上传审批闭环

**Generated**: 2026-07-29
**Estimated Complexity**: Medium

## Overview

本计划目标是让系统支持上传真实员工 Excel 后完成自动审批，并下载包含审批结论、证据和人工复核信息的结果 Excel。当前 demo 链路已跑通，但真实使用还需要补齐规则 Excel 转 JSON、真实 evidence provider 接入、行级容错、结果导出增强和验证用例。

## Prerequisites

- `.env` 已由用户配置完成。
- 内部分类规则 Excel 已存在：`C:\Users\Administrator\Desktop\document\最终分类表.xlsx`。
- 项目运行目录：`D:\audit-agent`。
- 依赖已包含 `openpyxl`、`httpx`、`fastapi`、`langgraph`、`pydantic`。

## Sprint 1: 规则 Excel 转 JSON

**Goal**: 将内部分类规则 Excel 转换为系统可加载的 `data/rules/category_rules.json`。

**Demo/Validation**:
- 执行转换脚本后生成 JSON。
- `load_category_rules("data/rules/category_rules.json")` 可以正常加载。
- 转换后的规则数量明显大于 demo 规则数量。

### Task 1.1: 新增规则转换脚本

- **Location**: `scripts/convert_category_rules.py`
- **Description**: 读取 `一级品类`、`二级品类`、`三级品类`、`模块名称`、`子模块列表`，对空白分类字段做向下填充，拆分关键词后写入 JSON。
- **Dependencies**: 无。
- **Acceptance Criteria**:
  - 支持默认输入路径和自定义输入路径。
  - 支持默认输出到 `data/rules/category_rules.json`。
  - 跳过缺少必要分类字段的空行。
  - 每条输出符合 `CategoryRule` 模型。
- **Validation**:
  - 新增单元测试覆盖 fill-forward 和关键词拆分。
  - 运行脚本并加载 JSON。

### Task 1.2: 用真实规则 Excel 生成 JSON

- **Location**: `data/rules/category_rules.json`
- **Description**: 使用桌面规则 Excel 生成正式 JSON，替换 demo 规则。
- **Dependencies**: Task 1.1。
- **Acceptance Criteria**:
  - JSON 文件是合法 UTF-8。
  - 顶层是列表。
  - 每条包含 `level1`、`level2`、`level3`、`module`、`keywords`。
- **Validation**:
  - 执行 `python scripts/convert_category_rules.py`。
  - 执行规则加载测试。

## Sprint 2: 真实 Evidence Provider 接入

**Goal**: 上传真实 Excel 时可以通过配置选择 mock 或官网证据 provider。

**Demo/Validation**:
- `.env` 设置 `COMPANY_PROVIDER=website` 后，上传接口使用官网爬虫 provider。
- `.env` 设置 `COMPANY_PROVIDER=mock` 后，仍使用 mock provider，保证测试稳定。

### Task 2.1: 修改 provider 依赖注入

- **Location**: `app/api/dependencies.py`
- **Description**: 根据 `settings.company_provider` 返回 `MockCompanyEvidenceProvider` 或 `WebsiteCompanyProvider`。
- **Dependencies**: 无。
- **Acceptance Criteria**:
  - 支持 `mock`。
  - 支持 `website`。
  - 不支持的值抛出清晰错误。
- **Validation**:
  - 新增依赖测试。

### Task 2.2: 补充官网 provider 真实使用测试

- **Location**: `tests/unit/test_api_dependencies.py`
- **Description**: 验证不同配置下 provider 类型正确。
- **Dependencies**: Task 2.1。
- **Acceptance Criteria**:
  - mock 模式返回 mock provider。
  - website 模式返回 website provider。

## Sprint 3: 真实上传容错增强

**Goal**: 真实 Excel 中某一行有问题时，不让整个批次直接失败。

**Demo/Validation**:
- 上传包含一条缺字段的 Excel，系统仍能处理其他行。
- 错误行在结果中标记为人工复核或数据错误。

### Task 3.1: 行级错误结果模型

- **Location**: `app/services/case_service.py`、`app/api/routes.py`
- **Description**: 将创建 `AuditCase` 的批处理从“遇错即失败”改成“收集错误并继续处理”。
- **Dependencies**: 无。
- **Acceptance Criteria**:
  - 有效行继续进入审批流程。
  - 无效行不导致整个上传接口失败。
  - 上传响应或结果 Excel 能看到错误行原因。
- **Validation**:
  - 新增 API 测试，覆盖部分坏行。

## Sprint 4: 结果 Excel 增强

**Goal**: 下载结果 Excel 时能看到证据来源、证据质量和证据片段，方便人工复核。

**Demo/Validation**:
- 结果 Excel 的“审批明细”新增 evidence 字段。

### Task 4.1: 导出证据信息

- **Location**: `app/infrastructure/excel_writer.py`、`app/services/result_file_service.py`、`app/api/routes.py`
- **Description**: 将 `evidence_packages` 传入结果导出方法，在审批明细中增加证据来源、证据质量分、证据片段和采集错误。
- **Dependencies**: Sprint 2。
- **Acceptance Criteria**:
  - 结果 Excel 包含 evidence columns。
  - 旧测试兼容，不传 evidence 时仍可导出。
- **Validation**:
  - 更新 Excel writer 测试。
  - 上传后下载结果文件检查表头。

## Sprint 5: 工作流效率优化

**Goal**: 将规则召回和证据采集改成并行前置节点。

**Demo/Validation**:
- 工作流仍能通过所有测试。
- `evidence_agent` 和 `rule_agent` 都从 START 出发，`classification_agent` 汇合。

### Task 5.1: LangGraph fan-out / fan-in

- **Location**: `app/workflow/graph.py`、`app/workflow/state.py`
- **Description**: 调整 graph 边关系，并确认 `trace_events`、`assessments` reducer 能正确合并并行节点输出。
- **Dependencies**: Sprint 1 至 Sprint 4。
- **Acceptance Criteria**:
  - 规则召回和证据采集无依赖串行关系。
  - assessment 不丢失。
  - trace event 不丢失。
- **Validation**:
  - 更新 workflow 测试。
  - 跑全量 pytest。

## Testing Strategy

- 单元测试：
  - 规则 Excel 转 JSON。
  - provider 依赖注入。
  - Excel writer evidence 字段。
  - workflow assessment 合并。
- 集成测试：
  - 上传真实结构 Excel。
  - 下载结果 Excel。
  - 查询复核任务。
- 手动验证：
  - Swagger 上传自己的 Excel。
  - 下载结果 Excel，检查审批明细、人员汇总、人工复核任务。

## Potential Risks & Gotchas

- 规则 Excel 存在大量合并单元格或空白单元格，需要 fill-forward。
- 真实官网可能打不开，不能因为官网失败导致整个批次失败。
- 用户 Excel 表头必须满足当前要求，否则需要先提供模板或支持表头别名。
- 真实 LLM 输出可能不是合法 JSON，必须保留 fallback。
- 并行节点写入同一个 state key 时必须依赖 reducer 合并。

## Rollback Plan

- 如果真实规则 JSON 影响 demo 测试，可将原 demo JSON 备份为 `data/rules/category_rules.demo.json`。
- 如果 website provider 不稳定，可通过 `.env` 切回 `COMPANY_PROVIDER=mock`。
- 如果并行 workflow 出现 state 合并问题，可回退为串行边关系。
