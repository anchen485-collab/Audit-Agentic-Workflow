import pytest

from app.domain.decisions import DecisionAction
from app.domain.errors import MissingFieldError
from app.infrastructure.excel_reader import ExcelAuditRow
from app.services.case_service import create_audit_case, create_audit_cases, create_audit_cases_with_errors


def test_create_audit_case_from_excel_row():
    """Excel 行应该能转换成标准审批单。"""
    row = ExcelAuditRow(
        row_number=2,
        date="2026-07-25",
        employee_name="张三",
        entered_level1="信软技术服务",
        entered_subcategory="软件开发",
        company_raw="杭州云启软件有限公司 https://example.com",
        company_name="杭州云启软件有限公司",
        website_url="https://example.com",
    )

    case = create_audit_case(row, batch_id="batch_001")

    assert case.case_id == "batch_001_row_2"
    assert case.batch_id == "batch_001"
    assert case.row_number == 2
    assert case.employee_name == "张三"
    assert case.company_name == "杭州云启软件有限公司"
    assert case.website_url == "https://example.com"
    assert case.status == "pending"


def test_create_audit_case_rejects_missing_required_fields():
    """缺少必填字段时，应该抛出业务错误。"""
    row = ExcelAuditRow(
        row_number=3,
        date="2026-07-25",
        employee_name="",
        entered_level1="信软技术服务",
        entered_subcategory="软件开发",
        company_raw="杭州云启软件有限公司",
        company_name="杭州云启软件有限公司",
        website_url="",
    )

    with pytest.raises(MissingFieldError) as error:
        create_audit_case(row, batch_id="batch_001")

    assert "姓名" in str(error.value)


def test_create_audit_cases_keeps_valid_rows_in_order():
    """批量转换时，审批单顺序应该和 Excel 行顺序一致。"""
    rows = [
        ExcelAuditRow(
            row_number=2,
            date="2026-07-25",
            employee_name="张三",
            entered_level1="信软技术服务",
            entered_subcategory="软件开发",
            company_raw="杭州云启软件有限公司",
            company_name="杭州云启软件有限公司",
            website_url="",
        ),
        ExcelAuditRow(
            row_number=3,
            date="2026-07-25",
            employee_name="李四",
            entered_level1="农业",
            entered_subcategory="种植业",
            company_raw="黑龙江丰禾农业发展有限公司",
            company_name="黑龙江丰禾农业发展有限公司",
            website_url="",
        ),
    ]

    cases = create_audit_cases(rows, batch_id="batch_001")

    assert [case.case_id for case in cases] == ["batch_001_row_2", "batch_001_row_3"]


def test_create_audit_cases_with_errors_keeps_bad_rows_for_review():
    """真实上传模式下，坏行应该转成人工复核结论，不中断整批处理。"""
    rows = [
        ExcelAuditRow(
            row_number=2,
            date="2026-07-25",
            employee_name="张三",
            entered_level1="信软技术服务",
            entered_subcategory="软件开发",
            company_raw="杭州云启软件有限公司",
            company_name="杭州云启软件有限公司",
            website_url="",
        ),
        ExcelAuditRow(
            row_number=3,
            date="2026-07-25",
            employee_name="",
            entered_level1="信软技术服务",
            entered_subcategory="软件开发",
            company_raw="杭州云启软件有限公司",
            company_name="杭州云启软件有限公司",
            website_url="",
        ),
    ]

    valid_cases, invalid_cases, invalid_decisions = create_audit_cases_with_errors(rows, batch_id="batch_001")

    assert len(valid_cases) == 1
    assert len(invalid_cases) == 1
    assert invalid_cases[0].status == "invalid"
    assert invalid_decisions[0].action == DecisionAction.NEEDS_HUMAN_REVIEW
    assert "姓名" in invalid_decisions[0].reason
