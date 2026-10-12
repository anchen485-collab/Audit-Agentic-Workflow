from app.agents.decision_verifier import DecisionVerifier
from app.agents.llm_classification_provider import SemanticClassificationResult
from app.agents.risk_agent import RiskAssessment, RiskLevel
from app.domain.decisions import DecisionAction, DecisionStatus
from app.domain.models import (
    ApprovalDecision,
    AuditCase,
    CandidateCategory,
    CandidateRuleSet,
    CategoryRule,
    EvidencePackage,
    EvidenceSnippet,
)


def test_low_confidence_auto_decision_is_sent_to_review():
    result = _run_verifier(classification=_classification(confidence=69))

    assert result.value.action == DecisionAction.NEEDS_HUMAN_REVIEW
    assert result.value.confidence == 60
    assert "置信度" in result.value.reason


def test_fallback_semantic_result_is_sent_to_review():
    result = _run_verifier(
        classification=_classification(normalization_warning="LLM 调用失败，已使用确定性规则兜底。"),
    )

    assert result.value.action == DecisionAction.NEEDS_HUMAN_REVIEW
    assert any("降级处理" in failure for failure in result.assessment.output["failures"])


def test_mismatched_case_data_is_sent_to_review():
    evidence = _evidence().model_copy(update={"case_id": "other_case"})

    result = _run_verifier(evidence=evidence)

    assert result.value.action == DecisionAction.NEEDS_HUMAN_REVIEW
    assert "case_id" in result.value.reason


def test_partial_level2_path_can_match_category_candidate():
    candidate_rules = _rules().model_copy(
        update={
            "category_candidates": [
                CandidateCategory(
                    level1="Software",
                    level2="Information Technology",
                    level3="",
                    granularity="level2",
                    matched_entered_value="Information Technology",
                )
            ],
            "entered_subcategory_granularity": "level2",
            "granularity_reason": "员工细分命中二级分类。",
        }
    )
    classification = _classification(
        matched_level3="",
        matched_category_candidate_ids=["category_1"],
    )

    result = _run_verifier(candidate_rules=candidate_rules, classification=classification)

    assert result.value.action == DecisionAction.APPROVED
    assert result.assessment.output["verification_status"] == "passed"


def test_verifier_exception_downgrades_auto_decision():
    class BrokenVerifier(DecisionVerifier):
        def _verify(self, *args, **kwargs):
            raise RuntimeError("verifier broken")

    result = BrokenVerifier().run(
        audit_case=_case(),
        evidence=_evidence(),
        candidate_rules=_rules(),
        classification_result=_classification(),
        risk_assessment=_risk(),
        decision=_decision(),
    )

    assert result.value.action == DecisionAction.NEEDS_HUMAN_REVIEW
    assert result.value.status == DecisionStatus.PENDING_REVIEW
    assert result.assessment.status == "failed"


def test_non_auto_decision_is_reported_as_skipped():
    manual_decision = _decision().model_copy(
        update={
            "action": DecisionAction.NEEDS_HUMAN_REVIEW,
            "status": DecisionStatus.PENDING_REVIEW,
            "needs_review": True,
        }
    )

    result = _run_verifier(decision=manual_decision)

    assert result.value == manual_decision
    assert result.assessment.status == "skipped"
    assert result.assessment.output["verification_status"] == "skipped"
    assert result.assessment.output["skipped"] is True


def test_valid_auto_rejection_passes_verification():
    result = _run_verifier(
        classification=_classification(result="conflicts_with_entered_category"),
        decision=_decision(action=DecisionAction.REJECTED),
    )

    assert result.value.action == DecisionAction.REJECTED
    assert result.assessment.output["verification_status"] == "passed"


def test_risk_score_mismatch_is_sent_to_review():
    risk = _risk().model_copy(update={"risk_score": 25})

    result = _run_verifier(risk=risk)

    assert result.value.action == DecisionAction.NEEDS_HUMAN_REVIEW
    assert any("风险分" in failure for failure in result.assessment.output["failures"])


