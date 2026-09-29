"""单条审批单重试：幂等、互斥、可审计地复用完整工作流。"""

import re
from typing import Any

from app.agents.evidence_agent import EvidenceProvider
from app.agents.llm_classification_provider import ClassificationProvider
from app.domain.errors import AuditError
from app.domain.models import ApprovalDecision, AuditCase, CategoryRule, ReviewTask
from app.infrastructure.batch_repository import (
    CaseRetryAttemptContext,
    begin_case_retry_attempt,
    cache_case_retry_response,
    fail_case_retry_attempt,
    get_decision_payload,
    list_decision_payloads,
    list_review_task_payloads_by_batch,
    replace_case_after_retry,
)
from app.infrastructure.settings import Settings
from app.observability.metrics import calculate_audit_metrics
from app.observability.trace import new_trace_id
from app.services.review_service import create_review_task
from app.workflow.audit_workflow import build_audit_workflow

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def retry_audit_case(
    batch_id: str,
    case_id: str,
    tenant_id: str | None,
    retried_by: str,
    idempotency_key: str,
    rules: list[CategoryRule],
    evidence_provider: EvidenceProvider,
    classification_provider: ClassificationProvider,
    settings: Settings,
) -> dict[str, Any]:
    """重新执行一条审批单；重复请求只回放第一次成功结果。"""
    normalized_key = _validate_idempotency_key(idempotency_key)
    attempt = begin_case_retry_attempt(
        database_path=settings.database_path,
        batch_id=batch_id,
        case_id=case_id,
        tenant_id=tenant_id,
        idempotency_key=normalized_key,
        retried_by=retried_by,
        retry_trace_id=new_trace_id(),
        lock_timeout_seconds=settings.case_retry_lock_timeout_seconds,
    )
    if attempt.idempotent_replay:
        return _replay_retry_response(attempt=attempt, settings=settings)

    try:
        audit_case = AuditCase.model_validate(attempt.case_payload)
        if audit_case.status == "invalid":
            raise ValueError("该审批单缺少必填字段，请先修正原始 Excel 后重新上传。")

        workflow_result = _run_single_case_workflow(
            audit_case=audit_case,
            rules=rules,
            evidence_provider=evidence_provider,
            classification_provider=classification_provider,
            settings=settings,
            retry_trace_id=attempt.retry_trace_id,
        )
        decision = workflow_result["decisions"][0]
        review_task = create_review_task(decision)
        case_assessments = workflow_result.get("assessments", {}).get(case_id, [])
        metrics = replace_case_after_retry(
            database_path=settings.database_path,
            attempt_id=attempt.attempt_id,
            batch_id=batch_id,
            case_id=case_id,
            tenant_id=attempt.tenant_id,
            decision=decision.model_dump(mode="json"),
            evidence_package=workflow_result["evidence_packages"][case_id].model_dump(mode="json"),
            assessments=[assessment.model_dump(mode="json") for assessment in case_assessments],
            review_task=review_task.model_dump(mode="json") if review_task else None,
            retry_trace_id=attempt.retry_trace_id,
            retried_by=retried_by,
        )
        all_review_tasks = _load_review_tasks(batch_id=batch_id, settings=settings)
        response = _build_retry_response(
            attempt=attempt,
            decision=decision,
            review_task=review_task,
            all_review_tasks=all_review_tasks,
            metrics=metrics,
            idempotent_replay=False,
        )
        cache_case_retry_response(settings.database_path, attempt.attempt_id, response)
        return response
    except Exception as error:
        error_code, error_message = _retry_failure_details(error)
        fail_case_retry_attempt(
            database_path=settings.database_path,
            attempt_id=attempt.attempt_id,
            error_code=error_code,
            error_message=error_message,
        )
        raise


