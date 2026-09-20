from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from starlette.responses import FileResponse

from app.agents.evidence_agent import EvidenceProvider
from app.agents.llm_classification_provider import ClassificationProvider, OpenAICompatibleClassificationProvider
from app.api.dependencies import (
    get_app_settings,
    get_classification_provider,
    get_evidence_provider,
    get_rule_file_path,
    require_any_role,
)
from app.api.schemas import (
    AuditBatchListResponse,
    AuditBatchSummaryResponse,
    AuditUploadResponse,
    CaseRetryResponse,
    LLMHealthResponse,
    ReviewDecisionRequest,
    ReviewTaskListResponse,
)
from app.domain.errors import CaseRetryConflictError, CaseRetryNotFoundError
from app.domain.models import CurrentUser
from app.infrastructure.batch_repository import AuditBatchRecord, record_file_access_audit_log
from app.infrastructure.excel_reader import read_audit_excel
from app.infrastructure.rule_repository import load_category_rules
from app.infrastructure.settings import Settings
from app.observability.logging import get_audit_logger
from app.observability.metrics import calculate_audit_metrics
from app.observability.trace import new_trace_id
from app.services.batch_service import (
    find_audit_batch,
    list_audit_batch_assessments,
    list_audit_batch_cases,
    list_audit_batch_decisions,
    list_recent_audit_batches,
    list_review_tasks,
    save_audit_batch_details,
    save_audit_batch_summary,
    submit_review_decision,
)
from app.services.case_retry_service import retry_audit_case
from app.services.case_service import create_audit_cases_with_errors
from app.services.result_file_service import create_result_excel, find_or_rebuild_result_excel
from app.services.review_service import create_review_tasks
from app.services.upload_service import save_upload_file
from app.workflow.audit_workflow import build_audit_workflow

router = APIRouter(prefix="/api/audit", tags=["audit"])
review_router = APIRouter(prefix="/api/review", tags=["review"])
health_router = APIRouter(prefix="/health", tags=["health"])
logger = get_audit_logger("api.routes")


