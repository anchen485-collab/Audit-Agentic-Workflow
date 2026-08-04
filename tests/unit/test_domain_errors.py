from app.domain.decisions import DecisionAction
from app.domain.errors import (
    EvidenceUnavailableError,
    LLMInvalidCandidateError,
    LLMInvalidJsonError,
    LLMOutputError,
    LLMProviderAuthError,
    MissingFieldError,
    RuleNotFoundError,
    action_for_error,
)


def test_missing_field_error_goes_to_human_review():
    """字段缺失需要人工确认或补录。"""
    error = MissingFieldError("缺少企业名称")

    assert action_for_error(error) == DecisionAction.NEEDS_HUMAN_REVIEW


def test_evidence_unavailable_error_goes_to_more_evidence():
    """证据采集失败应该进入补证流程。"""
    error = EvidenceUnavailableError("官网无法访问")

    assert action_for_error(error) == DecisionAction.NEEDS_MORE_EVIDENCE


def test_llm_output_error_goes_to_human_review():
    """LLM 输出异常不能自动通过或驳回。"""
    error = LLMOutputError("LLM 返回了非法 JSON")

    assert action_for_error(error) == DecisionAction.NEEDS_HUMAN_REVIEW


def test_rule_not_found_error_goes_to_human_review():
    """分类规则缺失需要人工复核分类口径。"""
    error = RuleNotFoundError("内部分类不存在")

    assert action_for_error(error) == DecisionAction.NEEDS_HUMAN_REVIEW


def test_llm_error_subtypes_have_distinct_error_codes():
    """不同 LLM 错误应该有不同 error_code，方便日志、Excel 和指标区分。"""
    assert LLMInvalidJsonError("bad json").error_code == "llm_invalid_json"
    assert LLMInvalidCandidateError("bad rule").error_code == "llm_invalid_candidate"
    assert LLMProviderAuthError("bad key").error_code == "llm_provider_auth"
