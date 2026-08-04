import json
from pathlib import Path

from app.agents.classification_agent import classify_audit_case
from app.domain.models import AuditCase
from app.infrastructure.evidence_provider import MockCompanyEvidenceProvider
from app.infrastructure.rule_repository import load_category_rules
from app.services.decision_service import calculate_decision_accuracy
from app.services.review_service import calculate_review_metrics, create_review_tasks
from app.services.rule_retriever import retrieve_candidate_rules

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_FILE = PROJECT_ROOT / "tests" / "fixtures" / "sample_cases.json"
RULE_FILE = PROJECT_ROOT / "data" / "rules" / "category_rules.json"
EVIDENCE_FILE = PROJECT_ROOT / "data" / "evidence" / "mock_company_evidence.json"


rules = load_category_rules(RULE_FILE)
provider = MockCompanyEvidenceProvider(EVIDENCE_FILE)

def test_small_process():
    cases = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))

    audit_cases = []

    #获取用户的输入，包装为AuditCase
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


    #加载规则文件以及初始化一个证据包提供provider
    rules = load_category_rules(RULE_FILE)
    provider = MockCompanyEvidenceProvider(EVIDENCE_FILE)

    #调用classification_agent做出决定
    decisions = []
    for audit_case in audit_cases:
        candidate_rules = retrieve_candidate_rules(
            audit_case=audit_case,
            rules=rules,
            limit=3,
        )
        evidence = provider.fetch(audit_case.case_id,audit_case.company_name)

        decision = classify_audit_case(
            audit_case=audit_case,
            evidence=evidence,
            candidate_rules=candidate_rules,
        )

        decisions.append(decision)

    #创建人工复审任务
    review_tasks = create_review_tasks(decisions)
    print("需要复审的任务：",review_tasks)

    #准备expected_actions，后面用来校对答案用
    expected_actions = {
        sample_case["case_id"]: sample_case["expected_action"]
        for sample_case in cases
    }

    #计算人工复审指标
    for decision in decisions:
        expected_action = expected_actions[decision.case_id]

        print(
            decision.case_id,
            "expected=",
            expected_action,
            "actual=",
            decision.action,
            "needs_review=",
            decision.needs_review,
            "reason=",
            decision.reason,
        )

    metric = calculate_review_metrics(decisions)
    print(metric)


    #计算正确率
    accuracy = calculate_decision_accuracy(decisions,expected_actions)
    print("正确率:",accuracy)




