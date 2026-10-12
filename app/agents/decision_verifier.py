from typing import Any

from app.agents.base import AgentExecutionResult, AgentStatus, build_agent_assessment, run_agent_step
from app.agents.llm_classification_provider import SemanticClassificationResult
from app.agents.risk_agent import RiskAssessment, RiskLevel
from app.domain.decisions import DecisionAction, DecisionStatus
from app.domain.models import ApprovalDecision, AuditCase, CandidateRuleSet, EvidencePackage

MIN_EVIDENCE_QUALITY_SCORE = 60
MIN_CLASSIFICATION_CONFIDENCE = 70
MAX_AUTO_RISK_SCORE = 39
AUTO_ACTIONS = frozenset({DecisionAction.APPROVED, DecisionAction.REJECTED})


class DecisionVerifier:
    """在自动审批前，用确定性规则再检查一次审批结论。"""

    agent_name = "decision_verifier"

    def run(
        self,
        audit_case: AuditCase,
        evidence: EvidencePackage,
        candidate_rules: CandidateRuleSet,
        classification_result: SemanticClassificationResult,
        risk_assessment: RiskAssessment,
        decision: ApprovalDecision,
    ) -> AgentExecutionResult[ApprovalDecision]:
        """校验自动通过或自动驳回；校验失败时转人工复核。"""
        if decision.action not in AUTO_ACTIONS:
            output = self._build_output(
                audit_case=audit_case,
                decision=decision,
                final_decision=decision,
                status="skipped",
                failures=[],
            )
            assessment = build_agent_assessment(
                agent_name=self.agent_name,
                status=AgentStatus.SKIPPED,
                confidence=100,
                findings=["当前结论不是自动审批，跳过校验。"],
                output=output,
            )
            return AgentExecutionResult(value=decision, assessment=assessment)

        fallback_decision = self._fallback_decision(decision)

        return run_agent_step(
            agent_name=self.agent_name,
            func=lambda: self._verify(
                audit_case,
                evidence,
                candidate_rules,
                classification_result,
                risk_assessment,
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
        risk_assessment: RiskAssessment,
        decision: ApprovalDecision,
    ) -> tuple[ApprovalDecision, list[str], dict[str, Any], int]:
        """检查自动动作的证据、规则、风险和状态一致性。"""
        failures = self._find_failures(
            audit_case,
            evidence,
            candidate_rules,
            classification_result,
            risk_assessment,
            decision,
        )
        verified_decision = decision if not failures else self._send_to_review(decision, failures)
        findings = ["自动审批校验通过。"] if not failures else failures
        output = self._build_output(
            audit_case=audit_case,
            decision=decision,
            final_decision=verified_decision,
            status="passed" if not failures else "failed",
            failures=failures,
        )
        return verified_decision, findings, output, verified_decision.confidence

    def _find_failures(
        self,
        audit_case: AuditCase,
        evidence: EvidencePackage,
        candidate_rules: CandidateRuleSet,
        classification_result: SemanticClassificationResult,
        risk_assessment: RiskAssessment,
        decision: ApprovalDecision,
    ) -> list[str]:
        """列出自动动作不满足的条件，方便人工复核时查看。"""
        failures: list[str] = []
        case_ids = {
            audit_case.case_id,
            evidence.case_id,
            candidate_rules.case_id,
            risk_assessment.case_id,
            decision.case_id,
        }
        if len(case_ids) > 1:
            failures.append("审批数据的 case_id 不一致。")
        if evidence.company_name.strip() != audit_case.company_name.strip():
            failures.append("证据所属企业与当前审批企业不一致。")
        if (
            evidence.quality_score < MIN_EVIDENCE_QUALITY_SCORE
            or not evidence.business_scope.strip()
            or not evidence.snippets
        ):
            failures.append("自动审批缺少足够的外部证据。")
        if evidence.errors:
            failures.append("外部证据仍包含采集错误。")
        if not candidate_rules.entered_path_exists:
            failures.append("员工录入分类不在内部规则库中。")
        if self._has_abnormal_granularity(candidate_rules):
            failures.append("员工录入分类粒度存在异常。")
        if risk_assessment.risk_level != RiskLevel.LOW or risk_assessment.risk_score > MAX_AUTO_RISK_SCORE:
            failures.append("风险分未达到自动审批要求。")
        if decision.risk_score != risk_assessment.risk_score:
            failures.append("审批结论中的风险分与 Risk Agent 结果不一致。")
        if classification_result.confidence < MIN_CLASSIFICATION_CONFIDENCE:
            failures.append("语义判断置信度未达到自动审批要求。")
        if classification_result.normalization_warning:
            failures.append("语义判断经过了降级处理。")
        if not classification_result.reason.strip():
            failures.append("语义判断缺少可解释原因。")
        if decision.confidence != classification_result.confidence:
            failures.append("审批结论置信度与语义判断不一致。")
        if decision.status != DecisionStatus.COMPLETED or decision.needs_review:
            failures.append("自动审批结论的状态字段不一致。")
        if decision.action == DecisionAction.APPROVED and classification_result.result != "supports_entered_category":
            failures.append("语义判断不支持自动通过。")
        if decision.action == DecisionAction.APPROVED and classification_result.unsupported_entered_values:
            failures.append("仍有员工录入分类未得到证据支持。")
        if (
            decision.action == DecisionAction.REJECTED
            and classification_result.result != "conflicts_with_entered_category"
        ):
            failures.append("语义判断不支持自动驳回。")
        if decision.action == DecisionAction.REJECTED and not self._has_valid_rejection_suggestion(
            decision,
            candidate_rules,
        ):
            failures.append("自动驳回缺少规则库内的建议分类。")
        if not self._matches_candidate_rule(classification_result, candidate_rules):
            failures.append("语义判断没有命中合法的候选分类。")
        if not self._covers_all_level2_candidates(classification_result, candidate_rules, decision):
            failures.append("语义判断没有覆盖全部二级分类候选。")

        return list(dict.fromkeys(failures))

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
            matched_ids = set(classification_result.matched_category_candidate_ids)
            return bool(valid_ids) and matched_ids.issubset(valid_ids)

        candidate_paths = {
            (rule.level1, rule.level2, rule.level3)
            for rule in candidate_rules.candidates
        }
        category_paths = {
            (candidate.level1, candidate.level2, candidate.level3)
            for candidate in candidate_rules.category_candidates
        }
        return classification_result.matched_path() in candidate_paths | category_paths

    def _has_valid_rejection_suggestion(
        self,
        decision: ApprovalDecision,
        candidate_rules: CandidateRuleSet,
    ) -> bool:
        """自动驳回的建议分类必须来自候选规则，避免输出编造分类。"""
        suggestion = decision.suggestion.strip()
        if not suggestion:
            return False

        allowed_paths = {
            " / ".join(part for part in (rule.level1, rule.level2, rule.level3) if part)
            for rule in candidate_rules.candidates
        }
        allowed_paths.update(
            " / ".join(part for part in (candidate.level1, candidate.level2, candidate.level3) if part)
            for candidate in candidate_rules.category_candidates
        )
        return any(path and path in suggestion for path in allowed_paths)

    def _covers_all_level2_candidates(
        self,
        classification_result: SemanticClassificationResult,
        candidate_rules: CandidateRuleSet,
        decision: ApprovalDecision,
    ) -> bool:
        """多二级分类自动通过时，必须明确支持全部候选。"""
        if decision.action != DecisionAction.APPROVED:
            return True
        if candidate_rules.entered_subcategory_granularity != "level2":
            return True

        level2_ids = {
            f"category_{index + 1}"
            for index, candidate in enumerate(candidate_rules.category_candidates)
            if candidate.granularity == "level2"
        }
        if len(level2_ids) <= 1:
            return True

        return level2_ids.issubset(set(classification_result.matched_category_candidate_ids))

    def _has_abnormal_granularity(self, candidate_rules: CandidateRuleSet) -> bool:
        """只在召回结果明确提供粒度诊断时判断异常，兼容旧数据。"""
        has_diagnosis = bool(
            candidate_rules.category_candidates
            or candidate_rules.granularity_reason
            or candidate_rules.unmatched_values
            or candidate_rules.ambiguous_values
        )
        return has_diagnosis and candidate_rules.entered_subcategory_granularity in {
            "mixed",
            "ambiguous",
            "unknown",
        }

    def _build_output(
        self,
        audit_case: AuditCase,
        decision: ApprovalDecision,
        final_decision: ApprovalDecision,
        status: str,
        failures: list[str],
    ) -> dict[str, Any]:
        """生成稳定的结构化校验记录，供 trace、API 和 Excel 复用。"""
        return {
            "case_id": audit_case.case_id,
            "verification_status": status,
            "original_action": decision.action.value,
            "final_action": final_decision.action.value,
            "verified": status == "passed",
            "skipped": status == "skipped",
            "changed": final_decision.action != decision.action,
            "failure_count": len(failures),
            "failures": failures,
        }

    def _fallback_decision(self, decision: ApprovalDecision) -> ApprovalDecision:
        """校验器异常时把自动动作降级为人工复核。"""
        return self._send_to_review(decision, ["自动审批校验执行异常。"])

    def _send_to_review(self, decision: ApprovalDecision, failures: list[str]) -> ApprovalDecision:
        """把没有通过校验的自动结论降级为人工复核。"""
        reason = "；".join(failures)
        return decision.model_copy(
            update={
                "action": DecisionAction.NEEDS_HUMAN_REVIEW,
                "status": DecisionStatus.PENDING_REVIEW,
                "confidence": min(decision.confidence, 60),
                "needs_review": True,
                "reason": f"{decision.reason} 自动审批校验未通过：{reason}，已转人工复核。",
                "suggestion": "请人工确认企业主营业务和分类口径。",
            }
        )
