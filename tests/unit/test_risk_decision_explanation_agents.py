from app.agents.decision_agent import DecisionAgent
from app.agents.explanation_agent import ExplanationAgent
from app.agents.llm_classification_provider import SemanticClassificationResult
from app.agents.risk_agent import RiskAgent, RiskAssessment, RiskLevel
from app.domain.decisions import DecisionAction, DecisionStatus
from app.domain.models import AuditCase, CandidateRuleSet, CategoryRule, EvidencePackage, EvidenceSnippet


def test_risk_agent_marks_low_quality_evidence_as_high_risk():
    result = RiskAgent().run(
        audit_case=_build_case(),
        evidence=_build_evidence(quality_score=0, snippets=[]),
        candidate_rules=_build_rules(),
        classification_result=_classification_result("insufficient_evidence"),
    )

    assert result.value.risk_level == RiskLevel.HIGH
    assert result.value.risk_score >= 70
    assert result.assessment.status == "success"
    assert result.assessment.output["risk_level"] == "high"


def test_decision_agent_approves_low_risk_supported_case():
    risk = RiskAgent().run(
        audit_case=_build_case(),
        evidence=_build_evidence(),
        candidate_rules=_build_rules(),
        classification_result=_classification_result("supports_entered_category"),
    ).value

    result = DecisionAgent().run(
        audit_case=_build_case(),
        evidence=_build_evidence(),
        candidate_rules=_build_rules(),
        classification_result=_classification_result("supports_entered_category"),
        risk_assessment=risk,
    )

    assert result.value.action == DecisionAction.APPROVED
    assert result.value.status == DecisionStatus.COMPLETED
    assert result.value.needs_review is False
    assert result.assessment.agent_name == "decision_agent"


def test_decision_agent_routes_high_risk_approval_to_human_review():
    risk = _high_risk()

    result = DecisionAgent().run(
        audit_case=_build_case(),
        evidence=_build_evidence(),
        candidate_rules=_build_rules(),
        classification_result=_classification_result("supports_entered_category"),
        risk_assessment=risk,
    )

    assert result.value.action == DecisionAction.NEEDS_HUMAN_REVIEW
    assert result.value.status == DecisionStatus.PENDING_REVIEW
    assert result.value.needs_review is True


def test_decision_agent_routes_high_risk_rejection_to_human_review():
    """高风险自动驳回也应该转人工，避免错误驳回员工录入。"""
    risk = _high_risk()

    result = DecisionAgent().run(
        audit_case=_build_case(),
        evidence=_build_evidence(),
        candidate_rules=_build_rules(),
        classification_result=_classification_result("conflicts_with_entered_category"),
        risk_assessment=risk,
    )

    assert result.value.action == DecisionAction.NEEDS_HUMAN_REVIEW
    assert result.value.status == DecisionStatus.PENDING_REVIEW
    assert result.value.needs_review is True


def test_decision_agent_routes_abnormal_granularity_to_human_review():
    """即使语义结果支持分类，异常细分粒度也不能自动通过。"""
    rules = _build_rules().model_copy(
        update={
            "entered_path_exists": True,
            "entered_subcategory_granularity": "mixed",
            "granularity_reason": "同一条记录的细分混合了二级和三级分类。",
        }
    )

    result = DecisionAgent().run(
        audit_case=_build_case(),
        evidence=_build_evidence(),
        candidate_rules=rules,
        classification_result=_classification_result("supports_entered_category"),
        risk_assessment=RiskAssessment(
            case_id="case_001",
            risk_level=RiskLevel.LOW,
            risk_score=20,
            reasons=[],
        ),
    )

    assert result.value.action == DecisionAction.NEEDS_HUMAN_REVIEW
    assert result.value.needs_review is True


