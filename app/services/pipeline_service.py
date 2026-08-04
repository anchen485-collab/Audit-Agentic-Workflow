from typing import Protocol

from app.agents.classification_agent import classify_audit_case
from app.domain.models import (
    ApprovalDecision,
    AuditCase,
    CandidateRuleSet,
    CategoryRule,
    EvidencePackage,
    PipelineResult,
    ReviewTask,
)
from app.services.decision_service import calculate_decision_accuracy
from app.services.review_service import calculate_review_metrics, create_review_tasks
from app.services.rule_retriever import retrieve_candidate_rules


#Protocol 只要某个对象有 fetch(case_id, company_name) 方法，它就可以作为 evidence_provider 传进 pipeline。
class EvidenceProvider(Protocol):
    """证据提供器协议，方便后续替换 mock provider 或真实爬虫 provider。"""

    def fetch(self, case_id: str, company_name: str) -> EvidencePackage:
        """获取企业证据包。"""


def run_audit_pipeline(
    cases: list[AuditCase],
    rules: list[CategoryRule],
    evidence_provider: EvidenceProvider,
    expected_actions: dict[str, str] | None = None,
) -> PipelineResult:
    """执行一批审批单的完整审批流水线。"""
    rule_sets: dict[str, CandidateRuleSet] = {}
    evidence_packages: dict[str, EvidencePackage] = {}
    decisions: list[ApprovalDecision] = []

    for audit_case in cases:
        candidate_rules = retrieve_candidate_rules(
            audit_case=audit_case,
            rules=rules,
        )
        evidence = evidence_provider.fetch(
            case_id=audit_case.case_id,
            company_name=audit_case.company_name,
        )
        decision = classify_audit_case(
            audit_case=audit_case,
            evidence=evidence,
            candidate_rules=candidate_rules,
        )

        #把检索到的规则和证据包给存下来，方便后续导出、追踪和人工复核。
        rule_sets[audit_case.case_id] = candidate_rules
        evidence_packages[audit_case.case_id] = evidence
        decisions.append(decision)

    review_tasks = create_review_tasks(decisions)
    metrics = _build_pipeline_metrics(decisions, review_tasks, expected_actions)

    return PipelineResult(
        cases=cases,
        rule_sets=rule_sets,
        evidence_packages=evidence_packages,
        decisions=decisions,
        review_tasks=review_tasks,
        metrics=metrics,
    )


def _build_pipeline_metrics(
    decisions: list[ApprovalDecision],
    review_tasks: list[ReviewTask],
    expected_actions: dict[str, str] | None,
) -> dict[str, float | int]:
    """汇总审批流水线指标。"""
    review_metrics = calculate_review_metrics(decisions)

    metrics: dict[str, float | int] = {
        **review_metrics,
        "decision_count": len(decisions),
        "review_task_count": len(review_tasks),
    }

    if expected_actions is not None:
        metrics["accuracy"] = calculate_decision_accuracy(
            decisions=decisions,
            expected_actions=expected_actions,
        )

    return metrics
