from typing import Any

from app.agents.base import AgentExecutionResult, run_agent_step
from app.agents.llm_classification_provider import SemanticClassificationResult
from app.domain.decisions import DecisionAction, DecisionStatus
from app.domain.models import ApprovalDecision, AuditCase, CandidateRuleSet, EvidencePackage


class DecisionVerifier:
    """在自动审批前，用确定性规则再检查一次审批结论。"""

    agent_name = "decision_verifier"

    def run(
        self,
        audit_case: AuditCase,
        evidence: EvidencePackage,
        candidate_rules: CandidateRuleSet,
        classification_result: SemanticClassificationResult,
        decision: ApprovalDecision,
    ) -> AgentExecutionResult[ApprovalDecision]:
        """校验自动通过或自动驳回；校验失败时转人工复核。"""
        fallback_decision = self._send_to_review(decision, ["自动审批校验执行异常。"])

        return run_agent_step(
            agent_name=self.agent_name,
            func=lambda: self._verify(
                audit_case,
                evidence,
                candidate_rules,
                classification_result,
                decision,
            ),
            fallback_value=fallback_decision,
        )

    def _verify(
        self,
        audit_case: AuditCase,
        evidence: EvidencePackage,
        candidate_rules: CandidateRuleSet,
        classification_result: SemanticClassificationResult,
        decision: ApprovalDecision,
    ) -> tuple[ApprovalDecision, list[str], dict[str, Any], int]:
        """只检查自动动作，人工复核和证据不足结论保持原样。"""
        failures = self._find_failures(evidence, candidate_rules, classification_result, decision)
        verified_decision = decision if not failures else self._send_to_review(decision, failures)
        changed = verified_decision.action != decision.action

        findings = ["自动审批校验通过。"] if not failures else failures
        output = {
            "case_id": audit_case.case_id,
            "original_action": decision.action.value,
            "final_action": verified_decision.action.value,
            "verified": not failures,
            "changed": changed,
            "failures": failures,
        }
        return verified_decision, findings, output, verified_decision.confidence

    def _find_failures(
        self,
        evidence: EvidencePackage,
        candidate_rules: CandidateRuleSet,
        classification_result: SemanticClassificationResult,
        decision: ApprovalDecision,
    ) -> list[str]:
        """列出自动动作不满足的条件，方便人工复核时查看。"""
        if decision.action not in {DecisionAction.APPROVED, DecisionAction.REJECTED}:
            return []

        failures = []
        if evidence.quality_score < 60 or not evidence.business_scope.strip() or not evidence.snippets:
            failures.append("自动审批缺少足够的外部证据。")
        if not candidate_rules.entered_path_exists:
            failures.append("员工录入分类不在内部规则库中。")
        if decision.risk_score >= 40:
            failures.append("风险分未达到自动审批要求。")
        if decision.action == DecisionAction.APPROVED and classification_result.result != "supports_entered_category":
            failures.append("语义判断不支持自动通过。")
        if (
            decision.action == DecisionAction.REJECTED
            and classification_result.result != "conflicts_with_entered_category"
        ):
            failures.append("语义判断不支持自动驳回。")
        if not self._matches_candidate_rule(classification_result, candidate_rules):
            failures.append("语义判断没有命中合法的候选分类。")

        return failures

    def _matches_candidate_rule(
        self,
        classification_result: SemanticClassificationResult,
        candidate_rules: CandidateRuleSet,
    ) -> bool:
        """确认 LLM 命中的分类来自 Rule Agent 提供的候选集。"""
        rule_id = classification_result.matched_candidate_rule_id
        if rule_id:
            return rule_id in {f"rule_{index + 1}" for index in range(len(candidate_rules.candidates))}

        if classification_result.matched_category_candidate_ids:
            valid_ids = {
                f"category_{index + 1}"
                for index in range(len(candidate_rules.category_candidates))
            }
            return set(classification_result.matched_category_candidate_ids).issubset(valid_ids)

        return classification_result.matched_path() in {
            (rule.level1, rule.level2, rule.level3)
            for rule in candidate_rules.candidates
        }

    def _send_to_review(self, decision: ApprovalDecision, failures: list[str]) -> ApprovalDecision:
        """把没有通过校验的自动结论降级为人工复核。"""
        reason = "；".join(failures)
        return decision.model_copy(
            update={
                "action": DecisionAction.NEEDS_HUMAN_REVIEW,
                "status": DecisionStatus.PENDING_REVIEW,
                "needs_review": True,
                "reason": f"{decision.reason} 自动审批校验未通过：{reason}，已转人工复核。",
                "suggestion": decision.suggestion or "请人工确认企业主营业务和分类口径。",
            }
        )
