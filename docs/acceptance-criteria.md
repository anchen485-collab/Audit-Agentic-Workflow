# 首版验收标准

## 1. 功能闭环

- 能上传 Excel。
- 能解析员工录入记录。
- 能生成标准审批单。
- 能获取 mock 企业证据。
- 能召回内部分类规则。
- 能输出四类审批动作。
- 能导出结果 Excel。

## 2. 四类审批动作

- approved：高置信、低风险、证据支持。
- rejected：证据明确不支持，并能给出建议。
- needs_more_evidence：外部证据不足。
- needs_human_review：低置信、冲突、高风险或模型异常。

## 3. 质量指标

- sample_case_count >= 10。
- 首版 golden_case_count >= 30。
- accuracy >= 80%。
- e2e_pass_rate = 100%。
- LLM 失败不能导致整批 batch 失败。

## 4. 工程验收

- `python -m pytest` 通过。
- `ruff check .` 通过。
- `python scripts/demo_trace.py` 能展示完整链路。
- `python scripts/run_eval.py` 能输出指标。