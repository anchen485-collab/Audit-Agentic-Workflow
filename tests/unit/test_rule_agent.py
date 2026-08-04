from app.agents.rule_agent import RuleAgent
from app.domain.models import AuditCase, CategoryRule


def test_rule_agent_returns_candidate_rules_and_assessment():
    agent = RuleAgent(rules=[_software_rule()])

    result = agent.run(_build_case())

    assert result.value.case_id == "case_001"
    assert result.value.entered_path_exists is True
    assert len(result.value.candidates) == 1
    assert result.assessment.agent_name == "rule_agent"
    assert result.assessment.status == "success"
    assert result.assessment.output["candidate_count"] == 1
    assert result.assessment.output["entered_path_exists"] is True
    assert result.assessment.output["raw_match_count"] == 1
    assert result.assessment.output["deduped_match_count"] == 1
    assert result.assessment.output["exact_match_count"] == 1
    assert result.assessment.output["truncated"] is False
    assert result.assessment.output["candidate_paths"] == [
        "Software / Information Technology / Software Development",
    ]


def test_rule_agent_marks_missing_entered_path_as_successful_business_result():
    agent = RuleAgent(rules=[_software_rule()])
    audit_case = _build_case(entered_level1="Unknown", entered_subcategory="Unknown Category")

    result = agent.run(audit_case)

    assert result.assessment.status == "success"
    assert result.value.entered_path_exists is False
    assert result.assessment.output["entered_path_exists"] is False


def test_rule_agent_uses_default_top_five_dynamic_recall():
    """RuleAgent 默认使用动态 Top5，不再硬编码 Top3。"""
    agent = RuleAgent(
        rules=[
            CategoryRule(
                level1="Software",
                level2=f"Information Technology {index}",
                level3=f"Software Development {index}",
                module="business",
                keywords=["software"],
            )
            for index in range(1, 6)
        ]
    )

    result = agent.run(_build_case())

    assert result.assessment.output["candidate_count"] == 5
    assert result.value.recall_default_top_k == 5


def _build_case(
    entered_level1: str = "Software",
    entered_subcategory: str = "Software Development",
) -> AuditCase:
    return AuditCase(
        case_id="case_001",
        batch_id="batch_001",
        row_number=2,
        employee_name="Alice",
        company_raw="Acme Software",
        company_name="Acme Software",
        website_url="",
        entered_level1=entered_level1,
        entered_subcategory=entered_subcategory,
        entered_stage="input",
        status="pending",
    )


def _software_rule() -> CategoryRule:
    return CategoryRule(
        level1="Software",
        level2="Information Technology",
        level3="Software Development",
        module="business",
        keywords=["software", "platform"],
    )
