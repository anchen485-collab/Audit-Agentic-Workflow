from app.domain.models import AuditCase, EvidencePackage
from app.infrastructure.evidence_provider import MockCompanyEvidenceProvider


def collect_evidence(
    audit_case: AuditCase,
    provider: MockCompanyEvidenceProvider,
) -> EvidencePackage:
    """为一条审批单采集企业证据。"""
    evidence = provider.fetch(
        case_id=audit_case.case_id,
        company_name=audit_case.company_name,
    )

    return evidence


def has_sufficient_evidence(evidence: EvidencePackage, min_quality_score: int = 60) -> bool:
    """判断证据是否足够支持后续自动审批。"""
    if evidence.quality_score < min_quality_score:
        return False

    if not evidence.business_scope.strip():
        return False

    if not evidence.snippets:
        return False

    return True