def _run_single_case_workflow(
    audit_case: AuditCase,
    rules: list[CategoryRule],
    evidence_provider: EvidenceProvider,
    classification_provider: ClassificationProvider,
    settings: Settings,
    retry_trace_id: str,
) -> dict[str, Any]:
    """构造单 case 状态并执行与首次审批相同的工作流。"""
    return build_audit_workflow().invoke(
        {
            "cases": [audit_case],
            "rules": rules,
            "evidence_provider": evidence_provider,
            "classification_provider": classification_provider,
            "evidence_concurrency": settings.evidence_concurrency,
            "classification_concurrency": settings.classification_concurrency,
            "rule_concurrency": settings.rule_concurrency,
            "rule_recall_default_top_k": settings.rule_recall_default_top_k,
            "rule_recall_max_top_k": settings.rule_recall_max_top_k,
            "rule_recall_exact_match_score_threshold": settings.rule_recall_exact_match_score_threshold,
            "lightweight_agent_concurrency": settings.lightweight_agent_concurrency,
            "trace_id": retry_trace_id,
            "trace_events": [],
            "assessments": {},
        }
    )


def _replay_retry_response(attempt: CaseRetryAttemptContext, settings: Settings) -> dict[str, Any]:
    """返回相同幂等键第一次成功的响应，不再次调用 Agent 或外部服务。"""
    if attempt.cached_response is not None:
        return {**attempt.cached_response, "idempotent_replay": True}

    decision_payload = get_decision_payload(
        settings.database_path,
        batch_id=attempt.batch_id,
        case_id=attempt.case_id,
        tenant_id=attempt.tenant_id,
    )
    if decision_payload is None:
        raise RuntimeError("重试已完成，但当前审批结论缺失。")

    decision = ApprovalDecision.model_validate(decision_payload)
    all_review_tasks = _load_review_tasks(batch_id=attempt.batch_id, settings=settings)
    review_task = next((task for task in all_review_tasks if task.case_id == attempt.case_id), None)
    all_decisions = [
        ApprovalDecision.model_validate(payload)
        for payload in list_decision_payloads(settings.database_path, attempt.batch_id)
    ]
    metrics = calculate_audit_metrics(decisions=all_decisions, review_tasks=all_review_tasks)
    response = _build_retry_response(
        attempt=attempt,
        decision=decision,
        review_task=review_task,
        all_review_tasks=all_review_tasks,
        metrics=metrics,
        idempotent_replay=True,
    )
    cache_case_retry_response(settings.database_path, attempt.attempt_id, response)
    return response


def _build_retry_response(
    attempt: CaseRetryAttemptContext,
    decision: ApprovalDecision,
    review_task: ReviewTask | None,
    all_review_tasks: list[ReviewTask],
    metrics: dict[str, float | int],
    idempotent_replay: bool,
) -> dict[str, Any]:
    return {
        "batch_id": attempt.batch_id,
        "case_id": attempt.case_id,
        "attempt_id": attempt.attempt_id,
        "idempotency_key": attempt.idempotency_key,
        "idempotent_replay": idempotent_replay,
        "retry_trace_id": attempt.retry_trace_id,
        "previous_action": attempt.previous_action,
        "decision": decision.model_dump(mode="json"),
        "review_task": review_task.model_dump(mode="json") if review_task else None,
        "review_tasks": [task.model_dump(mode="json") for task in all_review_tasks],
        "metrics": metrics,
    }


def _load_review_tasks(batch_id: str, settings: Settings) -> list[ReviewTask]:
    return [
        ReviewTask.model_validate(payload)
        for payload in list_review_task_payloads_by_batch(settings.database_path, batch_id)
    ]


def _validate_idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(normalized):
        raise ValueError("Idempotency-Key 必须为 8-128 位，只能包含字母、数字、点、下划线、冒号和中划线。")
    return normalized


def _retry_failure_details(error: Exception) -> tuple[str, str]:
    """审计记录保留可排查的错误类型，但不向查询接口写入底层异常或密钥。"""
    if isinstance(error, AuditError):
        return error.error_code, error.message
    return error.__class__.__name__, "重试执行失败，详细错误请查看服务端日志。"
