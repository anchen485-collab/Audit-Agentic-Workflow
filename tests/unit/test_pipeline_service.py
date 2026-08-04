from app.domain.models import AuditCase, CategoryRule, EvidencePackage, EvidenceSnippet
from app.services.pipeline_service import run_audit_pipeline


class FakeEvidenceProvider:
    """测试用证据提供器。"""

    def fetch(self, case_id: str, company_name: str) -> EvidencePackage:
        return EvidencePackage(
            case_id=case_id,
            company_name=company_name,
            sources=["fake"],
            business_scope="公司主要提供软件开发和系统集成服务。",
            snippets=[
                EvidenceSnippet(
                    source="fake",
                    text="提供软件开发服务",
                    url="",
                )
            ],
            quality_score=90,
            errors=[],
        )


def test_run_audit_pipeline_returns_decisions_and_metrics():
    """审批流水线应该能返回审批结论、复核任务和统计指标。"""
    cases = [
        AuditCase(
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
    ]
    rules = [
        CategoryRule(
            level1="信软技术服务",
            level2="软件和信息技术",
            level3="软件开发",
            module="业务领域",
            keywords=["软件开发", "系统集成"],
        )
    ]

    result = run_audit_pipeline(
        cases=cases,
        rules=rules,
        evidence_provider=FakeEvidenceProvider(),
        expected_actions={"case_001": "approved"},
    )

    assert len(result.cases) == 1
    assert len(result.decisions) == 1
    assert result.decisions[0].case_id == "case_001"
    assert result.metrics["decision_count"] == 1
    assert result.metrics["accuracy"] == 1.0
    assert result.metrics["review_task_count"] == 0