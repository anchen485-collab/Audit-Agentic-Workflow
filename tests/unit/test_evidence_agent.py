from app.agents.evidence_agent import EvidenceAgent
from app.domain.models import AuditCase, EvidencePackage, EvidenceSnippet


class StrongEvidenceProvider:
    """测试用证据源：返回高质量证据。"""

    def fetch(self, case_id: str, company_name: str, website_url: str = "") -> EvidencePackage:
        return EvidencePackage(
            case_id=case_id,
            company_name=company_name,
            sources=["fake"],
            business_scope="Company provides software development and system integration services.",
            snippets=[
                EvidenceSnippet(
                    source="fake",
                    text="The company builds software platforms.",
                    url=website_url,
                )
            ],
            quality_score=90,
            errors=[],
        )


class EmptyEvidenceProvider:
    """测试用证据源：正常执行，但没有找到有效证据。"""

    def fetch(self, case_id: str, company_name: str, website_url: str = "") -> EvidencePackage:
        return EvidencePackage(
            case_id=case_id,
            company_name=company_name,
            sources=[],
            business_scope="",
            snippets=[],
            quality_score=0,
            errors=["not found"],
        )


class BrokenEvidenceProvider:
    """测试用证据源：模拟 provider 运行异常。"""

    def fetch(self, case_id: str, company_name: str, website_url: str = "") -> EvidencePackage:
        raise RuntimeError("provider failed")


def test_evidence_agent_collects_strong_evidence():
    agent = EvidenceAgent(provider=StrongEvidenceProvider())

    result = agent.run(_build_case())

    assert result.value.quality_score == 90
    assert result.assessment.agent_name == "evidence_agent"
    assert result.assessment.status == "success"
    assert result.assessment.confidence == 90
    assert result.assessment.output["sufficient"] is True
    assert result.assessment.output["snippet_count"] == 1


def test_evidence_agent_marks_insufficient_evidence_without_failed_status():
    agent = EvidenceAgent(provider=EmptyEvidenceProvider())

    result = agent.run(_build_case())

    assert result.value.quality_score == 0
    assert result.assessment.status == "success"
    assert result.assessment.output["sufficient"] is False
    assert result.assessment.output["errors"] == ["not found"]


def test_evidence_agent_returns_fallback_when_provider_failed():
    agent = EvidenceAgent(provider=BrokenEvidenceProvider())

    result = agent.run(_build_case())

    assert result.value.quality_score == 0
    assert result.assessment.status == "failed"
    assert result.assessment.confidence == 0
    assert "provider failed" in result.assessment.output["error"]


def _build_case() -> AuditCase:
    return AuditCase(
        case_id="case_001",
        batch_id="batch_001",
        row_number=2,
        employee_name="Alice",
        company_raw="Acme Software https://example.com",
        company_name="Acme Software",
        website_url="https://example.com",
        entered_level1="Software",
        entered_subcategory="Software Development",
        entered_stage="input",
        status="pending",
    )
