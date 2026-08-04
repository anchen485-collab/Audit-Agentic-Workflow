from typing import Any

from app.agents.base import AgentExecutionResult, run_agent_step
from app.domain.models import AuditCase, CandidateRuleSet, CategoryRule
from app.services.rule_retriever import RuleRecallConfig, retrieve_candidate_rules


class RuleAgent:
    """内部分类规则召回 Agent。"""

    agent_name = "rule_agent"

    def __init__(
        self,
        rules: list[CategoryRule],
        limit: int | None = None,
        config: RuleRecallConfig | None = None,
    ):
        self.rules = rules
        self.limit = limit
        self.config = config

    def run(self, audit_case: AuditCase) -> AgentExecutionResult[CandidateRuleSet]:
        """为单条审批单召回候选分类规则。"""
        fallback_rules = CandidateRuleSet(
            case_id=audit_case.case_id,
            entered_path_exists=False,
            candidates=[],
            retrieval_reason="Rule Agent 执行失败，未能召回候选规则。",
        )

        return run_agent_step(
            agent_name=self.agent_name,
            func=lambda: self._retrieve(audit_case),
            fallback_value=fallback_rules,
        )

    def _retrieve(self, audit_case: AuditCase) -> tuple[CandidateRuleSet, list[str], dict[str, Any], int]:
        """执行规则召回，并生成 AgentAssessment 所需信息。"""
        candidate_rules = retrieve_candidate_rules(
            audit_case=audit_case,
            rules=self.rules,
            limit=self.limit,
            config=self.config,
        )
        candidate_count = len(candidate_rules.candidates)
        confidence = self._calculate_confidence(candidate_rules)
        findings = [candidate_rules.retrieval_reason]

        if not candidate_rules.entered_path_exists:
            findings.append("员工录入分类不在内部规则库中。")

        output = {
            "case_id": candidate_rules.case_id,
            "entered_path_exists": candidate_rules.entered_path_exists,
            "candidate_count": candidate_count,
            "entered_subcategory_granularity": candidate_rules.entered_subcategory_granularity,
            "granularity_reason": candidate_rules.granularity_reason,
            "category_candidate_paths": [
                _format_category_candidate_path(candidate)
                for candidate in candidate_rules.category_candidates
            ],
            "unmatched_values": candidate_rules.unmatched_values,
            "ambiguous_values": candidate_rules.ambiguous_values,
            "recall_default_top_k": candidate_rules.recall_default_top_k,
            "recall_max_top_k": candidate_rules.recall_max_top_k,
            "raw_match_count": candidate_rules.raw_match_count,
            "deduped_match_count": candidate_rules.deduped_match_count,
            "exact_match_count": candidate_rules.exact_match_count,
            "truncated": candidate_rules.truncated,
            "candidate_paths": [
                f"{rule.level1} / {rule.level2} / {rule.level3}"
                for rule in candidate_rules.candidates
            ],
            "retrieval_reason": candidate_rules.retrieval_reason,
        }

        return candidate_rules, findings, output, confidence

    def _calculate_confidence(self, candidate_rules: CandidateRuleSet) -> int:
        """根据召回结果给 Rule Agent 一个可解释置信度。"""
        if not candidate_rules.candidates:
            return 30

        if not candidate_rules.entered_path_exists:
            return 60

        return 90


def _format_category_candidate_path(candidate) -> str:
    """格式化二级/三级候选路径，供 API、前端和导出展示。"""
    return " / ".join(part for part in [candidate.level1, candidate.level2, candidate.level3] if part)
