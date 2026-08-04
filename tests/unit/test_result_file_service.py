import pytest

from app.domain.decisions import DecisionAction, DecisionStatus
from app.domain.models import ApprovalDecision, AuditCase
from app.infrastructure.settings import Settings
from app.services.result_file_service import (
    build_result_file_path,
    create_result_excel,
    find_result_excel,
)


def test_build_result_file_path_uses_outputs_dir(tmp_path):
    """结果文件应该保存到 outputs_dir 下。"""
    settings = Settings(AUDIT_STORAGE_DIR=tmp_path)

    result_path = build_result_file_path("batch_001", settings)

    assert result_path == settings.outputs_dir / "batch_001_result.xlsx"


def test_create_result_excel_writes_file(tmp_path):
    """应该能生成审批结果 Excel 文件。"""
    settings = Settings(AUDIT_STORAGE_DIR=tmp_path)
    cases = [_build_case()]
    decisions = [_build_decision()]
    review_tasks = []

    result_path = create_result_excel(
        batch_id="batch_001",
        cases=cases,
        decisions=decisions,
        review_tasks=review_tasks,
        settings=settings,
    )

    assert result_path.exists()
    assert result_path.suffix == ".xlsx"


def test_find_result_excel_raises_when_missing(tmp_path):
    """结果文件不存在时，应该抛出清晰错误。"""
    settings = Settings(AUDIT_STORAGE_DIR=tmp_path)

    with pytest.raises(FileNotFoundError):
        find_result_excel("missing_batch", settings)


def _build_case() -> AuditCase:
    """构造测试审批单。"""
    return AuditCase(
        case_id="case_001",
        batch_id="batch_001",
        row_number=2,
        employee_name="张三",
        company_raw="杭州云启软件有限公司 https://example.com",
        company_name="杭州云启软件有限公司",
        website_url="https://example.com",
        entered_level1="信软技术服务",
        entered_subcategory="软件开发",
        entered_stage="录入",
        status="pending",
    )


def _build_decision() -> ApprovalDecision:
    """构造测试审批结论。"""
    return ApprovalDecision(
        case_id="case_001",
        action=DecisionAction.APPROVED,
        status=DecisionStatus.COMPLETED,
        confidence=90,
        risk_score=10,
        reason="证据支持员工录入分类。",
        suggestion="",
        needs_review=False,
    )