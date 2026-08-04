import json
from pathlib import Path
from typing import Any

from app.domain.models import EvidencePackage, EvidenceSnippet


class MockCompanyEvidenceProvider:
    """mock 企业证据提供器，用本地 JSON 模拟外部数据源。"""

    def __init__(self, evidence_file: str | Path):
        self.evidence_file = Path(evidence_file)
        self.evidence_by_company = self._load_evidence()

    def fetch(self, case_id: str, company_name: str, website_url: str = "") -> EvidencePackage:
        """根据企业名称获取证据包。"""
        raw_evidence = self.evidence_by_company.get(company_name)

        if raw_evidence is None:
            return EvidencePackage(
                case_id=case_id,
                company_name=company_name,
                sources=[],
                business_scope="",
                snippets=[],
                quality_score=0,
                errors=[f"mock 证据库中未找到企业：{company_name}"],
            )

        return EvidencePackage(
            case_id=case_id,
            company_name=company_name,
            sources=raw_evidence.get("sources", []),
            business_scope=raw_evidence.get("business_scope", ""),
            snippets=self._build_snippets(raw_evidence),
            quality_score=raw_evidence.get("quality_score", 0),
            errors=raw_evidence.get("errors", []),
        )

    def _load_evidence(self) -> dict[str, dict[str, Any]]:
        """读取本地 mock 证据文件。"""
        if not self.evidence_file.exists():
            raise FileNotFoundError(f"证据文件不存在：{self.evidence_file}")

        try:
            evidence_data = json.loads(self.evidence_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"证据文件不是合法 JSON：{self.evidence_file}") from error

        if not isinstance(evidence_data, dict):
            raise ValueError("证据文件顶层必须是对象，key 应该是企业名称。")

        return evidence_data

    def _build_snippets(self, raw_evidence: dict[str, Any]) -> list[EvidenceSnippet]:
        """把字符串证据片段转成 EvidenceSnippet 模型。"""
        snippets = []

        for text in raw_evidence.get("snippets", []):
            snippets.append(
                EvidenceSnippet(
                    source="mock_company_provider",
                    text=text,
                    url="",
                )
            )

        return snippets
