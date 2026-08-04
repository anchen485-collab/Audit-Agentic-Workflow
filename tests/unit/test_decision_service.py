from app.domain.decisions import DecisionAction
from app.domain.models import ApprovalDecision
from app.services.decision_service import calculate_decision_accuracy


def test_calculate_decision_accuracy():
    """应该能计算审批动作准确率。"""
    decisions = [
        ApprovalDecision(
            case_id="case_001",
            action=DecisionAction.APPROVED,
            status="completed",
            confidence=90,
            risk_score=10,
            reason="证据支持分类。",
            suggestion="",
            needs_review=False,
        ),
        ApprovalDecision(
            case_id="case_002",
            action=DecisionAction.REJECTED,
            status="completed",
            confidence=88,
            risk_score=40,
            reason="证据不支持分类。",
            suggestion="信软技术服务 / 软件开发",
            needs_review=False,
        ),
    ]

    expected_actions = {
        "case_001": "approved",
        "case_002": "rejected",
    }

    accuracy = calculate_decision_accuracy(decisions, expected_actions)

    assert accuracy == 1.0