@router.post("/upload", response_model=AuditUploadResponse)
async def upload_audit_excel(
    file: Annotated[UploadFile, File()],
    settings: Annotated[Settings, Depends(get_app_settings)],
    rule_file: Annotated[Path, Depends(get_rule_file_path)],
    evidence_provider: Annotated[EvidenceProvider, Depends(get_evidence_provider)],
    classification_provider: Annotated[
        ClassificationProvider,
        Depends(get_classification_provider),
    ],
    current_user: Annotated[CurrentUser, Depends(require_any_role({"uploader"}))],
) -> AuditUploadResponse:
    """上传员工录入 Excel，并执行审批 Agent 工作流。"""
    original_filename = file.filename or ""
    logger.info(
        "收到审批 Excel 上传请求: filename=%s provider=%s llm_enabled=%s rule_file=%s",
        original_filename,
        settings.company_provider,
        settings.llm_enabled,
        rule_file,
    )

    try:
        batch_id, upload_path = await save_upload_file(file, settings=settings)
        logger.info("上传文件已保存: batch_id=%s path=%s", batch_id, upload_path)

        rows = read_audit_excel(upload_path)
        logger.info("Excel 解析完成: batch_id=%s row_count=%s", batch_id, len(rows))
        if not rows:
            raise ValueError("Excel 没有可处理的数据行。")

        valid_cases, invalid_cases, invalid_decisions = create_audit_cases_with_errors(rows, batch_id=batch_id)
        logger.info(
            "审批单构造完成: batch_id=%s valid_cases=%s invalid_cases=%s",
            batch_id,
            len(valid_cases),
            len(invalid_cases),
        )
        for invalid_decision in invalid_decisions:
            logger.warning(
                "Excel 行数据异常，已转人工复核: batch_id=%s case_id=%s reason=%s",
                batch_id,
                invalid_decision.case_id,
                invalid_decision.reason,
            )

        all_cases = valid_cases + invalid_cases
        rules = load_category_rules(rule_file)
        trace_id = new_trace_id()
        logger.info("分类规则加载完成: batch_id=%s rule_count=%s trace_id=%s", batch_id, len(rules), trace_id)

        result = build_audit_workflow().invoke(
            {
                "cases": valid_cases,
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
                "trace_id": trace_id,
                "trace_events": [],
                "assessments": {},
            }
        )
        logger.info(
            "多 Agent 工作流完成: batch_id=%s decisions=%s review_tasks=%s duration_ms=%s",
            batch_id,
            len(result["decisions"]),
            len(result["review_tasks"]),
            result["metrics"].get("total_duration_ms", 0.0),
        )

        all_decisions = [*result["decisions"], *invalid_decisions]
        all_review_tasks = [*result["review_tasks"], *create_review_tasks(invalid_decisions)]
        metrics = calculate_audit_metrics(
            decisions=all_decisions,
            review_tasks=all_review_tasks,
            assessments=result.get("assessments", {}),
            trace_events=result.get("trace_events", []),
        )

        result_file = create_result_excel(
            batch_id=batch_id,
            cases=all_cases,
            decisions=all_decisions,
            review_tasks=all_review_tasks,
            settings=settings,
            evidence_packages=result.get("evidence_packages", {}),
            assessments=result.get("assessments", {}),
        )
        logger.info("审批结果 Excel 已生成: batch_id=%s result_file=%s", batch_id, result_file)

        save_audit_batch_summary(
            batch_id=batch_id,
            trace_id=trace_id,
            input_file=upload_path,
            result_file=result_file,
            case_count=len(all_cases),
            metrics=metrics,
            settings=settings,
            tenant_id=current_user.tenant_id,
        )
        save_audit_batch_details(
            batch_id=batch_id,
            cases=all_cases,
            decisions=all_decisions,
            review_tasks=all_review_tasks,
            assessments=result.get("assessments", {}),
            evidence_packages=result.get("evidence_packages", {}),
            settings=settings,
            tenant_id=current_user.tenant_id,
        )
        logger.info(
            "审批批次已保存: batch_id=%s total=%s auto_handled=%s review=%s review_rate=%.2f",
            batch_id,
            metrics["total_count"],
            metrics["auto_handled_count"],
            metrics["review_count"],
            metrics["review_rate"],
        )

        return AuditUploadResponse(
            batch_id=batch_id,
            case_count=len(all_cases),
            decision_count=len(all_decisions),
            review_task_count=len(all_review_tasks),
            metrics=metrics,
            cases=_attach_rule_recall_summary_to_cases(
                cases=all_cases,
                rule_sets=result.get("rule_sets", {}),
            ),
            decisions=[
                decision.model_dump(mode="json")
                for decision in all_decisions
            ],
            review_tasks=[
                task.model_dump(mode="json")
                for task in all_review_tasks
            ],
            download_url=f"/api/audit/batches/{batch_id}/result",
        )

    except ValueError as error:
        logger.warning(
            "审批上传失败: filename=%s reason=%s",
            original_filename,
            error,
        )
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.exception("审批上传出现未预期错误: filename=%s", original_filename)
        raise HTTPException(status_code=500, detail="审批处理失败，请查看服务端控制台日志。") from error


