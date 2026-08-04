from enum import StrEnum
from typing import Any


class DecisionAction(StrEnum):
    """最终审批动作。"""

    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


class DecisionStatus(StrEnum):
    """审批结论状态。"""

    PENDING = "pending"
    COMPLETED = "completed"
    PENDING_REVIEW = "pending_review"
    FAILED = "failed"


class ReviewFinalAction(StrEnum):
    """人工复核允许提交的最终动作。"""

    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    UNABLE_TO_DECIDE = "unable_to_decide"


def needs_manual_review(action: DecisionAction) -> bool:
    """判断某个审批动作是否需要人工继续处理。"""
    return action in {
        DecisionAction.NEEDS_MORE_EVIDENCE,
        DecisionAction.NEEDS_HUMAN_REVIEW,
    }


def decide_final_action(
    evidence: Any,
    candidate_rules: Any,
    semantic_result: Any,
    risk_level: str,
) -> DecisionAction:
    """根据确定性规则生成最终审批动作，LLM 只提供语义判断输入。"""
    if _is_evidence_insufficient(evidence) or semantic_result.result == "insufficient_evidence":
        return DecisionAction.NEEDS_MORE_EVIDENCE

    if not candidate_rules.entered_path_exists:
        return DecisionAction.NEEDS_HUMAN_REVIEW

    if _has_abnormal_granularity(candidate_rules):
        return DecisionAction.NEEDS_HUMAN_REVIEW

    if risk_level == "high":
        return DecisionAction.NEEDS_HUMAN_REVIEW

    if semantic_result.result == "supports_entered_category":
        return DecisionAction.APPROVED

    if semantic_result.result == "conflicts_with_entered_category":
        if _matched_rule_exists(semantic_result, candidate_rules):
            return DecisionAction.REJECTED
        return DecisionAction.NEEDS_HUMAN_REVIEW

    return DecisionAction.NEEDS_HUMAN_REVIEW


def _is_evidence_insufficient(evidence: Any) -> bool:
    """判断证据是否不足以进入自动审批。"""
    return evidence.quality_score < 60 or not evidence.business_scope.strip() or not evidence.snippets


def _matched_rule_exists(semantic_result: Any, candidate_rules: Any) -> bool:
    """判断语义结果中的建议分类是否来自候选规则。"""
    matched_candidate_rule_id = getattr(semantic_result, "matched_candidate_rule_id", "")
    if matched_candidate_rule_id:
        return any(
            matched_candidate_rule_id == f"rule_{index + 1}"
            for index, _ in enumerate(candidate_rules.candidates)
        )

    matched_path = semantic_result.matched_path()
    if not any(matched_path):
        return False

    return any(
        matched_path == (rule.level1, rule.level2, rule.level3)
        for rule in candidate_rules.candidates
    )


def _has_abnormal_granularity(candidate_rules: Any) -> bool:
    """识别新召回流程显式标记的异常细分粒度。"""
    has_explicit_granularity = bool(
        getattr(candidate_rules, "category_candidates", [])
        or getattr(candidate_rules, "granularity_reason", "")
        or getattr(candidate_rules, "unmatched_values", [])
        or getattr(candidate_rules, "ambiguous_values", [])
    )
    if not has_explicit_granularity:
        return False

    return getattr(candidate_rules, "entered_subcategory_granularity", "") in {
        "mixed",
        "ambiguous",
        "unknown",
    }
