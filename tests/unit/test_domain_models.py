import pytest
from pydantic import ValidationError

from app.domain.models import (
    AgentAssessment,
    ApprovalDecision,
    AuditCase,
    CandidateCategory,
    CandidateRuleSet,
    CategoryRule,
    CurrentUser,
    EvidencePackage,
    EvidenceSnippet,
    ReviewTask,
)


def test_audit_case_can_be_serialized():
    """审批单应该能表达一条员工录入记录。"""
    case = AuditCase(
        case_id="case_001",
        batch_id="batch_001",
        row_number=2,
        employee_name="张三",
        company_raw="杭州云启软件有限公司 https://example.com",
        company_name="杭州云启软件有限公司",
        website_url="https://example.com",
        entered_level1="信软技术服务",
        entered_subcategory="软件开发",
        entered_stage="录入",
        status="pending",
    )

    data = case.model_dump()

    assert data["case_id"] == "case_001"
    assert data["company_name"] == "杭州云启软件有限公司"
    assert data["status"] == "pending"


def test_evidence_package_contains_snippets_and_quality_score():
    """证据包应该包含来源、证据片段和质量分。"""
    package = EvidencePackage(
        case_id="case_001",
        company_name="杭州云启软件有限公司",
        sources=["mock_company_provider"],
        business_scope="公司主要提供软件开发和系统集成服务。",
        snippets=[
            EvidenceSnippet(
                source="mock_company_provider",
                text="公司主要提供软件开发服务。",
                url="https://example.com",
            )
        ],
        quality_score=90,
        errors=[],
    )

    assert package.quality_score == 90
    assert package.snippets[0].text == "公司主要提供软件开发服务。"


def test_category_rule_and_candidate_rule_set_can_be_serialized():
    """候选规则集应该能约束后续 LLM 只能从候选分类里选择。"""
    rule = CategoryRule(
        level1="信软技术服务",
        level2="软件和信息技术",
        level3="软件开发",
        module="业务领域",
        keywords=["软件开发", "系统集成"],
    )
    rule_set = CandidateRuleSet(
        case_id="case_001",
        entered_path_exists=True,
        candidates=[rule],
        retrieval_reason="员工录入分类存在，并命中软件开发关键词。",
    )

    data = rule_set.model_dump()

    assert data["entered_path_exists"] is True
    assert data["candidates"][0]["level3"] == "软件开发"


def test_candidate_rule_set_can_store_level2_category_candidates():
    """候选规则集应该能表达员工细分命中二级分类的情况。"""
    child_rule = CategoryRule(
        level1="卫生和社会工作",
        level2="医院",
        level3="专科医院",
        module="业务领域",
        keywords=["专科医院"],
    )
    candidate = CandidateCategory(
        level1="卫生和社会工作",
        level2="医院",
        granularity="level2",
        matched_entered_value="医院",
        child_count=1,
        children=[child_rule],
        keywords=["医院", "专科医院"],
    )
    rule_set = CandidateRuleSet(
        case_id="case_001",
        entered_path_exists=True,
        candidates=[child_rule],
        category_candidates=[candidate],
        entered_subcategory_granularity="level2",
        granularity_reason="员工录入细分命中二级分类。",
        retrieval_reason="命中二级医院。",
    )

    data = rule_set.model_dump()

    assert data["entered_subcategory_granularity"] == "level2"
    assert data["category_candidates"][0]["level3"] == ""
    assert data["category_candidates"][0]["child_count"] == 1


def test_agent_assessment_has_unified_output_shape():
    """每个 Agent 的输出都应该能记录为统一 assessment。"""
    assessment = AgentAssessment(
        agent_name="evidence_agent",
        status="success",
        confidence=90,
        findings=["采集到强证据"],
        output={"quality_score": 90},
        duration_ms=12.5,
    )

    assert assessment.agent_name == "evidence_agent"
    assert assessment.output["quality_score"] == 90


def test_approval_decision_supports_four_actions():
    """审批结论应该支持四类分流动作。"""
    decision = ApprovalDecision(
        case_id="case_001",
        action="approved",
        status="completed",
        confidence=92,
        risk_score=10,
        reason="证据支持员工录入分类。",
        suggestion="",
        needs_review=False,
    )

    assert decision.action == "approved"
    assert decision.needs_review is False


def test_review_task_can_store_manual_decision():
    """人工复核任务应该能记录人工最终结论。"""
    task = ReviewTask(
        task_id="review_001",
        case_id="case_010",
        priority="high",
        reason="分类不存在，需要人工确认。",
        status="pending",
        reviewer=None,
        final_action=None,
    )

    assert task.status == "pending"
    assert task.final_action is None


def test_current_user_can_check_roles():
    """当前用户上下文应该能判断角色权限。"""
    user = CurrentUser(
        user_id="reviewer_001",
        tenant_id="tenant_a",
        roles=["reviewer"],
    )

    assert user.has_role("reviewer") is True
    assert user.has_any_role({"reviewer", "admin"}) is True
    assert user.has_any_role({"uploader", "auditor"}) is False


def test_quality_score_must_be_between_0_and_100():
    """证据质量分不能超出 0 到 100。"""
    with pytest.raises(ValidationError):
        EvidencePackage(
            case_id="case_001",
            company_name="杭州云启软件有限公司",
            sources=["mock_company_provider"],
            business_scope="公司主要提供软件开发服务。",
            snippets=[],
            quality_score=120,
            errors=[],
        )
