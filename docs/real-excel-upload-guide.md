# 真实 Excel 上传审批说明

## 1. 上传模板

标准模板路径：

```text
data/templates/audit_upload_template.xlsx
```

必须包含以下表头：

- `日期`
- `姓名`
- `一级分类`
- `细分`
- `企业名称&官网`

可选表头：

- `二级分类`

如果 Excel 中有 `二级分类`、`二级品类` 或 `二级` 列，系统会读取员工录入的二级分类，并在结果 Excel 的 `审批明细` 中展示；如果没有该列，则该字段为空，不影响上传。

其中 `企业名称&官网` 建议同时填写企业名称和官网地址，例如：

```text
示例企业有限公司 https://example.com
```

如果没有官网，系统在 `COMPANY_PROVIDER=website` 模式下会将该行判断为证据不足或转人工复核。

## 2. 内部规则

真实内部规则 Excel 已转换为：

```text
data/rules/category_rules.json
```

转换命令：

```powershell
.\.venv\Scripts\python.exe scripts\convert_category_rules.py
```

脚本默认读取：

```text
C:\Users\Administrator\Desktop\document\最终分类表.xlsx
```

如果规则 Excel 换了位置，可以使用：

```powershell
.\.venv\Scripts\python.exe scripts\convert_category_rules.py --input "你的规则表.xlsx"
```

## 3. 证据来源

通过 `.env` 中的 `COMPANY_PROVIDER` 控制：

```text
COMPANY_PROVIDER=mock
```

使用本地 mock 证据，适合测试和评测。

```text
COMPANY_PROVIDER=website
```

使用官网爬虫 provider，适合上传真实 Excel 做真实证据采集。

## 4. LLM 配置

当前项目使用 OpenAI-compatible Chat Completions 格式调用 LLM。DeepSeek 官方兼容 OpenAI API，推荐配置：

```text
LLM_ENABLED=true
LLM_API_KEY=你的 DeepSeek API Key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
```

如果控制台出现 `401 Unauthorized`，通常不是代码不兼容，而是：

- `LLM_API_KEY` 不是当前平台的 key。
- `LLM_BASE_URL` 和 key 不匹配。
- key 已失效或账户余额/权限异常。
- 服务进程没有重启，仍在读取旧 `.env`。

## 5. 上传接口

启动服务后进入：

```text
http://127.0.0.1:8000/docs
```

调用：

```text
POST /api/audit/upload
```

上传 `.xlsx` 文件后，响应中会返回：

- `batch_id`
- `metrics`
- `decisions`
- `review_tasks`
- `download_url`

## 6. 下载结果

上传成功后，使用响应里的 `download_url` 下载结果 Excel：

```text
GET /api/audit/batches/{batch_id}/result
```

结果 Excel 包含：

- `审批明细`
- `人员汇总`
- `人工复核任务`

`审批明细` 中会包含审批动作、风险分、原因、建议、证据来源、证据质量分、证据片段和采集错误。
同时会回显员工录入信息，包括录入人员、一级分类、二级分类、细分、企业名称和企业官网，方便审核员对照原始录入内容。
