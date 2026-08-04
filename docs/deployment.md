# 部署说明

## 本地启动

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn app.api.app:app --reload
```

健康检查：

```powershell
curl http://127.0.0.1:8000/health
```

## Docker 启动

```powershell
docker build -t audit-agent .
docker compose up
```

默认挂载 `storage/`，上传文件、结果 Excel 和 SQLite 数据库会保留在本地。

## 环境变量

参考 `.env.example`：

- `AUDIT_STORAGE_DIR`：本地存储目录。
- `LLM_ENABLED`：是否启用真实 LLM。
- `LLM_API_KEY`：真实 LLM API key。
- `LLM_BASE_URL`：OpenAI-compatible API 地址。
- `LLM_MODEL`：模型名称。
- `COMPANY_PROVIDER`：企业证据 provider 类型。

## 回滚思路

- 保留上一版 Docker 镜像 tag。
- 保留 `storage/audit_agent.db` 备份。
- 部署异常时切回上一版镜像并恢复数据库备份。


## ????????

???????????? `app.api.app:app`?Dockerfile?README ??????????????????????????? `app/main.py`?

Docker Compose ???? `.env`?`.env.example` ????????????????? `.env`?
