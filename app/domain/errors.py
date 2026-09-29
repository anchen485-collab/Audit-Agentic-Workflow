from app.domain.decisions import DecisionAction


class AuditError(Exception):
    """审批业务错误基类。"""

    def __init__(self, message: str, error_code: str):
        super().__init__(message)
        self.message = message
        self.error_code = error_code


class MissingFieldError(AuditError):
    """员工录入缺少必填字段。"""

    def __init__(self, message: str):
        super().__init__(message, "missing_field")


class EvidenceUnavailableError(AuditError):
    """外部证据不可用，例如官网缺失、访问失败、证据为空。"""

    def __init__(self, message: str):
        super().__init__(message, "evidence_unavailable")


class LLMOutputError(AuditError):
    """LLM 输出异常，例如不是 JSON、字段缺失、编造分类。"""

    def __init__(self, message: str, error_code: str = "llm_output_error"):
        super().__init__(message, error_code)


class LLMInvalidJsonError(LLMOutputError):
    """LLM 返回内容不是合法 JSON。"""

    def __init__(self, message: str):
        super().__init__(message, "llm_invalid_json")


class LLMInvalidCandidateError(LLMOutputError):
    """LLM 返回了候选规则之外的分类或候选规则 ID。"""

    def __init__(self, message: str):
        super().__init__(message, "llm_invalid_candidate")


class LLMProviderAuthError(LLMOutputError):
    """LLM 服务认证或权限配置错误。"""

    def __init__(self, message: str):
        super().__init__(message, "llm_provider_auth")


class RuleNotFoundError(AuditError):
    """内部分类规则不存在或召回失败。"""

    def __init__(self, message: str):
        super().__init__(message, "rule_not_found")


class CaseRetryNotFoundError(AuditError):
    """需要重试的审批单或批次不存在。"""

    def __init__(self, message: str):
        super().__init__(message, "case_retry_not_found")


class CaseRetryConflictError(AuditError):
    """审批单已有人工最终结论，不能再由自动重试覆盖。"""

    def __init__(self, message: str):
        super().__init__(message, "case_retry_conflict")


class CaseRetryInProgressError(AuditError):
    """同一审批单已经有一个重试正在执行。"""

    def __init__(self, message: str):
        super().__init__(message, "case_retry_in_progress")


class CaseRetryIdempotencyError(AuditError):
    """同一个幂等键对应的重试状态不允许再次执行。"""

    def __init__(self, message: str):
        super().__init__(message, "case_retry_idempotency_conflict")


def action_for_error(error: AuditError) -> DecisionAction:
    """把业务错误映射为审批动作，避免异常直接打断整批流程。"""
    if isinstance(error, EvidenceUnavailableError):
        return DecisionAction.NEEDS_MORE_EVIDENCE

    return DecisionAction.NEEDS_HUMAN_REVIEW
