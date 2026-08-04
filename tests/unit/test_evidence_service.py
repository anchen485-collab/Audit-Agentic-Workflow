import json

from app.domain.models import AuditCase, EvidencePackage, EvidenceSnippet
from app.infrastructure.evidence_provider import MockCompanyEvidenceProvider
from app.services.evidence_service import collect_evidence, has_sufficient_evidence


def test_collect_evidence_for_audit_case(tmp_path):
    """evidence service 应该能为审批单生成证据包。"""
    evidence_file = tmp_path / "mock_company_evidence.json"
    evidence_file.write_text(
        json.dumps(
            {
                "杭州云启软件有限公司": {
                    "business_scope": "公司主要提供软件开发服务。",
                    "quality_score": 92,
                    "sources": ["mock_company_provider"],
                    "snippets": ["提供软件开发服务"],
                    "errors": [],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    provider = MockCompanyEvidenceProvider(evidence_file)
    audit_case = AuditCase(
        case_id="case_001",
        batch_id="batch_001",
        row_number=2,
        employee_name="张三",
        company_raw="杭州云启软件有限公司 https://yunqi.example.com",
        company_name="杭州云启软件有限公司",
        website_url="https://yunqi.example.com",
        entered_level1="信软技术服务",
        entered_subcategory="软件开发",
        entered_stage="录入",
        status="pending",
    )

    evidence = collect_evidence(audit_case, provider)

    assert evidence.case_id == "case_001"
    assert evidence.company_name == "杭州云启软件有限公司"
    assert evidence.quality_score == 92


def test_has_sufficient_evidence_accepts_high_quality_evidence():
    """高质量且有业务文本的证据，应该被认为证据充足。"""
    evidence = EvidencePackage(
        case_id="case_001",
        company_name="杭州云启软件有限公司",
        sources=["mock_company_provider"],
        business_scope="公司主要提供软件开发服务。",
        snippets=[
            EvidenceSnippet(
                source="mock_company_provider",
                text="提供软件开发服务",
                url="",
            )
        ],
        quality_score=92,
        errors=[],
    )

    assert has_sufficient_evidence(evidence) is True


def test_has_sufficient_evidence_rejects_low_quality_evidence():
    """质量分过低时，应该被认为证据不足。"""
    evidence = EvidencePackage(
        case_id="case_008",
        company_name="成都青禾生态农业有限公司",
        sources=["mock_company_provider"],
        business_scope="首页 导航 联系我们 新闻动态 版权所有",
        snippets=[],
        quality_score=15,
        errors=["官网文本清洗后无有效业务证据"],
    )

    assert has_sufficient_evidence(evidence) is False