# 企业录入审批 Agent

[![CI](https://github.com/anchen485-collab/new-audit-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/anchen485-collab/new-audit-agent/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-1C3C3C)](https://langchain-ai.github.io/langgraph/)

> **基于实习期间参与的企业分类录入审批业务复刻的 Agent 项目。**
> 项目对真实业务流程进行了脱敏与独立实现：将 Excel 批量录入、企业官网证据、内部分类规则、LLM 语义判断与人工复核串成一条**可解释、可追溯、可恢复**的审批链路。

---

## 为什么做这个项目

企业信息录入的分类审核，往往依赖人工逐条核对官网、比对内部规则，再给出通过、驳回或补充材料的结论。

- **效率低**：批量 Excel 待审核时，低风险记录也会占用人工时间；
- **标准不一**：不同审核员对同一企业的理解可能不同；
- **难追溯**：审核结论缺少证据、规则和决策过程，复盘成本很高。

本项目把审批过程拆解为多个职责明确的 Agent 节点：让模型负责语义理解，让确定性代码负责边界、风控和最终动作，把不确定记录交给人工。

## 核心亮点

| 亮点 | 实现方式 | 业务价值 |
| --- | --- | --- |
| **Workflow 驱动，而非模型自由决策** | LangGraph 编排固定审批主链路；LLM 仅输出语义判断 | 流程稳定、可测试，避免“模型说通过就通过” |
| **自动审批双重校验** | Decision Agent 先决策，Decision Verifier 再校验证据、规则、风险、置信度与分类候选 | 不满足硬条件的自动通过/驳回会降级到人工复核 |
| **二级/三级分类粒度识别** | Rule Agent 识别员工填写的是二级、三级、混合或歧义分类，动态召回 Top-K 候选 | 避免分类粒度不一致带来的误判 |
| **真实官网证据链** | 支持本地 Mock 和官网抓取；抓取首页及高价值业务子页，保留来源 URL 与证据片段 | 每条结论都有可回看的业务依据 |
| **单条重试可靠性设计** | 幂等键、同 Case 互斥锁、超时锁释放、Trace、重试审计与结果回放 | 重试不会重复调用外部服务，也不会覆盖已完成的人审结论 |
| **可观测与可评测** | AgentAssessment、TraceEvent、SQLite 持久化、结果 Excel、golden cases | 可定位“哪一环慢、哪一环错、为什么转人工” |

## 审批工作流

~~~mermaid
flowchart TD
    A[上传 Excel] --> B[解析并标准化 AuditCase]
    B --> C[Evidence Agent<br/>采集企业证据]
    B --> D[Rule Agent<br/>召回分类候选]
    C --> E[Classification Agent<br/>语义判断]
    D --> E
    E --> F[Risk Agent<br/>风险分层]
    F --> G[Decision Agent<br/>确定性决策]
    G --> H[Decision Verifier<br/>自动审批校验]
    H --> I[Explanation Agent<br/>生成可读说明]
    I --> J[创建人工复核任务]
    J --> K[指标、Trace、SQLite、结果 Excel]
    H -->|校验未通过| L[转人工复核]
    K --> M[自动通过 / 自动驳回 / 证据不足 / 人工复核]
~~~

### 七个核心 Agent 节点

| 节点 | 职责 |
| --- | --- |
| Evidence Agent | 采集企业官网或 Mock 证据，生成证据质量分和可引用片段 |
| Rule Agent | 检查员工录入路径，识别细分类目粒度，召回候选规则 |
| Classification Agent | 判断“支持 / 冲突 / 证据不足 / 不确定” |
| Risk Agent | 综合证据质量、规则命中与语义结果进行风险分层 |
| Decision Agent | 使用确定性规则输出初步审批动作 |
| Decision Verifier | 为自动通过、自动驳回追加硬性校验；失败即降级人工复核 |
| Explanation Agent | 为审核员和录入员工生成结构化、可读的结论说明 |

## 四类审批结果

| 动作 | 触发条件 | 后续处理 |
| --- | --- | --- |
| **自动通过** | 证据充分、规则命中、语义支持、低风险，并通过 Verifier | 直接完成 |
| **自动驳回** | 证据充分、语义明确冲突，且建议分类来自规则候选集 | 返回修正建议 |
| **证据不足** | 官网缺失、访问失败、内容为空或质量不足 | 补充官网或业务材料 |
| **人工复核** | 分类不存在、粒度异常、低置信度、风险较高、LLM 异常或 Verifier 拦截 | 创建 Review Task |

## 技术架构

~~~text
app/
├── agents/          # 各 Agent 的单条审批逻辑与统一异常兜底
├── api/             # FastAPI 路由、依赖注入、鉴权与响应模型
├── domain/          # AuditCase、EvidencePackage、ApprovalDecision 等领域模型
├── infrastructure/  # Excel、SQLite、官网抓取、LLM Client、配置
├── observability/   # 日志、Trace、指标
├── services/        # 批次管理、规则召回、结果导出、单 Case 重试
├── static/          # 审批工作台前端
└── workflow/        # LangGraph State、Node 与 Graph 编排

data/                # Mock 证据、规则库、Excel 上传模板
evals/               # Golden cases 与真实评测样例
tests/               # 单元、集成、端到端测试
~~~

## 快速开始

### 本地运行

> 推荐 Python 3.11 与 PowerShell。

~~~powershell
git clone https://github.com/anchen485-collab/new-audit-agent.git
cd new-audit-agent

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

Copy-Item .env.example .env
uvicorn app.api.app:app --reload
~~~

启动后访问：

- 审批工作台：http://127.0.0.1:8000
- OpenAPI 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/health

### Docker 运行

~~~powershell
Copy-Item .env.example .env
docker compose up --build
~~~

## 输入格式

上传模板在 **data/templates/audit_upload_template.xlsx**。

| 日期 | 姓名 | 一级分类 | 细分 | 企业名称&官网 |
| --- | --- | --- | --- | --- |

“企业名称&官网”支持直接填写 URL，也支持 Excel 单元格超链接。

## 配置说明

默认使用本地 Mock，开箱即可完成全流程演示：

~~~dotenv
COMPANY_PROVIDER=mock
LLM_ENABLED=false
AUTH_ENABLED=false
~~~

如需接入真实官网和兼容 OpenAI Chat Completions 的模型：

~~~dotenv
COMPANY_PROVIDER=website

LLM_ENABLED=true
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://your-provider/v1
LLM_MODEL=your_model
~~~

> 真实 LLM 的输出会经过 JSON Schema、候选分类、路径合法性和 Decision Verifier 校验；模型不拥有最终审批权。

## API 一览

| 方法 | 接口 | 说明 |
| --- | --- | --- |
| POST | /api/audit/upload | 上传 Excel 并执行整批审批 |
| GET | /api/audit/batches | 查询最近审批批次 |
| GET | /api/audit/batches/{batch_id} | 查询批次摘要 |
| GET | /api/audit/batches/{batch_id}/cases | 查询审批单明细 |
| GET | /api/audit/batches/{batch_id}/decisions | 查询审批结论与错误摘要 |
| GET | /api/audit/batches/{batch_id}/assessments | 查询 Agent 执行轨迹 |
| GET | /api/audit/batches/{batch_id}/result | 下载结果 Excel |
| POST | /api/audit/batches/{batch_id}/cases/{case_id}/retry | 使用 Idempotency-Key 幂等重试单条审批 |
| GET | /api/audit/batches/{batch_id}/cases/{case_id}/retry-attempts | 查询单条重试历史 |
| GET | /api/review/tasks | 查询待人工复核任务 |
| POST | /api/review/tasks/{task_id}/decision | 提交人工复核结论 |
| GET | /health/llm | 检查 LLM 配置与连通性 |

## 质量保障

~~~powershell
# 全量测试
python -m pytest

# 代码风格检查
python -m ruff check .

# 离线稳定回归：Mock 证据 + Mock 分类
python scripts/run_eval.py --mock --min-accuracy 0.8

# 查看完整 Agent Trace
python scripts/demo_trace.py
~~~

评测不仅关注最终审批动作，也记录自动处理率、人工复核率、证据不足率、LLM 失败统计、节点耗时与 AgentAssessment 数量。

## 设计取舍

### 为什么不让 LLM 直接输出“通过”或“驳回”？

~~~text
LLM：理解企业业务与分类语义
代码：校验边界、计算风险、决定最终动作、执行持久化
人工：处理证据不足、冲突和高风险记录
~~~

这样既具备 LLM 的语义理解能力，也保留企业审批所需的确定性和审计能力。

### 为什么是固定 Workflow，而不是自由规划的 Agent？

企业分类审批的主链路高度稳定，适合用显式 Workflow 约束；真正不确定的部分只有“企业业务是否支持该分类”，才交给 LLM。这样的 Agentic Workflow 更容易测试、回放和优化。

## 可用于面试的项目总结

> 我基于实习中接触的企业分类录入审批业务，独立复刻了一个可落地的审批 Agent。系统通过 LangGraph 将 Excel 解析、官网证据采集、规则召回、LLM 语义判断、风险分层和人工复核编排成固定工作流；其中 LLM 只负责语义判断，最终审批由确定性规则和 Decision Verifier 双重把关。为处理真实业务中的失败重试问题，我还实现了单条审批的幂等重试、互斥锁、超时恢复与审计追踪，使每条记录都能复盘“依据了什么证据、命中了什么规则、为什么得到这个结论”。

## 后续迭代方向

- 将官网抓取升级为多来源、带可信度等级的企业证据系统；
- 引入批次级 checkpoint 与异步任务队列，支持断点恢复；
- 扩充真实标注评测集，持续监控自动审批精确率和人工复核召回率；
- 对接企业统一身份认证与更细粒度的权限策略。
