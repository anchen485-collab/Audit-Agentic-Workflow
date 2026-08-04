from app.agents.classification_agent import classify_audit_case
from app.domain.models import ApprovalDecision, AuditCase, CandidateRuleSet, EvidencePackage


def decide_audit_case(
    audit_case: AuditCase,
    evidence: EvidencePackage,
    candidate_rules: CandidateRuleSet,
) -> ApprovalDecision:
    """审批单决策入口，封装单条审批判断。"""
    return classify_audit_case(
        audit_case=audit_case,
        evidence=evidence,
        candidate_rules=candidate_rules,
    )


def decide_audit_cases(
    cases: list[AuditCase],
    evidence_packages: dict[str, EvidencePackage],
    rule_sets: dict[str, CandidateRuleSet],
) -> list[ApprovalDecision]:
    """批量生成审批结论。"""
    decisions = []

    for audit_case in cases:
        evidence = evidence_packages[audit_case.case_id]
        candidate_rules = rule_sets[audit_case.case_id]

        decisions.append(
            decide_audit_case(
                audit_case=audit_case,
                evidence=evidence,
                candidate_rules=candidate_rules,
            )
        )

    return decisions


def calculate_decision_accuracy(
    decisions: list[ApprovalDecision],
    expected_actions: dict[str, str],
) -> float:
    """计算审批动作准确率。"""
    if not decisions:
        return 0.0

    correct_count = 0

    for decision in decisions:
        if decision.action == expected_actions[decision.case_id]:
            correct_count += 1

    return correct_count / len(decisions)