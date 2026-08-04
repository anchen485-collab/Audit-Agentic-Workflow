import json
from pathlib import Path

from app.api.dependencies import get_classification_provider
from app.domain.models import AuditCase
from app.infrastructure.evidence_provider import MockCompanyEvidenceProvider
from app.infrastructure.rule_repository import load_category_rules
from app.observability.trace import new_trace_id
from app.workflow.audit_workflow import build_audit_workflow

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_FILE = PROJECT_ROOT / "tests" / "fixtures" / "sample_cases.json"
RULE_FILE = PROJECT_ROOT / "data" / "rules" / "category_rules.json"
EVIDENCE_FILE = PROJECT_ROOT / "data" / "evidence" / "mock_company_evidence.json"

rules = load_category_rules(RULE_FILE)
provider = MockCompanyEvidenceProvider(EVIDENCE_FILE)


def test_small_process():
    cases = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))

    audit_cases = []

    # 获取用户的输入，包装为AuditCase
    for row_number, sample_case in enumerate(cases, start=2):
        input_data = sample_case["input"]

        audit_cases.append(
            AuditCase(
                case_id=sample_case["case_id"],
                batch_id="sample_batch",
                row_number=row_number,
                employee_name=input_data["employee_name"],
                company_raw=input_data["company_raw"],
                company_name=input_data["company_name"],
                website_url=input_data["website_url"],
                entered_level1=input_data["entered_level1"],
                entered_subcategory=input_data["entered_subcategory"],
                entered_stage=input_data["entered_stage"],
                status="pending",
            )
        )

    # 加载规则文件以及初始化一个证据包提供provider
    rules = load_category_rules(RULE_FILE)
    provider = MockCompanyEvidenceProvider(EVIDENCE_FILE)

    # 准备expected_actions，后面用来校对答案用
    expected_actions = {
        sample_case["case_id"]: sample_case["expected_action"]
        for sample_case in cases
    }

    trace_id = new_trace_id()
    workflow = build_audit_workflow()
    result = workflow.invoke({
        "cases": audit_cases,
        "rules": rules,
        "expected_actions": expected_actions,
        "evidence_provider": provider,
        "classification_provider": get_classification_provider(),
        "trace_id": trace_id,
        "trace_events": [],
    })
    print("审计结果：", result)
