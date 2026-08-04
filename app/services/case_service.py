from app.domain.decisions import DecisionAction, DecisionStatus
from app.domain.errors import MissingFieldError
from app.domain.models import ApprovalDecision, AuditCase
from app.infrastructure.excel_reader import ExcelAuditRow

REQUIRED_ROW_FIELDS = {
    "日期": "date",
    "姓名": "employee_name",
    "一级分类": "entered_level1",
    "细分": "entered_subcategory",
    "企业名称&官网": "company_raw",
}


def create_audit_case(row: ExcelAuditRow, batch_id: str) -> AuditCase:
    """把 Excel 原始行转换成标准审批单。"""
    missing_fields = _missing_required_fields(row)
    if missing_fields:
        raise MissingFieldError(f"第 {row.row_number} 行缺少必填字段：{'、'.join(missing_fields)}")

    return _build_audit_case(row=row, batch_id=batch_id, status="pending")


def create_audit_cases_with_errors(
    rows: list[ExcelAuditRow],
    batch_id: str,
) -> tuple[list[AuditCase], list[AuditCase], list[ApprovalDecision]]:
    """批量转换 Excel 行，坏行转成人工复核结论而不是中断整批上传。"""
    valid_cases = []
    invalid_cases = []
    invalid_decisions = []

    for row in rows:
        missing_fields = _missing_required_fields(row)
        if not missing_fields:
            valid_cases.append(_build_audit_case(row=row, batch_id=batch_id, status="pending"))
            continue

        invalid_case = _build_audit_case(row=row, batch_id=batch_id, status="invalid")
        invalid_cases.append(invalid_case)
        invalid_decisions.append(_build_invalid_row_decision(invalid_case, missing_fields))

    return valid_cases, invalid_cases, invalid_decisions


def _build_audit_case(row: ExcelAuditRow, batch_id: str, status: str) -> AuditCase:
    """构造审批单对象。"""
    return AuditCase(
        case_id=f"{batch_id}_row_{row.row_number}",
        batch_id=batch_id,
        row_number=row.row_number,
        employee_name=row.employee_name,
        company_raw=row.company_raw,
        company_name=row.company_name,
        website_url=row.website_url,
        entered_level1=row.entered_level1,
        entered_level2=row.entered_level2,
        entered_subcategory=row.entered_subcategory,
        entered_stage="",
        status=status,
    )


def create_audit_cases(rows: list[ExcelAuditRow], batch_id: str) -> list[AuditCase]:
    """批量把 Excel 行转换成审批单。"""
    return [create_audit_case(row, batch_id) for row in rows]


def _build_invalid_row_decision(audit_case: AuditCase, missing_fields: list[str]) -> ApprovalDecision:
    """为字段缺失的 Excel 行生成待人工复核结论。"""
    reason = f"Excel 第 {audit_case.row_number} 行缺少必填字段：{'、'.join(missing_fields)}。"
    return ApprovalDecision(
        case_id=audit_case.case_id,
        action=DecisionAction.NEEDS_HUMAN_REVIEW,
        status=DecisionStatus.PENDING_REVIEW,
        confidence=100,
        risk_score=100,
        reason=reason,
        suggestion="请补全员工录入信息后重新提交，或由审核员人工确认。",
        needs_review=True,
    )


def _missing_required_fields(row: ExcelAuditRow) -> list[str]:
    """返回当前行缺失的必填字段中文名。"""
    missing_fields = []
    for label, attr_name in REQUIRED_ROW_FIELDS.items():
        value = getattr(row, attr_name)
        if not str(value or "").strip():
            missing_fields.append(label)
    return missing_fields