@router.get("/batches/{batch_id}/result")
async def download_audit_result(
    batch_id: str,
    request: Request,
    settings: Annotated[Settings, Depends(get_app_settings)],
    current_user: Annotated[CurrentUser, Depends(require_any_role({"uploader", "reviewer", "auditor"}))],
) -> FileResponse:
    """下载某个批次的审批结果 Excel。"""
    try:
        result_path = find_or_rebuild_result_excel(
            batch_id=batch_id,
            settings=settings,
            tenant_id=_tenant_filter_for(current_user),
        )
    except ValueError as error:
        logger.warning("结果下载失败: batch_id=%s reason=%s", batch_id, error)
        raise HTTPException(status_code=400, detail=str(error)) from error
    except FileNotFoundError as error:
        logger.warning("结果下载失败: batch_id=%s reason=%s", batch_id, error)
        raise HTTPException(status_code=404, detail=str(error)) from error

    record_file_access_audit_log(
        database_path=settings.database_path,
        user_id=current_user.user_id,
        tenant_id=current_user.tenant_id,
        batch_id=batch_id,
        action="download_result_excel",
        client_ip=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
    )
    logger.info("下载审批结果 Excel: batch_id=%s user_id=%s path=%s", batch_id, current_user.user_id, result_path)
    return FileResponse(
        path=result_path,
        filename=f"{batch_id}_result.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/batches", response_model=AuditBatchListResponse)
def list_audit_batches(
    settings: Annotated[Settings, Depends(get_app_settings)],
    current_user: Annotated[CurrentUser, Depends(require_any_role({"uploader", "reviewer", "auditor"}))],
    limit: int = 20,
) -> AuditBatchListResponse:
    """查询最近审批批次。"""
    records = list_recent_audit_batches(
        settings=settings,
        limit=limit,
        tenant_id=_tenant_filter_for(current_user),
    )

    return AuditBatchListResponse(
        total=len(records),
        items=[
            _batch_record_to_response(record)
            for record in records
        ],
    )


@router.get("/batches/{batch_id}", response_model=AuditBatchSummaryResponse)
def get_audit_batch(
    batch_id: str,
    settings: Annotated[Settings, Depends(get_app_settings)],
    current_user: Annotated[CurrentUser, Depends(require_any_role({"uploader", "reviewer", "auditor"}))],
) -> AuditBatchSummaryResponse:
    """查询单个审批批次摘要。"""
    record = find_audit_batch(
        batch_id=batch_id,
        settings=settings,
        tenant_id=_tenant_filter_for(current_user),
    )

    if record is None:
        raise HTTPException(status_code=404, detail=f"未找到审批批次：{batch_id}")

    return _batch_record_to_response(record)


@router.get("/batches/{batch_id}/cases")
def list_audit_batch_cases_api(
    batch_id: str,
    settings: Annotated[Settings, Depends(get_app_settings)],
    current_user: Annotated[CurrentUser, Depends(require_any_role({"uploader", "reviewer", "auditor"}))],
) -> dict:
    """查询某个批次下的审批单明细。"""
    if find_audit_batch(batch_id=batch_id, settings=settings, tenant_id=_tenant_filter_for(current_user)) is None:
        raise HTTPException(status_code=404, detail=f"未找到审批批次：{batch_id}")

    items = list_audit_batch_cases(batch_id=batch_id, settings=settings)
    return {"total": len(items), "items": items}


@router.get("/batches/{batch_id}/decisions")
def list_audit_batch_decisions_api(
    batch_id: str,
    settings: Annotated[Settings, Depends(get_app_settings)],
    current_user: Annotated[CurrentUser, Depends(require_any_role({"uploader", "reviewer", "auditor"}))],
) -> dict:
    """查询某个批次下的审批结论明细。"""
    if find_audit_batch(batch_id=batch_id, settings=settings, tenant_id=_tenant_filter_for(current_user)) is None:
        raise HTTPException(status_code=404, detail=f"未找到审批批次：{batch_id}")

    items = _attach_classification_error_summary(
        decisions=list_audit_batch_decisions(batch_id=batch_id, settings=settings),
        assessments=list_audit_batch_assessments(batch_id=batch_id, settings=settings),
    )
    return {"total": len(items), "items": items}


