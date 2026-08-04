# 测试策略

## 单元测试

覆盖领域模型、Excel 读写、规则召回、证据 provider、各 Agent、review service、batch repository。

核心命令：

```powershell
python -m pytest tests/unit
```

## 集成测试

覆盖 FastAPI 上传、下载、批次查询、人工复核 API、文件安全和评测脚本。

```powershell
python -m pytest tests/integration
```

## 评测脚本

```powershell
python scripts/run_eval.py
```

当前样例指标：

- 样例数：10 条
- 准确率：100%
- 自动处理率：60%
- 人工复核率：40%
- 单批 AgentAssessment：60 条

## Trace 演示

```powershell
python scripts/demo_trace.py
```

该脚本会打印单条审批记录经过的 Agent 节点、节点耗时和最终审批结论。
