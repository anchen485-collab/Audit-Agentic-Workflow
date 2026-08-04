# 旧审批 Agent 参考说明

## 1. 参考项目位置

旧项目位于：

```text
D:\audit
```

新项目位于：

```text
D:\audit-agent
```

旧项目只作为业务素材和实现思路参考，不直接复制代码。

## 2. 旧项目已有能力

根据 `D:\audit` 当前结构和文档，旧项目已经具备这些能力：

- FastAPI Web 页面上传 Excel。
- 员工录入 Excel 读取。
- 内部分类规则读取，并可从 Excel 生成 JSON 规则索引。
- LangGraph 审计流程编排。
- mock 企业信息 Provider。
- 企查查 Provider 预留。
- 官网爬虫 Provider。
- 规则打分和关键词匹配。
- 可选 LLM 分类 Agent。
- 审计结果 Excel 导出。
- 人员汇总统计。
- trace_id 和阶段耗时日志。
- 上传、规则、爬虫、trace、Excel 等测试。

## 3. 旧项目核心流程

旧项目的 LangGraph 流程大致是：

```text
read_employee
  -> read_category
  -> pipeline_audit
  -> build_summary
  -> export_result
```

其中 `pipeline_audit` 做了两件事：

- 并发爬取或查询企业信息。
- 基于规则或可选 LLM 做审计。

旧项目更像一条审计流水线，新项目要升级为职责更清晰的审批 Agent 工作流。

## 4. 值得参考的模块

### 4.1 Excel 读取

参考位置：

```text
D:\audit\app\excel\input_reader.py
D:\audit\tests\test_excel_reader.py
```

可参考点：

- 员工录入表头。
- 企业名称和官网 URL 的解析方式。
- 缺表头、空字段等异常测试。

新项目改进方向：

- 输出标准化 `AuditCase`。
- 把读取错误转成明确业务错误。
- 保持 Excel reader 只负责读取，不参与审批判断。

### 4.2 分类规则读取和索引

参考位置：

```text
D:\audit\app\excel\category_reader.py
D:\audit\app\category\rule_index.py
D:\audit\scripts\build_category_rules_json.py
```

可参考点：

- 内部分类表字段。
- 合并单元格处理。
- 从 Excel 生成 JSON 规则索引。

新项目改进方向：

- 首版先用 `category_rules.json` 固定规则样例。
- 后续再补 Excel 导入。
- 规则召回应输出 `CandidateRuleSet`，用于约束 LLM。

### 4.3 官网爬虫

参考位置：

```text
D:\audit\app\company\website_provider.py
D:\audit\app\company\website_crawler.py
D:\audit\tests\test_website_crawler.py
D:\audit\tests\test_website_crawler_depth.py
D:\audit\tests\test_hybrid_website_crawler.py
```

可参考点：

- 官网 URL 标准化。
- 只爬同域名页面。
- 优先抓取公司简介、经典案例、业务领域等高价值页面。
- 限制最大页数、最大深度、超时时间。
- requests 爬虫失败后可用 Crawl4AI 兜底。
- 中文乱码修复。
- 证据不足时返回失败原因。
- 缓存相同官网结果，减少重复请求。

新项目改进方向：

- 首版先用 `MockCompanyProvider`，不直接接真实爬虫。
- 第二版再实现 `WebsiteCompanyProvider`。
- 爬虫输出统一转成 `EvidencePackage`，包含 sources、snippets、quality_score、errors。
- 爬虫失败不能导致整批任务失败，只能让单条 case 进入证据不足。

### 4.4 规则打分

参考位置：

```text
D:\audit\app\audit\scoring.py
D:\audit\app\audit\rules.py
D:\audit\tests\test_scoring.py
D:\audit\tests\test_rules.py
```

可参考点：

- 分类命中得分。
- 细分命中得分。
- 经营范围关键词命中得分。
- 建议分类生成。
- 低置信度进入复核。

新项目改进方向：

- 不沿用长规则函数。
- 拆成 `RuleRetriever`、`RiskAgent`、`DecisionAgent`。
- 业务决策集中放在 `app/domain/decisions.py`。
- 每个规则都要能单独测试。

### 4.5 LLM 分类 Agent

参考位置：

```text
D:\audit\app\agent\classification_agent.py
D:\audit\tests\test_classification_agent.py
```

可参考点：

- OpenAI-compatible chat completions 调用方式。
- 通过环境变量开启 LLM。
- response_format 使用 JSON。
- 限制证据文本和分类文本长度。
- LLM 输出解析和置信度裁剪。

新项目改进方向：

- 增加默认 `MockLLMClient`，测试不访问网络。
- LLM 输出必须使用 Pydantic schema 校验。
- LLM 只能从候选规则中选择分类。
- LLM 不直接返回最终审批动作，只返回语义判断。
- LLM 异常统一降级为人工复核。

### 4.6 Trace 和日志

参考位置：