@router.get("/batches/{batch_id}/assessments")
def list_audit_batch_assessments_api(
    batch_id: str,
    settings: Annotated[Settings, Depends(get_app_settings)],
    current_user: Annotated[CurrentUser, Depends(require_any_role({"uploader", "reviewer", "auditor"}))],
    case_id: str | None = None,
) -> dict:
    """查询某个批次或某条审批单的 AgentAssessment 执行轨迹。"""
    if find_audit_batch(batch_id=batch_id, settings=settings, tenant_id=_tenant_filter_for(current_user)) is None:
        raise HTTPException(status_code=404, detail=f"未找到审批批次：{batch_id}")

    items = list_audit_batch_assessments(
        batch_id=batch_id,
        settings=settings,
        case_id=case_id,
    )
    return {"total": len(items), "items": items}


@router.post("/batches/{batch_id}/cases/{case_id}/retry", response_model=CaseRetryResponse)
def retry_audit_case_api(
    batch_id: str,
    case_id: str,
    settings: Annotated[Settings, Depends(get_app_settings)],
    rule_file: Annotated[Path, Depends(get_rule_file_path)],
    evidence_provider: Annotated[EvidenceProvider, Depends(get_evidence_provider)],
    classification_provider: Annotated[ClassificationProvider, Depends(get_classification_provider)],
    current_user: Annotated[CurrentUser, Depends(require_any_role({"uploader", "reviewer", "auditor"}))],
) -> CaseRetryResponse:
    """重新执行单条审批单；已提交人工最终结论的记录保持不变。"""
    try:
        result = retry_audit_case(
            batch_id=batch_id,
            case_id=case_id,
            tenant_id=current_user.tenant_id,
            retried_by=current_user.user_id,
            rules=load_category_rules(rule_file),
            evidence_provider=evidence_provider,
            classification_provider=classification_provider,
            settings=settings,
        )
        logger.info(
            "审批单重试完成: batch_id=%s case_id=%s trace_id=%s user_id=%s",
            batch_id,
            case_id,
            result["retry_trace_id"],
            current_user.user_id,
        )
        return CaseRetryResponse(**result)
    except CaseRetryNotFoundError as error:
        raise HTTPException(status_code=404, detail=error.message) from error
    except CaseRetryConflictError as error:
        raise HTTPException(status_code=409, detail=error.message) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@review_router.get("/tasks", response_model=ReviewTaskListResponse)
def list_review_tasks_api(
    settings: Annotated[Settings, Depends(get_app_settings)],
    current_user: Annotated[CurrentUser, Depends(require_any_role({"reviewer", "auditor"}))],
    status: str | None = None,
) -> ReviewTaskListResponse:
    """查询人工复核任务。"""
    tasks = list_review_tasks(
        settings=settings,
        status=status,
        tenant_id=_tenant_filter_for(current_user),
    )
    return ReviewTaskListResponse(total=len(tasks), items=tasks)


@review_router.post("/tasks/{task_id}/decision")
def submit_review_decision_api(
    task_id: str,
    request: ReviewDecisionRequest,
    settings: Annotated[Settings, Depends(get_app_settings)],
    current_user: Annotated[CurrentUser, Depends(require_any_role({"reviewer"}))],
) -> dict:
    """提交人工复核结论。"""
    task = submit_review_decision(
        settings=settings,
        task_id=task_id,
        reviewer=current_user.user_id,
        final_action=request.final_action.value,
        tenant_id=_tenant_filter_for(current_user),
    )

    if task is None:
        raise HTTPException(status_code=404, detail=f"未找到人工复核任务：{task_id}")

    return task


def _batch_record_to_response(record: AuditBatchRecord) -> AuditBatchSummaryResponse:
    """把数据库批次记录转成 API 响应，避免把服务器本地文件路径暴露给前端。"""
    return AuditBatchSummaryResponse(
        batch_id=record.batch_id,
        trace_id=record.trace_id,
        download_url=f"/api/audit/batches/{record.batch_id}/result",
        case_count=record.case_count,
        decision_count=record.decision_count,
        review_task_count=record.review_task_count,
        auto_handled_count=record.auto_handled_count,
        review_count=record.review_count,
        auto_handled_rate=record.auto_handled_rate,
        review_rate=record.review_rate,
        total_duration_ms=record.total_duration_ms,
        created_at=record.created_at,
    )


