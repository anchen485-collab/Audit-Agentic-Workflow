from app.domain.decisions import DecisionAction
from app.domain.models import ApprovalDecision


def route_decision(decision: ApprovalDecision) -> str:
    """把审批动作映射到后续业务路由。"""
    if decision.action == DecisionAction.APPROVED:
        return "auto_approve"

    if decision.action == DecisionAction.REJECTED:
        return "auto_reject"

    if decision.action == DecisionAction.NEEDS_MORE_EVIDENCE:
        return "request_more_evidence"

    return "create_review_task"
