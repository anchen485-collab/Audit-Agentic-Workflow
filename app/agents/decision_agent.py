from typing import Any

from app.agents.base import AgentExecutionResult, run_agent_step
from app.agents.classification_agent import build_insufficient_evidence_reason
from app.agents.llm_classification_provider import SemanticClassificationResult
from app.agents.risk_agent import RiskAssessment, RiskLevel
from app.domain.decisions import DecisionAction, DecisionStatus, decide_final_action
from app.domain.models import ApprovalDecision, AuditCase, CandidateRuleSet, EvidencePackage


class DecisionAgent:
    """最终审批决策 Agent。"""

    agent_name = "decision_agent"

    def run(
        self,
        audit_case: AuditCase,
        evidence: EvidencePackage,
        candidate_rules: CandidateRuleSet,
        classification_result: SemanticClassificationResult,
        risk_assessment: RiskAssessment,
    ) -> AgentExecutionResult[ApprovalDecision]:
        """根据语义判断和风险评估生成最终审批动作。"""
        fallback_decision = ApprovalDecision(
            case_id=audit_case.case_id,
            action=DecisionAction.NEEDS_HUMAN_REVIEW,
            status=DecisionStatus.PENDING_REVIEW,
            confidence=0,
            risk_score=100,
            reason="Decision Agent 执行失败，默认转入人工复核。",
            suggestion="请人工审核该记录。",
            needs_review=True,
        )

        return run_agent_step(
            agent_name=self.agent_name,
            func=lambda: self._decide(audit_case, evidence, candidate_rules, classification_result, risk_assessment),
            fallback_value=fallback_decision,
        )

    def _decide(
        self,
        audit_case: AuditCase,
        evidence: EvidencePackage,
        candidate_rules: CandidateRuleSet,
        classification_result: SemanticClassificationResult,
        risk_assessment: RiskAssessment,
    ) -> tuple[ApprovalDecision, list[str], dict[str, Any], int]:
        """执行最终审批决策。"""
        action = self._final_action(evidence, candidate_rules, classification_result, risk_assessment)
        needs_review = action in {
            DecisionAction.NEEDS_MORE_EVIDENCE,
            DecisionAction.NEEDS_HUMAN_REVIEW,
        }
        status = DecisionStatus.PENDING_REVIEW if needs_review else DecisionStatus.COMPLETED

        decision = ApprovalDecision(
            case_id=audit_case.case_id,
            action=action,
            status=status,
            confidence=classification_result.confidence,
            risk_score=risk_assessment.risk_score,
            reason=self._build_reason(evidence, classification_result, risk_assessment, action),
            suggestion=self._build_suggestion(classification_result, candidate_rules, action),
            needs_review=needs_review,
        )

        findings = [
            f"最终动作：{decision.action.value}",
            f"风险等级：{risk_assessment.risk_level.value}",
            decision.reason,
        ]

        return decision, findings, decision.model_dump(mode="json"), decision.confidence

    def _final_action(
        self,
        evidence: EvidencePackage,
        candidate_rules: CandidateRuleSet,
        classification_result: SemanticClassificationResult,
        risk_assessment: RiskAssessment,
    ) -> DecisionAction:
        """把语义判断和风险分层合并为最终动作。"""
        return decide_final_action(
            evidence=evidence,
            candidate_rules=candidate_rules,
            semantic_result=classification_result,
            risk_level=risk_assessment.risk_level.value,
        )

    def _build_reason(
        self,
        evidence: EvidencePackage,
        classification_result: SemanticClassificationResult,
        risk_assessment: RiskAssessment,
        action: DecisionAction,
    ) -> str:
        """生成最终审批原因。"""
        if action == DecisionAction.NEEDS_MORE_EVIDENCE:
            return build_insufficient_evidence_reason(evidence)

        if action == DecisionAction.NEEDS_HUMAN_REVIEW and risk_assessment.risk_level == RiskLevel.HIGH:
            return f"{classification_result.reason} 风险等级为 {risk_assessment.risk_level.value}，需要人工复核。"

        return classification_result.reason

    def _build_suggestion(
        self,
        classification_result: SemanticClassificationResult,
        candidate_rules: CandidateRuleSet,
        action: DecisionAction,
    ) -> str:
        """生成处理建议，分类建议必须来自候选规则。"""
        if action == DecisionAction.REJECTED:
            matched_rule = self._matched_rule(classification_result, candidate_rules)
            if matched_rule:
                return f"建议调整为：{matched_rule.level1} / {matched_rule.level2} / {matched_rule.level3}"

        return classification_result.suggestion or self._default_suggestion(action)

    def _matched_rule(self, classification_result: SemanticClassificationResult, candidate_rules: CandidateRuleSet):
        """从候选规则中找到 LLM 选择的分类。"""
        if classification_result.matched_candidate_rule_id:
            for index, rule in enumerate(candidate_rules.candidates):
                if classification_result.matched_candidate_rule_id == f"rule_{index + 1}":
                    return rule

        matched_path = classification_result.matched_path()
        for rule in candidate_rules.candidates:
            if matched_path == (rule.level1, rule.level2, rule.level3):
                return rule

        return None

    def _default_suggestion(self, action: DecisionAction) -> str:
        """为没有建议文本的决策补充默认建议。"""
        if action == DecisionAction.NEEDS_MORE_EVIDENCE:
            return "请补充企业官网或有效业务介绍。"

        if action == DecisionAction.NEEDS_HUMAN_REVIEW:
            return "请人工确认企业主营业务和分类口径。"

        return ""
