from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter
from typing import Any, Generic, TypeVar

from app.domain.models import AgentAssessment
from app.observability.logging import get_audit_logger

T = TypeVar("T")
logger = get_audit_logger("agents.base")


class AgentStatus(StrEnum):
    """Agent 执行状态。"""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class AgentExecutionResult(Generic[T]):
    """Agent 执行结果：业务结果 + 评估记录。"""

    value: T
    assessment: AgentAssessment


def build_agent_assessment(
    agent_name: str,
    status: AgentStatus,
    confidence: int,
    findings: list[str] | None = None,
    output: dict[str, Any] | None = None,
    duration_ms: float = 0,
) -> AgentAssessment:
    """创建统一的 AgentAssessment。"""
    return AgentAssessment(
        agent_name=agent_name,
        status=status.value,
        confidence=confidence,
        findings=findings or [],
        output=output or {},
        duration_ms=round(duration_ms, 3),
    )


def run_agent_step(
    agent_name: str,
    func: Callable[[], tuple[T, list[str], dict[str, Any], int]],
    fallback_value: T,
) -> AgentExecutionResult[T]:
    """执行一个 Agent 步骤，并统一生成 AgentAssessment。"""
    start = perf_counter()

    try:
        value, findings, output, confidence = func()
        duration_ms = (perf_counter() - start) * 1000
        case_id = output.get("case_id", "")
        logger.info(
            "Agent 执行完成: agent=%s case_id=%s confidence=%s duration_ms=%.3f",
            agent_name,
            case_id,
            confidence,
            duration_ms,
        )

        assessment = build_agent_assessment(
            agent_name=agent_name,
            status=AgentStatus.SUCCESS,
            confidence=confidence,
            findings=findings,
            output=output,
            duration_ms=duration_ms,
        )

        return AgentExecutionResult(value=value, assessment=assessment)

    except Exception as error:
        duration_ms = (perf_counter() - start) * 1000
        logger.exception(
            "Agent 执行失败，已使用兜底结果: agent=%s duration_ms=%.3f reason=%s",
            agent_name,
            duration_ms,
            error,
        )

        assessment = build_agent_assessment(
            agent_name=agent_name,
            status=AgentStatus.FAILED,
            confidence=0,
            findings=[f"{agent_name} 执行失败：{error}"],
            output=_build_error_output(error),
            duration_ms=duration_ms,
        )

        return AgentExecutionResult(value=fallback_value, assessment=assessment)


def _build_error_output(error: Exception) -> dict[str, Any]:
    """生成结构化错误输出，方便 Excel、API 和指标统计复用。"""
    error_code = getattr(error, "error_code", error.__class__.__name__)
    return {
        "error": str(error),
        "error_code": error_code,
        "suggestion": _suggestion_for_error_code(str(error_code)),
    }


def _suggestion_for_error_code(error_code: str) -> str:
    """根据错误类型给出排查建议。"""
    if error_code == "llm_invalid_json":
        return "请检查 LLM prompt、模型稳定性或 JSON 输出约束。"

    if error_code == "llm_invalid_candidate":
        return "请检查候选规则召回和 LLM 返回的 matched_candidate_rule_id。"

    if error_code == "llm_provider_auth":
        return "请检查 LLM_API_KEY、LLM_BASE_URL 和模型权限。"

    return "请查看服务端日志定位具体异常。"
