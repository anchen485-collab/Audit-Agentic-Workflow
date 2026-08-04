import re
from pathlib import Path

from app.domain.models import AgentAssessment, ApprovalDecision, AuditCase, EvidencePackage, ReviewTask
from app.infrastructure.batch_repository import (
    get_batch_record,
    list_agent_assessment_payloads,
    list_case_payloads,
    list_decision_payloads,
    list_evidence_package_payloads,
    list_review_task_payloads_by_batch,
    mark_batch_result_clean,
)
from app.infrastructure.excel_writer import write_audit_result_excel
from app.infrastructure.settings import Settings


def build_result_file_path(batch_id: str, settings: Settings) -> Path:
    """生成某个批次的审批结果 Excel 路径。"""
    _validate_batch_id(batch_id)
    return settings.outputs_dir / f"{batch_id}_result.xlsx"


def create_result_excel(
    batch_id: str,
    cases: list[AuditCase],
    decisions: list[ApprovalDecision],
    review_tasks: list[ReviewTask],
    settings: Settings,
    evidence_packages: dict[str, EvidencePackage] | None = None,
    assessments: dict[str, list[AgentAssessment]] | None = None,
) -> Path:
    """生成审批结果 Excel，并返回文件路径。"""
    output_path = build_result_file_path(batch_id, settings)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    return write_audit_result_excel(
        output_path=output_path,
        cases=cases,
        decisions=decisions,
        review_tasks=review_tasks,
        evidence_packages=evidence_packages,
        assessments=assessments,
    )


def find_result_excel(batch_id: str, settings: Settings) -> Path:
    """根据 batch_id 查找审批结果 Excel。"""
    result_path = build_result_file_path(batch_id, settings)

    if not result_path.exists():
        raise FileNotFoundError(f"未找到批次结果文件：{batch_id}")

    return result_path


def find_or_rebuild_result_excel(
    batch_id: str,
    settings: Settings,
    tenant_id: str | None = None,
) -> Path:
    """查找结果 Excel；如果人工复核后已过期，就基于 DB 动态重建。"""
    _validate_batch_id(batch_id)
    record = get_batch_record(settings.database_path, batch_id, tenant_id=tenant_id)
    result_path = build_result_file_path(batch_id, settings)

    if record is None:
        if tenant_id is None and result_path.exists():
            return result_path
        raise FileNotFoundError(f"未找到批次结果文件：{batch_id}")

    if result_path.exists() and not record.result_dirty:
        return result_path

    cases = [
        AuditCase(**payload)
        for payload in list_case_payloads(settings.database_path, batch_id)
    ]
    decisions = [
        ApprovalDecision(**payload)
        for payload in list_decision_payloads(settings.database_path, batch_id)
    ]
    review_tasks = [
        ReviewTask(**payload)
        for payload in list_review_task_payloads_by_batch(settings.database_path, batch_id)
    ]
    evidence_packages = {
        payload["case_id"]: EvidencePackage(**payload)
        for payload in list_evidence_package_payloads(settings.database_path, batch_id)
    }
    assessments = _load_assessment_map(batch_id=batch_id, settings=settings)

    if not cases:
        raise FileNotFoundError(f"未找到批次明细，无法重建结果文件：{batch_id}")

    rebuilt_path = create_result_excel(
        batch_id=batch_id,
        cases=cases,
        decisions=decisions,
        review_tasks=review_tasks,
        settings=settings,
        evidence_packages=evidence_packages,
        assessments=assessments,
    )
    mark_batch_result_clean(settings.database_path, batch_id)

    return rebuilt_path


def _load_assessment_map(batch_id: str, settings: Settings) -> dict[str, list[AgentAssessment]]:
    """从 DB 读取 AgentAssessment，并按 case_id 分组。"""
    assessment_map: dict[str, list[AgentAssessment]] = {}
    for payload in list_agent_assessment_payloads(settings.database_path, batch_id):
        case_id = str(payload.get("case_id", ""))
        if not case_id:
            continue
        assessment_map.setdefault(case_id, []).append(AgentAssessment(**payload))

    return assessment_map


def _validate_batch_id(batch_id: str) -> None:
    """校验 batch_id，防止下载接口路径穿越。"""
    if ".." in batch_id or "/" in batch_id or "\\" in batch_id:
        raise ValueError("batch_id 包含非法路径字符。")

    if not re.fullmatch(r"[A-Za-z0-9_-]+", batch_id):
        raise ValueError("batch_id 只能包含字母、数字、下划线和中划线。")