def test_evidence_with_collection_errors_is_sent_to_review():
    evidence = _evidence().model_copy(update={"errors": ["官网部分页面抓取失败。"]})

    result = _run_verifier(evidence=evidence)

    assert result.value.action == DecisionAction.NEEDS_HUMAN_REVIEW
    assert any("采集错误" in failure for failure in result.assessment.output["failures"])


def test_incomplete_multi_level2_support_is_sent_to_review():
    candidate_rules = _rules().model_copy(
        update={
            "category_candidates": [
                CandidateCategory(
                    level1="Software",
                    level2="Information Technology",
                    granularity="level2",
                    matched_entered_value="Information Technology",
                ),
                CandidateCategory(
                    level1="Software",
                    level2="Cloud Services",
                    granularity="level2",
                    matched_entered_value="Cloud Services",
                ),
            ],
            "entered_subcategory_granularity": "level2",
            "granularity_reason": "员工细分命中两个二级分类。",
        }
    )
    classification = _classification(matched_category_candidate_ids=["category_1"])

    result = _run_verifier(candidate_rules=candidate_rules, classification=classification)

    assert result.value.action == DecisionAction.NEEDS_HUMAN_REVIEW
    assert any("全部二级分类" in failure for failure in result.assessment.output["failures"])


def _run_verifier(
    evidence: EvidencePackage | None = None,
    candidate_rules: CandidateRuleSet | None = None,
    classification: SemanticClassificationResult | None = None,
    risk: RiskAssessment | None = None,
    decision: ApprovalDecision | None = None,
):
    return DecisionVerifier().run(
        audit_case=_case(),
        evidence=evidence or _evidence(),
        candidate_rules=candidate_rules or _rules(),
        classification_result=classification or _classification(),
        risk_assessment=risk or _risk(),
        decision=decision or _decision(),
    )


def _case() -> AuditCase:
    return AuditCase(
        case_id="case_001",
        batch_id="batch_001",
        row_number=2,
        employee_name="Alice",
        company_raw="Acme Software",
        company_name="Acme Software",
        entered_level1="Software",
        entered_subcategory="Software Development",
    )


def _evidence() -> EvidencePackage:
    return EvidencePackage(
        case_id="case_001",
        company_name="Acme Software",
        sources=["website"],
        business_scope="Company provides software development services.",
        snippets=[EvidenceSnippet(source="website", text="software development", url="https://example.com")],
        quality_score=90,
    )


def _rules() -> CandidateRuleSet:
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
    )


def _classification(
    result: str = "supports_entered_category",
    confidence: int = 90,
    normalization_warning: str = "",
    matched_level3: str = "Software Development",
    matched_category_candidate_ids: list[str] | None = None,
) -> SemanticClassificationResult:
    return SemanticClassificationResult(
        result=result,
        confidence=confidence,
        matched_level1="Software",
        matched_level2="Information Technology",
        matched_level3=matched_level3,
        matched_category_candidate_ids=matched_category_candidate_ids or [],
        evidence_quotes=["software development"],
        reason="Evidence supports the entered category.",
        normalization_warning=normalization_warning,
    )


def _risk() -> RiskAssessment:
    return RiskAssessment(
        case_id="case_001",
        risk_level=RiskLevel.LOW,
        risk_score=20,
        reasons=["No obvious risk."],
    )


def _decision(action: DecisionAction = DecisionAction.APPROVED) -> ApprovalDecision:
    suggestion = "Software / Information Technology / Software Development" if action == DecisionAction.REJECTED else ""
    return ApprovalDecision(
        case_id="case_001",
        action=action,
        status=DecisionStatus.COMPLETED,
        confidence=90,
        risk_score=20,
        reason="Evidence supports the entered category.",
        suggestion=suggestion,
        needs_review=False,
    )
