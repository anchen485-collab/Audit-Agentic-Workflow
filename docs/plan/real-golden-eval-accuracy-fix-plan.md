# Real Golden Eval Accuracy Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于 `evals/real_golden_cases_2026_08_03.xlsx` 的 45 条人工 confirmed answer，把真实流程准确率从当前 86.67% 稳定提升，并减少 LLM 超时导致的误转人工。

**Architecture:** 保持现有多 Agent 流程不变，在 Rule Agent、Classification Agent、Decision Agent 的确定性边界增加保护。LLM 仍只做语义判断，不直接输出最终 action；代码负责证据充分性、规则合法性、风险和最终 action。

**Tech Stack:** Python 3.11, Pydantic, FastAPI, pytest, openpyxl, httpx, LangGraph workflow.

---

## Current Baseline

真实 golden eval answer：

- `D:/audit-agent/evals/real_golden_cases_2026_08_03.xlsx`
- 样本数：45
- 当前准确率：86.67%
- 当前自动处理率：55.56%
- 当前人工复核率：44.44%
- 错例数：6

错例分组：

- `eval_excel_row_4`：目标企业和官网证据企业不一致，本应 `needs_more_evidence`，但 LLM 超时后兜底成 `needs_human_review`。
- `eval_excel_row_6`、`eval_excel_row_33`、`eval_excel_row_36`：证据支持录入分类，但 LLM 超时或输出不完整，系统兜底转人工。
- `eval_excel_row_10`：员工一级分类为 `种植业,畜牧业`，细分为 `水果作物,家畜`，规则召回按整个一级字符串匹配，导致误判规则不存在。
- `eval_excel_row_46`：肥料企业官网提到产品适用于果树、蔬菜，LLM 按服务对象误判为支持 `水果作物,蔬菜作物`。

## Files

- Modify: `D:/audit-agent/app/services/rule_retriever.py`
  - 支持员工一级分类多值拆分，让 `种植业,畜牧业` 能分别匹配 `水果作物` 和 `家畜`。
- Modify: `D:/audit-agent/app/agents/classification_agent.py`
  - 增加目标企业一致性判断。
  - 增加“农资/肥料服务对象不等于作物主营分类”的保护。
  - 在 LLM 异常时优先使用确定性规则兜底，减少超时导致的误转人工。
- Modify: `D:/audit-agent/app/agents/llm_classification_provider.py`
  - 给 LLM 调用增加有限重试。
  - 强化 prompt：服务对象不能直接等于主营分类。
- Test: `D:/audit-agent/tests/unit/test_rule_retriever.py`
  - 覆盖多一级分类 + 多二级细分召回。
- Test: `D:/audit-agent/tests/unit/test_classification_agent.py`
  - 覆盖目标企业不一致。
  - 覆盖肥料服务对象误通过保护。
  - 覆盖 LLM provider 抛异常后确定性兜底。
- Test: `D:/audit-agent/tests/unit/test_llm_classification_provider.py`
  - 覆盖 LLM read timeout 后重试成功。

## Task 1: Fix Multi-Level1 Rule Recall

- [ ] **Step 1: Write failing test**

Add a test showing that `entered_level1="种植业,畜牧业"` and `entered_subcategory="水果作物,家畜"` should produce two level2 category candidates.

- [ ] **Step 2: Verify test fails**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_rule_retriever.py -q
```

Expected before implementation: the new test fails because current code normalizes the whole `种植业,畜牧业` string as one level1 key.

- [ ] **Step 3: Implement minimal fix**

Add a small helper to split `entered_level1` by comma and try each level1 key for every entered subcategory.

- [ ] **Step 4: Verify**

Run the same test file and confirm pass.

## Task 2: Detect Target Company Evidence Mismatch

- [ ] **Step 1: Write failing test**

Create a case where `audit_case.company_name="普洱淞茂谷林下中药材开发有限公司"` but evidence text repeatedly contains `江西大道农业发展有限公司` and not the target company. Expected semantic result: `insufficient_evidence`.

- [ ] **Step 2: Verify test fails**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_classification_agent.py -q
```

- [ ] **Step 3: Implement minimal fix**

Before calling LLM, if evidence text does not mention the target company but mentions another company-like name from the snippets, return insufficient evidence with reason `官网证据与目标企业不一致`。

- [ ] **Step 4: Verify**

Run classification tests.

## Task 3: Prevent Service-Object False Approval

- [ ] **Step 1: Write failing test**

Create a case where evidence says the company produces `有机肥/水溶肥/肥料` and products apply to `果树、蔬菜`, while employee input is `水果作物,蔬菜作物`. Expected semantic result: `uncertain`, so final action becomes `needs_human_review`.

- [ ] **Step 2: Verify test fails**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_classification_agent.py -q
```

- [ ] **Step 3: Implement minimal fix**

Before accepting provider `supports_entered_category`, detect fertilizer/agricultural-input provider evidence. If employee entered crop categories and evidence only describes service targets, downgrade to `uncertain`.

- [ ] **Step 4: Verify**

Run classification tests.

## Task 4: Add LLM Retry

- [ ] **Step 1: Write failing test**

Create fake `http_post` that raises `httpx.ReadTimeout` once and succeeds on the second call. Expected: provider returns parsed result and call count is 2.

- [ ] **Step 2: Verify test fails**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_llm_classification_provider.py -q
```

- [ ] **Step 3: Implement minimal fix**

Add `max_retries=2` to `OpenAICompatibleClassificationProvider` and retry `httpx.TimeoutException` / `httpx.NetworkError` with logging.

- [ ] **Step 4: Verify**

Run LLM provider tests.

## Task 5: Use Deterministic Fallback on LLM Exception

- [ ] **Step 1: Write failing test**

Create provider that raises `TimeoutError` for a clearly supported approved case. Expected ClassificationAgent returns `supports_entered_category` from deterministic fallback instead of `uncertain`.

- [ ] **Step 2: Verify test fails**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_classification_agent.py -q
```

- [ ] **Step 3: Implement minimal fix**

Change ClassificationAgent fallback from unconditional `uncertain` to a deterministic fallback using `classify_audit_case()` only when evidence is sufficient and entered path exists. Keep high-risk/unknown cases as human review.

- [ ] **Step 4: Verify**

Run classification tests.

## Task 6: Full Verification

- [ ] Run static checks:

```powershell
.venv\Scripts\python.exe -m ruff check .
```

- [ ] Run full test suite:

```powershell
.venv\Scripts\python.exe -m pytest -q
```

- [ ] Run real golden eval:

```powershell
.venv\Scripts\python.exe scripts\run_eval.py --excel-file D:\audit-agent\evals\real_golden_cases_2026_08_03.xlsx --min-accuracy 0.8
```

Expected target:

- accuracy >= 0.90
- LLM timeout caused mismatches decrease
- `eval_excel_row_46` no longer auto-approves fertilizer service-object sample

