from app.domain.decisions import DecisionAction, DecisionStatus
from app.domain.models import ApprovalDecision
from app.services.review_service import calculate_review_metrics, create_review_task, create_review_tasks


def test_create_review_task_for_human_review_decision():
    """需要人工复核的审批结论，应该生成 ReviewTask。"""
    decision = ApprovalDecision(
        case_id="case_009",
        action=DecisionAction.NEEDS_HUMAN_REVIEW,
        status=DecisionStatus.PENDING_REVIEW,
        confidence=70,
        risk_score=80,
        reason="证据同时支持多个业务方向，需要人工确认主营业务。",
        suggestion="请人工确认企业主营业务。",
        needs_review=True,
    )

    review_task = create_review_task(decision)

    assert review_task is not None
    assert review_task.task_id == "review_case_009"
    assert review_task.case_id == "case_009"
    assert review_task.priority == "high"
    assert review_task.status == "pending"
    assert review_task.final_action is None


def test_create_review_task_returns_none_for_auto_approved_decision():
    """自动通过的审批结论，不应该生成 ReviewTask。"""
    decision = ApprovalDecision(
        case_id="case_001",
        action=DecisionAction.APPROVED,
        status=DecisionStatus.COMPLETED,
        confidence=90,
        risk_score=10,
        reason="证据支持员工录入分类。",
        suggestion="",
        needs_review=False,
    )

    review_task = create_review_task(decision)

    assert review_task is None


def test_create_review_tasks_only_keeps_review_needed_decisions():
    """批量创建时，只应该为 needs_review=True 的结论创建任务。"""
    decisions = [
        ApprovalDecision(
            case_id="case_001",
            action=DecisionAction.APPROVED,
            status=DecisionStatus.COMPLETED,
            confidence=90,
            risk_score=10,
            reason="证据支持分类。",
            suggestion="",
            needs_review=False,
        ),
        ApprovalDecision(
            case_id="case_007",
            action=DecisionAction.NEEDS_MORE_EVIDENCE,
            status=DecisionStatus.PENDING_REVIEW,
            confidence=80,
            risk_score=70,
            reason="外部证据不足。",
            suggestion="请补充官网。",
            needs_review=True,
        ),
    ]

    review_tasks = create_review_tasks(decisions)

    assert len(review_tasks) == 1
    assert review_tasks[0].case_id == "case_007"



def test_calculate_review_metrics():
    """应该能计算人工复核率和自动处理率。"""
    decisions = [
        ApprovalDecision(
            case_id="case_001",
            action=DecisionAction.APPROVED,
            status=DecisionStatus.COMPLETED,
            confidence=90,
            risk_score=10,
            reason="通过。",
            suggestion="",
            needs_review=False,
        ),
        ApprovalDecision(
            case_id="case_007",
            action=DecisionAction.NEEDS_MORE_EVIDENCE,
            status=DecisionStatus.PENDING_REVIEW,
            confidence=80,
            risk_score=70,
            reason="证据不足。",
            suggestion="请补充证据。",
            needs_review=True,
        ),
    ]

    metrics = calculate_review_metrics(decisions)

    assert metrics["total_count"] == 2
    assert metrics["review_count"] == 1
    assert metrics["auto_handled_count"] == 1
    assert metrics["review_rate"] == 0.5
    assert metrics["auto_handled_rate"] == 0.5