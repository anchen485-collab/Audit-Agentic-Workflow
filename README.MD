# 企业录入审批 Agent

这是一个企业级录入审批 Agent，用于审核员工在 Excel 中录入的企业分类是否合理。

系统会结合员工录入、企业外部证据、内部分类规则和 LLM 语义判断，将记录分流为：

- 自动通过
- 自动驳回
- 证据不足
- 人工复核

## 架构

核心工作流基于 LangGraph 编排：

```text
Evidence Agent
  -> Rule Agent
  -> Classification Agent
  -> Risk Agent
  -> Decision Agent
  -> Explanation Agent
  -> Review / Metrics
```

每个 Agent 都输出 `AgentAssessment`，用于记录执行状态、置信度、发现信息、结构化结果和耗时。

## 本地开发

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
uvicorn app.api.app:app --reload
```

## 常用命令

```powershell
python scripts/run_eval.py
python scripts/demo_trace.py
```

## API

- `POST /api/audit/upload`：上传 Excel 并执行审批。
- `GET /api/audit/batches`：查询最近批次。
- `GET /api/audit/batches/{batch_id}`：查询单个批次。
- `GET /api/audit/batches/{batch_id}/result`：下载结果 Excel。
- `GET /api/review/tasks`：查询人工复核任务。
- `POST /api/review/tasks/{task_id}/decision`：提交人工复核结论。

## 当前评测结果

基于 10 条标准样例：

- 准确率：100%
- 自动处理率：60%
- 人工复核率：40%
- 每批 AgentAssessment：60 条

## Docker

```powershell
docker build -t audit-agent .
docker compose up
```

## 补充说明

- FastAPI 启动入口统一使用 `uvicorn app.api.app:app --reload`。
- Docker 启动入口同样使用 `app.api.app:app`，不再额外新增 `app/main.py`。
- `docker compose up` 默认读取 `.env`，`.env.example` 仅作为配置模板。
- 评测集默认使用 `evals/golden_cases.json`，当前 golden cases 数量为 30 条，最低准确率门槛为 80%。
- 批次明细可通过 `/api/audit/batches/{batch_id}/cases`、`/api/audit/batches/{batch_id}/decisions`、`/api/audit/batches/{batch_id}/assessments` 查询。
