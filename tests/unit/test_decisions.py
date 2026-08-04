import pytest
from pydantic import ValidationError

from app.domain.decisions import DecisionAction, DecisionStatus, needs_manual_review
from app.domain.models import ApprovalDecision


def test_decision_action_values_are_controlled():
    """审批动作必须是固定的四类结果。"""
    assert DecisionAction.APPROVED == "approved"
    assert DecisionAction.REJECTED == "rejected"
    assert DecisionAction.NEEDS_MORE_EVIDENCE == "needs_more_evidence"
    assert DecisionAction.NEEDS_HUMAN_REVIEW == "needs_human_review"


def test_needs_manual_review_identifies_review_actions():
    """证据不足和人工复核都不能自动完成。"""
    assert needs_manual_review(DecisionAction.NEEDS_HUMAN_REVIEW) is True
    assert needs_manual_review(DecisionAction.NEEDS_MORE_EVIDENCE) is True
    assert needs_manual_review(DecisionAction.APPROVED) is False
    assert needs_manual_review(DecisionAction.REJECTED) is False


def test_approval_decision_rejects_unknown_action():
    """非法审批动作应该被 Pydantic 拦截。"""
    with pytest.raises(ValidationError):
        ApprovalDecision(
            case_id="case_001",
            action="random_action",
            status=DecisionStatus.COMPLETED,
            confidence=90,
            risk_score=10,
            reason="非法动作不应该通过。",
        )