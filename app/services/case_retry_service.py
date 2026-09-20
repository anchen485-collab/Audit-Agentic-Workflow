"""单条审批单重试：复用完整工作流，但只替换当前 case 的运行结果。"""

from typing import Any

from app.agents.evidence_agent import EvidenceProvider
from app.agents.llm_classification_provider import ClassificationProvider
from app.domain.errors import CaseRetryConflictError, CaseRetryNotFoundError
from app.domain.models import ApprovalDecision, AuditCase, CategoryRule, ReviewTask
from app.infrastructure.batch_repository import (
    get_case_payload,
    get_decision_payload,
    list_decision_payloads,
    list_review_task_payloads_by_batch,
    replace_case_after_retry,
    update_batch_decision_metrics,
)
from app.infrastructure.settings import Settings
from app.observability.metrics import calculate_audit_metrics
from app.observability.trace import new_trace_id
from app.services.review_service import create_review_task
from app.workflow.audit_workflow import build_audit_workflow


def retry_audit_case(
    batch_id: str,
    case_id: str,
    tenant_id: str,
    retried_by: str,
    rules: list[CategoryRule],
    evidence_provider: EvidenceProvider,
    classification_provider: ClassificationProvider,
    settings: Settings,
) -> dict[str, Any]:
    """重新执行一条已持久化审批单，并同步其当前结论、复核任务和结果文件状态。"""
    case_payload = get_case_payload(
        settings.database_path,
        batch_id=batch_id,
        case_id=case_id,
        tenant_id=tenant_id,
    )
    previous_decision = get_decision_payload(
        settings.database_path,
        batch_id=batch_id,
        case_id=case_id,
        tenant_id=tenant_id,
    )
    if case_payload is None or previous_decision is None:
        raise CaseRetryNotFoundError("未找到指定批次中的审批单。")

    if previous_decision.get("manual_final_action"):
        raise CaseRetryConflictError("该审批单已有人工最终结论，重试不会覆盖人工审核结果。")

    audit_case = AuditCase.model_validate(case_payload)
    if audit_case.status == "invalid":
        raise ValueError("该审批单缺少必填字段，请先修正原始 Excel 后重新上传。")

    retry_trace_id = new_trace_id()
    result = build_audit_workflow().invoke(
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
    decision = result["decisions"][0]
    review_task = create_review_task(decision)
    case_assessments = result.get("assessments", {}).get(case_id, [])

    replace_case_after_retry(
        database_path=settings.database_path,
        batch_id=batch_id,
        case_id=case_id,
        tenant_id=tenant_id,
        decision=decision.model_dump(mode="json"),
        evidence_package=result["evidence_packages"][case_id].model_dump(mode="json"),
        assessments=[assessment.model_dump(mode="json") for assessment in case_assessments],
        review_task=review_task.model_dump(mode="json") if review_task else None,
        retry_trace_id=retry_trace_id,
        retried_by=retried_by,
    )

    all_decisions = [
        ApprovalDecision.model_validate(payload)
        for payload in list_decision_payloads(settings.database_path, batch_id)
    ]
    all_review_tasks = [
        ReviewTask.model_validate(payload)
        for payload in list_review_task_payloads_by_batch(settings.database_path, batch_id)
    ]
    metrics = calculate_audit_metrics(decisions=all_decisions, review_tasks=all_review_tasks)
    update_batch_decision_metrics(
        database_path=settings.database_path,
        batch_id=batch_id,
        tenant_id=tenant_id,
        metrics=metrics,
    )

    return {
        "batch_id": batch_id,
        "case_id": case_id,
        "retry_trace_id": retry_trace_id,
        "previous_action": previous_decision.get("action", ""),
        "decision": decision.model_dump(mode="json"),
        "review_task": review_task.model_dump(mode="json") if review_task else None,
        "review_tasks": [task.model_dump(mode="json") for task in all_review_tasks],
        "metrics": metrics,
    }
