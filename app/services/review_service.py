from app.domain.decisions import DecisionAction
from app.domain.models import ApprovalDecision, ReviewTask


def create_review_task(decision: ApprovalDecision) -> ReviewTask | None:
    """根据审批结论创建人工复核任务，不需要复核时返回 None。"""
    if not decision.needs_review:
        return None

    return ReviewTask(
        task_id=f"review_{decision.case_id}",
        case_id=decision.case_id,
        priority=_get_review_priority(decision),
        reason=decision.reason,
        status="pending",
        reviewer=None,
        final_action=None,
    )


def create_review_tasks(decisions: list[ApprovalDecision]) -> list[ReviewTask]:
    """批量创建人工复核任务。"""
    review_tasks = []

    for decision in decisions:
        review_task = create_review_task(decision)

        if review_task is not None:
            review_tasks.append(review_task)

    return review_tasks


def calculate_review_metrics(decisions: list[ApprovalDecision]) -> dict[str, float | int]:
    """计算人工复核相关指标，用于项目报告和简历成果。"""
    total_count = len(decisions)

    if total_count == 0:
        return {
            "total_count": 0,
            "review_count": 0,
            "auto_handled_count": 0,
            "review_rate": 0.0,
            "auto_handled_rate": 0.0,
        }

    review_count = sum(1 for decision in decisions if decision.needs_review)
    auto_handled_count = total_count - review_count

    return {
        "total_count": total_count,
        "review_count": review_count,
        "auto_handled_count": auto_handled_count,
        "review_rate": review_count / total_count,
        "auto_handled_rate": auto_handled_count / total_count,
    }


def _get_review_priority(decision: ApprovalDecision) -> str:
    """根据审批动作和风险分生成复核优先级。"""
    if decision.risk_score >= 80:
        return "high"

    if decision.action == DecisionAction.NEEDS_HUMAN_REVIEW:
        return "high"

    if decision.action == DecisionAction.NEEDS_MORE_EVIDENCE:
        return "medium"

    return "low"