```text
D:\audit\app\core\trace.py
D:\audit\app\core\logging_config.py
D:\audit\tests\test_trace.py
D:\audit\tests\test_logging.py
```

可参考点：

- trace_id 串联一次上传。
- 记录 LangGraph 节点耗时。
- 记录官网爬取耗时。
- 记录分类 Agent 耗时。

新项目改进方向：

- trace 不只记录阶段耗时，还要记录每个 Agent 的输入摘要、输出摘要、错误和兜底动作。
- trace 要能支撑 `scripts/demo_trace.py`。
- trace 要能用于面试演示。

### 4.7 结果导出和人员汇总

参考位置：

```text
D:\audit\app\excel\result_writer.py
D:\audit\app\audit\summary.py
D:\audit\tests\test_result_writer.py
```

可参考点：

- 导出审计明细。
- 按人员汇总正确率、错误数、疑似错误数。
- Excel 结果着色。

新项目改进方向：

- 增加人工复核任务 Sheet。
- 增加 Agent trace 或证据摘要字段。
- 增加自动通过率、自动驳回率、人工复核率等质量指标。

## 5. 旧项目主要问题

### 5.1 职责边界不够清晰

旧项目把规则匹配、候选召回、LLM 调用、建议分类、状态判断混在较长的规则函数里。

新项目要拆成：

- EvidenceService
- RuleRetriever
- ClassificationAgent
- RiskAgent
- DecisionAgent
- ReviewService

### 5.2 决策结果不够企业级

旧项目主要输出：

- 正确
- 错误
- 疑似错误
- 无法判断
- 信息缺失

新项目要升级为审批动作：

- approved
- rejected
- needs_more_evidence
- needs_human_review

这样更贴近真实审批系统。

### 5.3 人工复核不是完整闭环

旧项目可以标记 `needs_review`，但没有完整人工复核 API 或页面。

新项目要支持：

- 生成复核任务。
- 查询复核任务。
- 提交人工结论。
- 人工结论覆盖 Agent 结论。
- 导出人工最终结论。

### 5.4 评测指标不足

旧项目有测试，但还缺少面向效果的评测集。

新项目要建立：

- 30+ golden cases。
- `scripts/run_eval.py`。
- 准确率。
- 自动通过率。
- 自动驳回率。
- 人工复核率。
- 证据不足率。
- LLM 失败率。
- 平均审批耗时。

### 5.5 LLM 边界需要更清楚

旧项目中 LLM 分类 Agent 已经有结构化输出，但新项目要进一步明确：

- LLM 只做语义判断。
- 最终审批动作由确定性代码决定。
- LLM 输出必须被 schema、候选分类和风险规则校验。

## 6. 新项目改进方向

新项目不是重写旧代码，而是重建业务 Agent。

核心改进：

- 从规则流水线升级为多 Agent 审批工作流。
- 从“能判断”升级为“能解释、能兜底、能复核”。
- 从“有测试”升级为“有评测指标”。
- 从“导出结果”升级为“输出质量统计和实习成果数字”。
- 从“可运行 demo”升级为“可部署、可回滚、可面试讲清楚”。

## 7. 后续复用策略

### 可以直接复用的业务事实

- Excel 表头。
- 内部分类表字段。
- 官网证据采集目标模块。
- 常见失败场景。
- 测试样例思路。

### 需要重新设计的工程结构

- 领域模型。
- Agent 输出模型。
- 审批动作枚举。
- LangGraph 状态。
- 人工复核闭环。
- 评测指标体系。

### 后续实现爬虫时的参考步骤

1. 先读旧项目 `website_crawler.py`。
2. 提炼官网 URL 标准化、同域限制、深度限制、目标页面发现、乱码修复、Crawl4AI 兜底等能力。
3. 在新项目中实现 `WebsiteCompanyProvider`。
4. 输出统一 `EvidencePackage`。
5. 写单元测试覆盖正常、403、404、证据不足、乱码、超时等场景。

## 8. 可写进实习成果的差异点

旧项目可以作为“已有原型”，新项目要体现 anan 的价值：

- 把原规则审计流水线重构为职责清晰的多 Agent 审批架构。
- 把不可控的大判断过程拆成证据、规则、语义、风险、决策、解释多个可测试节点。
- 引入人工复核闭环，避免高风险记录被自动误批。
- 建立 golden cases 和评测脚本，用数字证明审批效果。
- 输出 trace 和质量指标，让系统可观测、可演示、可复盘。

## 9. Day 1 总结口径

今天完成的理解：

> 旧项目已经验证了 Excel 读取、规则匹配、官网爬取、LangGraph 流水线和结果导出的可行性，但它更像一个规则审计原型。新项目要在此基础上从零重建为企业级审批 Agent，重点体现清晰领域模型、多 Agent 分工、LLM 边界控制、人工复核兜底、评测指标和可部署交付。

后续原则：

> 参考旧项目的业务经验，不复制旧项目的工程混乱。
