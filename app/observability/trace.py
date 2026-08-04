from time import perf_counter
from uuid import uuid4

from pydantic import BaseModel, Field

from app.observability.logging import get_audit_logger

logger = get_audit_logger("observability.trace")


class TraceEvent(BaseModel):
    """工作流节点执行记录。"""

    trace_id: str = Field(description="本次审批流程的追踪 ID")
    node_name: str = Field(description="节点名称")
    status: str = Field(description="节点执行状态，例如 success 或 failed")
    duration_ms: float = Field(ge=0, description="节点耗时，单位毫秒")
    message: str = Field(default="", description="节点补充说明")


def new_trace_id() -> str:
    """生成一次审批流程的 trace_id。"""
    return f"trace_{uuid4().hex[:12]}"


def run_with_trace(trace_id: str, node_name: str, func):
    """执行一个节点函数，并返回节点结果和 trace 事件。"""
    start_time = perf_counter()

    try:
        result = func()
    except Exception as error:
        duration_ms = _elapsed_ms(start_time)
        event = TraceEvent(
            trace_id=trace_id,
            node_name=node_name,
            status="failed",
            duration_ms=duration_ms,
            message="节点执行失败。",
        )
        logger.exception(
            "工作流节点失败: trace_id=%s node=%s duration_ms=%.3f reason=%s",
            trace_id,
            node_name,
            duration_ms,
            error,
        )
        raise

    duration_ms = _elapsed_ms(start_time)
    event = TraceEvent(
        trace_id=trace_id,
        node_name=node_name,
        status="success",
        duration_ms=duration_ms,
        message="节点执行成功。",
    )

    return result, event


def _elapsed_ms(start_time: float) -> float:
    """计算从 start_time 到当前时间的毫秒耗时。"""
    return round((perf_counter() - start_time) * 1000, 3)