def test_decision_agent_uses_evidence_reason_when_final_action_needs_more_evidence():
    """即使语义结果写成支持分类，证据不足时最终原因也应该展示证据问题。"""
    evidence = _build_evidence(
        quality_score=0,
        snippets=[],
        errors=["官网访问失败：502 Bad Gateway"],
    )

    result = DecisionAgent().run(
        audit_case=_build_case(),
        evidence=evidence,
        candidate_rules=_build_rules(),
        classification_result=_classification_result("supports_entered_category"),
        risk_assessment=RiskAssessment(
            case_id="case_001",
            risk_level=RiskLevel.LOW,
            risk_score=20,
            reasons=[],
        ),
    )

    assert result.value.action == DecisionAction.NEEDS_MORE_EVIDENCE
    assert "官网访问失败" in result.value.reason
    assert "supports" not in result.value.reason


def test_explanation_agent_generates_internal_and_employee_text():
    decision = DecisionAgent().run(
        audit_case=_build_case(),
        evidence=_build_evidence(),
        candidate_rules=_build_rules(),
        classification_result=_classification_result("conflicts_with_entered_category"),
        risk_assessment=RiskAgent().run(
            audit_case=_build_case(),
            evidence=_build_evidence(),
            candidate_rules=_build_rules(),
            classification_result=_classification_result("conflicts_with_entered_category"),
        ).value,
    ).value

    result = ExplanationAgent().run(audit_case=_build_case(), decision=decision)

    assert result.value.internal_reason
    assert result.value.employee_feedback
    assert result.assessment.agent_name == "explanation_agent"


def test_decision_agent_rejects_with_matched_candidate_rule_id():
    """证据冲突且候选规则 ID 合法时，可以自动驳回并给出规则表内建议。"""
    result = DecisionAgent().run(
        audit_case=_build_case(),
        evidence=_build_evidence(),
        candidate_rules=_build_rules(),
        classification_result=_classification_result(
            "conflicts_with_entered_category",
            matched_candidate_rule_id="rule_1",
        ),
        risk_assessment=RiskAssessment(
            case_id="case_001",
            risk_level=RiskLevel.LOW,
            risk_score=30,
            reasons=[],
        ),
    )

    assert result.value.action == DecisionAction.REJECTED
    assert "Software / Information Technology / Software Development" in result.value.suggestion


def _build_case() -> AuditCase:
    return AuditCase(
        case_id="case_001",
        batch_id="batch_001",
        row_number=2,
        employee_name="Alice",
        company_raw="Acme Software",
        company_name="Acme Software",
        website_url="",
        entered_level1="Software",
        entered_subcategory="Software Development",
        entered_stage="input",
        status="pending",
    )


def _build_evidence(
    quality_score: int = 90,
    snippets: list[EvidenceSnippet] | None = None,
    errors: list[str] | None = None,
) -> EvidencePackage:
    return EvidencePackage(
        case_id="case_001",
        company_name="Acme Software",
        sources=["fake"],
        business_scope="Company provides software development services.",
        snippets=snippets
        if snippets is not None
        else [EvidenceSnippet(source="fake", text="software development", url="")],
        quality_score=quality_score,
        errors=errors or [],
    )


def _build_rules() -> CandidateRuleSet:
    return CandidateRuleSet(
        case_id="case_001",
        entered_path_exists=True,
        candidates=[
            CategoryRule(
                level1="Software",
                level2="Information Technology",
                level3="Software Development",
                module="business",
                keywords=["software"],
            )
        ],
        retrieval_reason="matched software",
    )


def _classification_result(
    result: str,
    confidence: int = 90,
    matched_candidate_rule_id: str = "",
) -> SemanticClassificationResult:
    return SemanticClassificationResult(
        result=result,
        confidence=confidence,
        matched_candidate_rule_id=matched_candidate_rule_id,
        matched_level1="Software",
        matched_level2="Information Technology",
        matched_level3="Software Development",
        evidence_quotes=["software development"],
        reason="classification reason",
        suggestion="Software / Information Technology / Software Development",
    )


def _high_risk() -> RiskAssessment:
    return RiskAssessment(
        case_id="case_001",
        risk_level=RiskLevel.HIGH,
        risk_score=85,
        reasons=["测试构造的高风险。"],
    )
