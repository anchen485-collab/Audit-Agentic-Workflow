import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.agents.llm_classification_provider import SemanticClassificationResult
from app.domain.models import EvidencePackage, EvidenceSnippet
from scripts.run_eval import EvaluationDataError, EvaluationFailedError, run_eval

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_run_eval_returns_metrics_for_golden_cases():
    """稳定回归测试显式使用 mock provider，避免自动化测试依赖外部官网和 LLM。"""
    result = run_eval(
        cases_file=PROJECT_ROOT / "evals" / "golden_cases.json",
        rules_file=PROJECT_ROOT / "data" / "rules" / "category_rules.json",
        evidence_file=PROJECT_ROOT / "data" / "evidence" / "mock_company_evidence.json",
        use_real_providers=False,
    )

    assert result["case_count"] >= 30
    assert result["metrics"]["decision_count"] == result["case_count"]
    assert "accuracy" in result["metrics"]
    assert result["metrics"]["accuracy"] >= 0.8
    assert result["metrics"]["agent_assessment_count"] >= 50

    actual_actions = {
        decision["action"]
        for decision in result["decisions"]
    }
    assert {
        "approved",
        "rejected",
        "needs_more_evidence",
        "needs_human_review",
    }.issubset(actual_actions)


def test_run_eval_raises_when_accuracy_below_threshold():
    with pytest.raises(EvaluationFailedError) as error:
        run_eval(
            cases_file=PROJECT_ROOT / "tests" / "fixtures" / "sample_cases.json",
            rules_file=PROJECT_ROOT / "data" / "rules" / "category_rules.json",
            evidence_file=PROJECT_ROOT / "data" / "evidence" / "mock_company_evidence.json",
            use_real_providers=False,
            min_accuracy=1.01,
        )

    assert error.value.mismatches
    assert "accuracy" in str(error.value)


def test_run_eval_can_use_llm_semantic_provider_for_level3_equivalence(tmp_path):
    """评测链路应该能注入 LLM provider，用语义等价判断解决三级分类近义词误拒。"""
    golden_cases = (PROJECT_ROOT / "evals" / "golden_cases.json").read_text(encoding="utf-8")
    medical_case = [
        item
        for item in json.loads(golden_cases)
        if item["case_id"] == "golden_002"
    ]
    cases_file = tmp_path / "medical_golden_case.json"
    cases_file.write_text(json.dumps(medical_case, ensure_ascii=False), encoding="utf-8")

    result = run_eval(
        cases_file=cases_file,
        rules_file=PROJECT_ROOT / "data" / "rules" / "category_rules.json",
        evidence_file=PROJECT_ROOT / "data" / "evidence" / "mock_company_evidence.json",
        classification_provider=FakeSemanticMedicalProvider(),
        use_real_providers=False,
        min_accuracy=1.0,
    )

    assert result["metrics"]["accuracy"] == 1.0
    assert result["decisions"][0]["action"] == "approved"


def test_real_eval_rejects_mock_website_urls():
    """真实流程评测不能使用 example.com 这类 mock 官网 URL。"""
    with pytest.raises(EvaluationDataError) as error:
        run_eval(
            cases_file=PROJECT_ROOT / "evals" / "golden_cases.json",
            rules_file=PROJECT_ROOT / "data" / "rules" / "category_rules.json",
            use_real_providers=True,
        )

    assert "mock 官网 URL" in str(error.value)
    assert "golden_001" in str(error.value)


def test_run_eval_from_excel_excludes_unavailable_websites_from_accuracy(tmp_path):
    """官网不可访问属于外部证据问题，不应该进入审批正确率分母。"""
    excel_file = tmp_path / "real_cases.xlsx"
    _write_eval_excel(excel_file)

    result = run_eval(
        excel_file=excel_file,
        rules_file=PROJECT_ROOT / "data" / "rules" / "category_rules.json",
        evidence_provider=MixedEvidenceProvider(),
        classification_provider=AlwaysApproveProvider(),
        use_real_providers=True,
        min_accuracy=1.0,
    )

    assert result["case_count"] == 2
    assert result["metrics"]["accuracy"] == 1.0
    assert result["metrics"]["accuracy_eligible_count"] == 1
    assert result["metrics"]["accuracy_excluded_count"] == 1
    assert result["metrics"]["evidence_unavailable_count"] == 1
    assert result["mismatches"] == []


class FakeSemanticMedicalProvider:
    """测试用 LLM provider：模拟模型理解医疗器械、康复设备属于医疗设备。"""

    def classify(self, audit_case, evidence, candidate_rules):
        assert audit_case.entered_subcategory == "医疗设备"
        assert "医疗器械" in evidence.business_scope

        return SemanticClassificationResult(
            result="supports_entered_category",
            confidence=92,
            matched_candidate_rule_id="rule_1",
            matched_level1="机械设备厂",
            matched_level2="专用设备厂",
            matched_level3="医疗设备",
            evidence_quotes=[
                "公司专注医用检测设备、康复设备、医疗器械配套系统的研发、生产和销售。",
            ],
            reason="证据中的医用检测设备、康复设备和医疗器械配套系统在语义上支持医疗设备分类。",
            suggestion="",
        )


class AlwaysApproveProvider:
    """测试用分类 provider：可访问证据直接判断通过。"""

    def classify(self, audit_case, evidence, candidate_rules):
        return SemanticClassificationResult(
            result="supports_entered_category",
            confidence=90,
            matched_candidate_rule_id="rule_1",
            matched_level1=audit_case.entered_level1,
            matched_level2="软件和信息技术",
            matched_level3=audit_case.entered_subcategory,
            evidence_quotes=["官网显示提供软件开发服务。"],
            reason="证据支持员工录入分类。",
            suggestion="",
        )


class MixedEvidenceProvider:
    """测试用证据 provider：第一条可访问，第二条官网访问失败。"""

    def fetch(self, case_id: str, company_name: str, website_url: str = ""):
        if "row_3" in case_id:
            return EvidencePackage(
                case_id=case_id,
                company_name=company_name,
                sources=[],
                business_scope="",
                snippets=[],
                quality_score=0,
                errors=["官网访问失败：连接超时。"],
            )

        return EvidencePackage(
            case_id=case_id,
            company_name=company_name,
            sources=["website"],
            business_scope="公司提供软件开发和系统集成服务。",
            snippets=[
                EvidenceSnippet(source="website", text="官网显示提供软件开发服务。", url=website_url),
            ],
            quality_score=90,
            errors=[],
        )


def _write_eval_excel(path: Path) -> None:
    """写入测试用 Excel，包含标准答案列。"""
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["日期", "姓名", "一级分类", "细分", "企业名称&官网", "expected_action"])
    sheet.append([
        "2026-08-03",
        "测试员",
        "信软技术服务",
        "软件开发",
        "测试软件公司 https://valid.audit-local.test",
        "approved",
    ])
    sheet.append([
        "2026-08-03",
        "测试员",
        "信软技术服务",
        "软件开发",
        "访问失败公司 https://down.audit-local.test",
        "approved",
    ])
    workbook.save(path)
