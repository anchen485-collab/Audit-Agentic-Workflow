from inspect import signature
from typing import Any, Protocol

from app.agents.base import AgentExecutionResult, run_agent_step
from app.domain.models import AuditCase, EvidencePackage


class EvidenceProvider(Protocol):
    """证据提供器协议，mock provider 和真实爬虫 provider 都可以实现它。"""

    def fetch(self, case_id: str, company_name: str, website_url: str = "") -> EvidencePackage:
        """获取企业证据包。"""


class EvidenceAgent:
    """企业外部证据采集 Agent。"""

    agent_name = "evidence_agent"

    def __init__(self, provider: EvidenceProvider, min_quality_score: int = 60):
        self.provider = provider
        self.min_quality_score = min_quality_score

    def run(self, audit_case: AuditCase) -> AgentExecutionResult[EvidencePackage]:
        """采集单条审批单的企业外部证据。"""
        fallback_evidence = EvidencePackage(
            case_id=audit_case.case_id,
            company_name=audit_case.company_name,
            sources=[],
            business_scope="",
            snippets=[],
            quality_score=0,
            errors=["Evidence Agent 执行失败，未能采集到有效证据。"],
        )

        return run_agent_step(
            agent_name=self.agent_name,
            func=lambda: self._collect(audit_case),
            fallback_value=fallback_evidence,
        )

    def _collect(
        self,
        audit_case: AuditCase,
    ) -> tuple[EvidencePackage, list[str], dict[str, Any], int]:
        """执行真实证据采集，并生成 assessment 所需信息。"""
        evidence = self._fetch_evidence(audit_case)

        sufficient = self._has_sufficient_evidence(evidence)
        confidence = self._calculate_confidence(evidence)

        findings = self._build_findings(evidence, sufficient)

        output = {
            "case_id": evidence.case_id,
            "company_name": evidence.company_name,
            "sources": evidence.sources,
            "source_count": len(evidence.sources),
            "snippet_count": len(evidence.snippets),
            "quality_score": evidence.quality_score,
            "has_business_scope": bool(evidence.business_scope.strip()),
            "sufficient": sufficient,
            "errors": evidence.errors,
        }

        return evidence, findings, output, confidence

    def _fetch_evidence(self, audit_case: AuditCase) -> EvidencePackage:
        """兼容 mock provider 和真实官网 provider 的 fetch 参数。"""
        fetch_parameters = signature(self.provider.fetch).parameters

        if "website_url" in fetch_parameters:
            return self.provider.fetch(
                case_id=audit_case.case_id,
                company_name=audit_case.company_name,
                website_url=audit_case.website_url,
            )

        return self.provider.fetch(
            case_id=audit_case.case_id,
            company_name=audit_case.company_name,
        )

    def _has_sufficient_evidence(self, evidence: EvidencePackage) -> bool:
        """判断证据是否足够进入后续自动审批。"""
        if evidence.quality_score < self.min_quality_score:
            return False

        if not evidence.business_scope.strip():
            return False

        if not evidence.snippets:
            return False

        return True

    def _calculate_confidence(self, evidence: EvidencePackage) -> int:
        """根据证据质量计算 Evidence Agent 的置信度。"""
        if evidence.errors:
            return min(evidence.quality_score, 50)

        return evidence.quality_score

    def _build_findings(
        self,
        evidence: EvidencePackage,
        sufficient: bool,
    ) -> list[str]:
        """生成给 trace 和人工审核看的发现信息。"""
        findings = []

        if evidence.business_scope.strip():
            findings.append(f"采集到企业业务描述：{evidence.business_scope}")

        if evidence.sources:
            findings.append(f"证据来源数量：{len(evidence.sources)}")

        if evidence.snippets:
            findings.append(f"证据片段数量：{len(evidence.snippets)}")

        if not sufficient:
            findings.append("证据不足，后续应谨慎自动审批。")

        if evidence.errors:
            findings.extend(evidence.errors)

        return findings
