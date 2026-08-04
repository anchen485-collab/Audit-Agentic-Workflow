from typing import Any

from app.domain.decisions import DecisionAction
from app.domain.models import AgentAssessment, ApprovalDecision, ReviewTask
from app.services.decision_service import calculate_decision_accuracy
from app.services.review_service import calculate_review_metrics


def calculate_audit_metrics(
    decisions: list[ApprovalDecision],
    review_tasks: list[ReviewTask],
    assessments: dict[str, list[AgentAssessment]] | None = None,
    trace_events: list[Any] | None = None,
    expected_actions: dict[str, str] | None = None,
) -> dict[str, float | int]:
    """统一计算审批业务指标，避免 API、workflow 和 eval 出现不同统计口径。"""
    review_metrics = calculate_review_metrics(decisions)
    total_count = len(decisions)
    assessments = assessments or {}
    trace_events = trace_events or []

    total_duration_ms = round(sum(float(getattr(event, "duration_ms", 0.0)) for event in trace_events), 3)
    assessment_count = sum(len(items) for items in assessments.values())
    llm_failure_count = _count_llm_failures(assessments)
    llm_invalid_json_count = _count_assessment_output(assessments, "error_code", "llm_invalid_json")
    llm_invalid_candidate_count = _count_assessment_output(assessments, "error_code", "llm_invalid_candidate")
    evidence_unavailable_count = _count_assessment_output(
        assessments,
        "evidence_error_type",
        "evidence_unavailable",
    )
    evidence_content_insufficient_count = _count_assessment_output(
        assessments,
        "evidence_error_type",
        "evidence_content_insufficient",
    )

    metrics: dict[str, float | int] = {
        **review_metrics,
        "decision_count": total_count,
        "review_task_count": len(review_tasks),
        "agent_assessment_count": assessment_count,
        "total_duration_ms": total_duration_ms,
        "average_latency_ms": _rate(total_duration_ms, total_count),
        "auto_approval_count": _count_action(decisions, DecisionAction.APPROVED),
        "auto_approval_rate": _action_rate(decisions, DecisionAction.APPROVED),
        "auto_rejection_count": _count_action(decisions, DecisionAction.REJECTED),
        "auto_rejection_rate": _action_rate(decisions, DecisionAction.REJECTED),
        "human_review_count": _count_action(decisions, DecisionAction.NEEDS_HUMAN_REVIEW),
        "human_review_rate": _action_rate(decisions, DecisionAction.NEEDS_HUMAN_REVIEW),
        "insufficient_evidence_count": _count_action(decisions, DecisionAction.NEEDS_MORE_EVIDENCE),
        "insufficient_evidence_rate": _action_rate(decisions, DecisionAction.NEEDS_MORE_EVIDENCE),
        "llm_failure_count": llm_failure_count,
        "llm_failure_rate": _rate(llm_failure_count, max(total_count, 1)),
        "classification_agent_failure_count": llm_failure_count,
        "classification_agent_failure_rate": _rate(llm_failure_count, total_count),
        "llm_invalid_candidate_count": llm_invalid_candidate_count,
        "llm_invalid_json_count": llm_invalid_json_count,
        "evidence_unavailable_count": evidence_unavailable_count,
        "evidence_content_insufficient_count": evidence_content_insufficient_count,
    }

    if expected_actions is not None:
        metrics["accuracy"] = calculate_decision_accuracy(
            decisions=decisions,
            expected_actions=expected_actions,
        )

    return metrics


def _count_action(decisions: list[ApprovalDecision], action: DecisionAction) -> int:
    """统计某类最终审批动作数量。"""
    return sum(1 for decision in decisions if decision.action == action)


def _action_rate(decisions: list[ApprovalDecision], action: DecisionAction) -> float:
    """统计某类最终审批动作占比。"""
    return _rate(_count_action(decisions, action), len(decisions))


def _count_llm_failures(assessments: dict[str, list[AgentAssessment]]) -> int:
    """统计 Classification Agent 失败次数，用于衡量 LLM 稳定性。"""
    return sum(
        1
        for case_assessments in assessments.values()
        for assessment in case_assessments
        if assessment.agent_name == "classification_agent" and assessment.status == "failed"
    )


def _count_assessment_output(
    assessments: dict[str, list[AgentAssessment]],
    key: str,
    value: str,
) -> int:
    """按 AgentAssessment output 中的字段统计错误类型。"""
    return sum(
        1
        for case_assessments in assessments.values()
        for assessment in case_assessments
        if assessment.agent_name == "classification_agent" and assessment.output.get(key) == value
    )


def _rate(numerator: float, denominator: int) -> float:
    """安全计算比例，避免空批次除零。"""
    if denominator <= 0:
        return 0.0

    return numerator / denominator