def _tenant_filter_for(current_user: CurrentUser) -> str | None:
    """admin 可跨租户查看；其他角色只能访问自己的租户。"""
    if current_user.has_role("admin"):
        return None

    return current_user.tenant_id


def _attach_classification_error_summary(
    decisions: list[dict],
    assessments: list[dict],
) -> list[dict]:
    """给 decision 明细补充 Classification Agent 错误摘要，方便前端直接展示。"""
    assessment_map = {
        assessment.get("case_id"): assessment
        for assessment in assessments
        if assessment.get("agent_name") == "classification_agent"
    }

    enriched_decisions = []
    for decision in decisions:
        item = dict(decision)
        assessment = assessment_map.get(decision.get("case_id"))
        output = assessment.get("output", {}) if assessment else {}
        item["classification_agent_status"] = assessment.get("status", "") if assessment else ""
        item["classification_agent_error"] = output.get("error") or output.get("normalization_warning", "")
        item["classification_agent_error_code"] = output.get("error_code", "")
        item["evidence_error_type"] = output.get("evidence_error_type", "")
        item.update(_rule_recall_summary_from_assessments(decision.get("case_id"), assessments))
        enriched_decisions.append(item)

    return enriched_decisions


def _attach_rule_recall_summary_to_cases(cases, rule_sets) -> list[dict]:
    """把规则召回粒度诊断挂到 case 返回值上，前端表格可直接展示。"""
    items = []
    for audit_case in cases:
        item = audit_case.model_dump(mode="json")
        rule_set = rule_sets.get(audit_case.case_id)
        if rule_set:
            item.update(
                {
                    "entered_subcategory_granularity": rule_set.entered_subcategory_granularity,
                    "granularity_reason": rule_set.granularity_reason,
                    "category_candidate_paths": _category_candidate_paths(rule_set),
                }
            )
        else:
            item.update(
                {
                    "entered_subcategory_granularity": "",
                    "granularity_reason": "",
                    "category_candidate_paths": [],
                }
            )
        items.append(item)

    return items


def _category_candidate_paths(rule_set) -> list[str]:
    """把分类候选格式化成路径，二级候选不补空三级。"""
    return [
        " / ".join(part for part in [candidate.level1, candidate.level2, candidate.level3] if part)
        for candidate in rule_set.category_candidates
    ]


def _rule_recall_summary_from_assessments(case_id, assessments: list[dict]) -> dict:
    """从 Rule Agent assessment 中提取召回粒度信息。"""
    for assessment in assessments:
        if assessment.get("case_id") != case_id or assessment.get("agent_name") != "rule_agent":
            continue

        output = assessment.get("output", {})
        return {
            "entered_subcategory_granularity": output.get("entered_subcategory_granularity", ""),
            "granularity_reason": output.get("granularity_reason", ""),
            "category_candidate_paths": output.get("category_candidate_paths", []),
        }

    return {
        "entered_subcategory_granularity": "",
        "granularity_reason": "",
        "category_candidate_paths": [],
    }


@health_router.get("/llm", response_model=LLMHealthResponse)
def check_llm_health(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> LLMHealthResponse:
    """检查 LLM 配置和连通性，不返回 API Key。"""
    if not settings.llm_enabled:
        return LLMHealthResponse(
            enabled=False,
            ok=True,
            provider="mock_classification",
            message="LLM 未启用，当前使用 mock classification provider。",
        )

    if not settings.llm_health_check_enabled:
        return LLMHealthResponse(
            enabled=True,
            ok=True,
            provider="openai_compatible",
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            message="LLM 连通性检查已关闭，仅完成静态配置校验。",
        )

    provider = OpenAICompatibleClassificationProvider(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )
    result = provider.health_check()

    return LLMHealthResponse(
        enabled=True,
        ok=bool(result["ok"]),
        provider="openai_compatible",
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        error_type=str(result.get("error_type", "")),
        message=str(result.get("message", "")),
    )
