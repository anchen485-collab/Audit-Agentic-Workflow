# Evals

`golden_cases.json` 用于保存正式评测集。当前 `scripts/run_eval.py` 会在该文件不存在时回退到
`tests/fixtures/sample_cases.json`，方便本地开发阶段持续运行评测。

默认运行方式会读取 `.env`，使用真实业务流程：

- `COMPANY_PROVIDER=website` 时使用官网爬虫采集证据。
- `LLM_ENABLED=true` 时使用真实 LLM provider 做语义判断。
- 规则召回、Risk Agent、Decision Agent 和 Review Task 生成都走完整 workflow。

```powershell
python scripts/run_eval.py --min-accuracy 0.8
```

真实流程评测会产生官网访问和真实 LLM API 调用，评测结果会受到官网可访问性、页面质量、模型稳定性、
接口超时和网络状态影响。因此 `golden_cases.json` 中的官网 URL 应该使用真实可访问官网，不能使用
`*.example.com` 这类 mock URL。脚本会在真实流程模式下主动拒绝 mock 官网 URL，避免生成误导性的
真实业务准确率。

如果只需要做离线稳定回归，可以显式使用 mock 模式：

```powershell
python scripts/run_eval.py --mock --min-accuracy 0.8
```

`--mock` 会使用 `data/evidence/mock_company_evidence.json` 和 mock classification provider，不代表真实业务
链路效果，只适合快速检查代码回归。

也可以直接使用真实员工录入 Excel 作为评测输入：

```powershell
python scripts/run_eval.py --excel-file "C:\Users\Administrator\Desktop\document\test.xlsx" --min-accuracy 0.8
```

Excel 必须包含审批上传所需表头：`日期`、`姓名`、`一级分类`、`细分`、`企业名称&官网`。如果要计算准确率，
还需要额外增加标准答案列，列名可以是：

- `expected_action`
- `期望动作`
- `标准答案`
- `人工标注动作`

标准答案值使用最终审批动作英文枚举：

- `approved`
- `rejected`
- `needs_more_evidence`
- `needs_human_review`

真实流程统计准确率时，官网无法访问、缺少官网 URL 这类外部证据不可用样本会被排除出准确率分母，并记录到：

- `accuracy_excluded_count`
- `accuracy_eligible_count`

没有标准答案列时，脚本仍会跑完整真实流程并输出自动处理率、人工复核率、证据不可用数量等运行指标，但不会输出
有业务含义的 `accuracy`。
