from app.domain.decisions import DecisionAction, DecisionStatus
from app.domain.models import AgentAssessment, ApprovalDecision, ReviewTask
from app.observability.metrics import calculate_audit_metrics


def test_calculate_audit_metrics_returns_business_and_agent_metrics():
    """审批指标应该同时覆盖业务效果、人工复核和 Agent 稳定性。"""
    decisions = [
        _decision("case_001", DecisionAction.APPROVED, needs_review=False),
        _decision("case_002", DecisionAction.REJECTED, needs_review=False),
        _decision("case_003", DecisionAction.NEEDS_HUMAN_REVIEW, needs_review=True),
        _decision("case_004", DecisionAction.NEEDS_MORE_EVIDENCE, needs_review=True),
    ]
    review_tasks = [
        ReviewTask(
            task_id="review_case_003",
            case_id="case_003",
            priority="high",
            reason="需要人工确认",
            status="pending",
        ),
        ReviewTask(
            task_id="review_case_004",
            case_id="case_004",
            priority="medium",
            reason="证据不足",
            status="pending",
        ),
    ]
    assessments = {
        "case_001": [_assessment("classification_agent", "success")],
        "case_002": [_assessment("classification_agent", "failed", {"error_code": "llm_invalid_json"})],
        "case_003": [_assessment("classification_agent", "failed", {"error_code": "llm_invalid_candidate"})],
        "case_004": [
            _assessment(
                "classification_agent",
                "success",
                {"evidence_error_type": "evidence_unavailable"},
            )
        ],
    }

    metrics = calculate_audit_metrics(
        decisions=decisions,
        review_tasks=review_tasks,
        assessments=assessments,
        trace_events=[],
        expected_actions={
            "case_001": "approved",
            "case_002": "rejected",
            "case_003": "needs_human_review",
            "case_004": "approved",
        },
    )

    assert metrics["total_count"] == 4
    assert metrics["auto_approval_rate"] == 0.25
    assert metrics["auto_rejection_rate"] == 0.25
    assert metrics["human_review_rate"] == 0.25
    assert metrics["insufficient_evidence_rate"] == 0.25
    assert metrics["review_rate"] == 0.5
    assert metrics["llm_failure_rate"] == 0.5
    assert metrics["classification_agent_failure_rate"] == 0.5
    assert metrics["llm_invalid_json_count"] == 1
    assert metrics["llm_invalid_candidate_count"] == 1
    assert metrics["evidence_unavailable_count"] == 1
    assert metrics["accuracy"] == 0.75


def _decision(case_id: str, action: DecisionAction, needs_review: bool) -> ApprovalDecision:
    """构造测试用审批结论。"""
    return ApprovalDecision(
        case_id=case_id,
        action=action,
        status=DecisionStatus.PENDING_REVIEW if needs_review else DecisionStatus.COMPLETED,
        confidence=80,
        risk_score=50,
        reason="测试原因",
        suggestion="",
        needs_review=needs_review,
    )


def _assessment(agent_name: str, status: str, output: dict | None = None) -> AgentAssessment:
    """构造测试用 AgentAssessment。"""
    return AgentAssessment(
        agent_name=agent_name,
        status=status,
        confidence=80,
        findings=[],
        output=output or {},
        duration_ms=10,
    )
