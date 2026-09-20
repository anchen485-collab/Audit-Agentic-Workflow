from pydantic import BaseModel, Field

from app.domain.decisions import ReviewFinalAction


class AuditUploadResponse(BaseModel):
    """上传审批 Excel 后返回的结果摘要。"""

    batch_id: str = Field(description="本次上传生成的批次 ID")
    case_count: int = Field(description="本批次审批单数量")
    decision_count: int = Field(description="审批结论数量")
    review_task_count: int = Field(description="人工复核任务数量")
    metrics: dict[str, float | int] = Field(description="审批指标")
    cases: list[dict] = Field(description="审批单列表，包含员工原始录入信息")
    decisions: list[dict] = Field(description="审批结论列表")
    review_tasks: list[dict] = Field(description="人工复核任务列表")
    download_url: str = Field(description="审批结果 Excel 下载地址")


class AuditBatchSummaryResponse(BaseModel):
    """审批批次摘要。"""

    batch_id: str = Field(description="审批批次 ID")
    trace_id: str = Field(description="审批流程 trace_id")
    download_url: str = Field(description="审批结果 Excel 下载地址")
    case_count: int = Field(description="审批单数量")
    decision_count: int = Field(description="审批结论数量")
    review_task_count: int = Field(description="人工复核任务数量")
    auto_handled_count: int = Field(description="自动处理数量")
    review_count: int = Field(description="人工复核数量")
    auto_handled_rate: float = Field(description="自动处理率")
    review_rate: float = Field(description="人工复核率")
    total_duration_ms: float = Field(description="本批次总耗时")
    created_at: str = Field(description="创建时间")


class AuditBatchListResponse(BaseModel):
    """审批批次列表响应。"""

    total: int = Field(description="返回批次数量")
    items: list[AuditBatchSummaryResponse] = Field(description="批次摘要列表")


class ReviewTaskListResponse(BaseModel):
    """人工复核任务列表响应。"""

    total: int = Field(description="任务数量")
    items: list[dict] = Field(description="人工复核任务列表")


class ReviewDecisionRequest(BaseModel):
    """人工复核提交请求。"""

    reviewer: str | None = Field(default=None, description="兼容旧前端字段；实际审核员以后端认证用户为准")
    final_action: ReviewFinalAction = Field(description="人工最终动作，例如 approved、rejected、unable_to_decide")


class CaseRetryResponse(BaseModel):
    """单条审批单重试后的当前结果。"""

    batch_id: str = Field(description="所属审批批次 ID")
    case_id: str = Field(description="被重新审批的审批单 ID")
    retry_trace_id: str = Field(description="本次重试的 Trace ID")
    previous_action: str = Field(description="重试前的系统审批动作")
    decision: dict = Field(description="重试后的当前审批结论")
    review_task: dict | None = Field(default=None, description="重试后需要人工复核时创建的任务")
    review_tasks: list[dict] = Field(description="该批次最新的人工复核任务列表")
    metrics: dict[str, float | int] = Field(description="重试后重新汇总的批次指标")


class LLMHealthResponse(BaseModel):
    """LLM 健康检查响应，不包含 API Key。"""

    enabled: bool = Field(description="是否启用真实 LLM")
    ok: bool = Field(description="LLM 配置或连通性是否正常")
    provider: str = Field(description="LLM provider 类型")
    model: str = Field(default="", description="当前模型名称")
    base_url: str = Field(default="", description="当前 LLM base_url")
    error_type: str = Field(default="", description="错误类型")
    message: str = Field(default="", description="中文说明或排查建议")
