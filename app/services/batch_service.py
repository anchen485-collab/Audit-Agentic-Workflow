from pathlib import Path

from app.infrastructure.batch_repository import (
    AuditBatchRecord,
    complete_review_task,
    get_batch_record,
    list_agent_assessment_payloads,
    list_batch_records,
    list_case_payloads,
    list_decision_payloads,
    list_evidence_package_payloads,
    list_review_task_payloads,
    new_created_at,
    save_batch_details,
    save_batch_record,
)
from app.infrastructure.settings import Settings


def save_audit_batch_summary(
    batch_id: str,
    trace_id: str,
    input_file: Path,
    result_file: Path,
    case_count: int,
    metrics: dict[str, float | int],
    settings: Settings,
    tenant_id: str = "default",
) -> AuditBatchRecord:
    """保存一次审批批次摘要。"""
    record = AuditBatchRecord(
        batch_id=batch_id,
        tenant_id=tenant_id,
        trace_id=trace_id,
        input_file=str(input_file),
        result_file=str(result_file),
        case_count=case_count,
        decision_count=int(metrics.get("decision_count", 0)),
        review_task_count=int(metrics.get("review_task_count", 0)),
        auto_handled_count=int(metrics.get("auto_handled_count", 0)),
        review_count=int(metrics.get("review_count", 0)),
        auto_handled_rate=float(metrics.get("auto_handled_rate", 0.0)),
        review_rate=float(metrics.get("review_rate", 0.0)),
        total_duration_ms=float(metrics.get("total_duration_ms", 0.0)),
        created_at=new_created_at(),
    )

    save_batch_record(settings.database_path, record)

    return record


def save_audit_batch_details(
    batch_id: str,
    cases,
    decisions,
    review_tasks,
    assessments,
    settings: Settings,
    evidence_packages=None,
    tenant_id: str = "default",
) -> None:
    """保存审批批次明细。"""
    save_batch_details(
        database_path=settings.database_path,
        batch_id=batch_id,
        cases=[case.model_dump(mode="json") for case in cases],
        decisions=[decision.model_dump(mode="json") for decision in decisions],
        review_tasks=[task.model_dump(mode="json") for task in review_tasks],
        assessments={
            case_id: [
                assessment.model_dump(mode="json")
                for assessment in case_assessments
            ]
            for case_id, case_assessments in assessments.items()
        },
        evidence_packages={
            case_id: evidence.model_dump(mode="json")
            for case_id, evidence in (evidence_packages or {}).items()
        },
        tenant_id=tenant_id,
    )


def find_audit_batch(
    batch_id: str,
    settings: Settings,
    tenant_id: str | None = None,
) -> AuditBatchRecord | None:
    """查询单个审批批次。"""
    return get_batch_record(settings.database_path, batch_id, tenant_id=tenant_id)


def list_recent_audit_batches(
    settings: Settings,
    limit: int = 20,
    tenant_id: str | None = None,
) -> list[AuditBatchRecord]:
    """查询最近审批批次。"""
    return list_batch_records(settings.database_path, limit=limit, tenant_id=tenant_id)


def list_audit_batch_cases(batch_id: str, settings: Settings) -> list[dict]:
    """查询某个批次下的审批单明细。"""
    return list_case_payloads(settings.database_path, batch_id=batch_id)


def list_audit_batch_decisions(batch_id: str, settings: Settings) -> list[dict]:
    """查询某个批次下的审批结论明细。"""
    return list_decision_payloads(settings.database_path, batch_id=batch_id)


def list_audit_batch_evidence_packages(batch_id: str, settings: Settings) -> list[dict]:
    """查询某个批次下的证据包明细。"""
    return list_evidence_package_payloads(settings.database_path, batch_id=batch_id)


def list_audit_batch_assessments(
    batch_id: str,
    settings: Settings,
    case_id: str | None = None,
) -> list[dict]:
    """查询某个批次或某条审批单的 AgentAssessment 执行轨迹。"""
    return list_agent_assessment_payloads(
        settings.database_path,
        batch_id=batch_id,
        case_id=case_id,
    )


def list_review_tasks(
    settings: Settings,
    status: str | None = None,
    tenant_id: str | None = None,
) -> list[dict]:
    """查询人工复核任务。"""
    return list_review_task_payloads(settings.database_path, status=status, tenant_id=tenant_id)


def submit_review_decision(
    settings: Settings,
    task_id: str,
    reviewer: str,
    final_action: str,
    tenant_id: str | None = None,
) -> dict | None:
    """提交人工复核结论。"""
    return complete_review_task(
        database_path=settings.database_path,
        task_id=task_id,
        reviewer=reviewer,
        final_action=final_action,
        tenant_id=tenant_id,
    )
