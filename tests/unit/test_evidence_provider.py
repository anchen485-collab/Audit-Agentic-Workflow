import json

import pytest

from app.infrastructure.evidence_provider import MockCompanyEvidenceProvider


def test_mock_provider_fetches_company_evidence(tmp_path):
    """mock provider 应该能根据企业名称返回证据包。"""
    evidence_file = tmp_path / "mock_company_evidence.json"
    evidence_file.write_text(
        json.dumps(
            {
                "杭州云启软件有限公司": {
                    "business_scope": "公司主要提供软件开发服务。",
                    "quality_score": 90,
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
    evidence = provider.fetch(
        case_id="case_001",
        company_name="杭州云启软件有限公司",
    )

    assert evidence.case_id == "case_001"
    assert evidence.company_name == "杭州云启软件有限公司"
    assert evidence.quality_score == 90
    assert evidence.snippets[0].text == "提供软件开发服务"


def test_mock_provider_returns_empty_evidence_when_company_not_found(tmp_path):
    """企业不存在时，不应该让流程崩溃，而是返回证据不足。"""
    evidence_file = tmp_path / "mock_company_evidence.json"
    evidence_file.write_text("{}", encoding="utf-8")

    provider = MockCompanyEvidenceProvider(evidence_file)
    evidence = provider.fetch(
        case_id="case_404",
        company_name="不存在的企业",
    )

    assert evidence.quality_score == 0
    assert evidence.business_scope == ""
    assert evidence.errors


def test_mock_provider_rejects_invalid_json(tmp_path):
    """证据文件不是合法 JSON 时，应该抛出清晰错误。"""
    evidence_file = tmp_path / "mock_company_evidence.json"
    evidence_file.write_text("{bad json", encoding="utf-8")

    with pytest.raises(ValueError, match="合法 JSON"):
        MockCompanyEvidenceProvider(evidence_file)