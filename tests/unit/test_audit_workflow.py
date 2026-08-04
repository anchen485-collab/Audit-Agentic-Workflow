import time
from threading import Lock

from app.agents.llm_classification_provider import OpenAICompatibleClassificationProvider, SemanticClassificationResult
from app.domain.models import AuditCase, CategoryRule, EvidencePackage, EvidenceSnippet
from app.infrastructure.settings import Settings
from app.observability.logging import configure_logging
from app.workflow.audit_workflow import build_audit_workflow


class FakeEvidenceProvider:
    """测试用证据提供器。"""

    def fetch(self, case_id: str, company_name: str) -> EvidencePackage:
        return EvidencePackage(
            case_id=case_id,
            company_name=company_name,
            sources=["fake"],
            business_scope="公司主要提供软件开发和系统集成服务。",
            snippets=[
                EvidenceSnippet(
                    source="fake",
                    text="提供软件开发服务",
                    url="",
                )
            ],
            quality_score=90,
            errors=[],
        )


def test_audit_workflow_returns_decision_and_metrics():
    """LangGraph 工作流应该能跑完审批主链路。"""
    workflow = build_audit_workflow()

    case = AuditCase(
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
    rules = [
        CategoryRule(
            level1="信软技术服务",
            level2="软件和信息技术",
            level3="软件开发",
            module="业务领域",
            keywords=["软件开发", "系统集成"],
        )
    ]

    result = workflow.invoke(
        {
            "cases": [case],
            "rules": rules,
            "evidence_provider": FakeEvidenceProvider(),
            "expected_actions": {"case_001": "approved"},
        }
    )

    assert len(result["decisions"]) == 1
    assert result["decisions"][0].case_id == "case_001"
    assert result["metrics"]["decision_count"] == 1
    assert result["metrics"]["accuracy"] == 1.0
    assert result["metrics"]["review_task_count"] == 0
    assert "case_001" in result["assessments"]
    assert len(result["assessments"]["case_001"]) >= 5
    assert {event.node_name for event in result["trace_events"]} >= {
        "evidence_agent",
        "rule_agent",
        "classification_agent",
    }
    assert {assessment.agent_name for assessment in result["assessments"]["case_001"]} >= {
        "evidence_agent",
        "rule_agent",
        "classification_agent",
    }


def test_audit_workflow_collects_evidence_for_cases_in_parallel():
    """多个 case 的证据采集应该按配置并行执行。"""
    workflow = build_audit_workflow()
    provider = SlowEvidenceProvider()
    cases = [_build_case(f"case_{index:03d}") for index in range(5)]

    result = workflow.invoke(
        {
            "cases": cases,
            "rules": [_software_rule()],
            "evidence_provider": provider,
            "classification_provider": FastClassificationProvider(),
            "evidence_concurrency": 5,
            "classification_concurrency": 1,
        }
    )

    assert len(result["decisions"]) == 5
    assert provider.max_active > 1


def test_audit_workflow_classifies_cases_in_parallel():
    """多个 case 的语义分类 Agent 应该按配置并行执行。"""
    workflow = build_audit_workflow()
    provider = SlowClassificationProvider()
    cases = [_build_case(f"case_{index:03d}") for index in range(5)]

    result = workflow.invoke(
        {
            "cases": cases,
            "rules": [_software_rule()],
            "evidence_provider": FakeEvidenceProvider(),
            "classification_provider": provider,
            "evidence_concurrency": 1,
            "classification_concurrency": 3,
        }
    )

    assert len(result["decisions"]) == 5
    assert provider.max_active > 1


def test_audit_workflow_logs_batch_stage_duration(capsys):
    """工作流应该在终端输出爬虫和 Agent 批量阶段耗时。"""
    configure_logging(Settings(_env_file=None))
    workflow = build_audit_workflow()
    cases = [_build_case(f"case_{index:03d}") for index in range(2)]

    workflow.invoke(
        {
            "cases": cases,
            "rules": [_software_rule()],
            "evidence_provider": FakeEvidenceProvider(),
            "classification_provider": FastClassificationProvider(),
            "evidence_concurrency": 2,
            "classification_concurrency": 2,
        }
    )

    output = capsys.readouterr().out

    assert "爬虫批量采集完成" in output
    assert "Classification Agent 批量分析完成" in output
    assert "wall_duration_ms=" in output


def test_audit_workflow_rule_agent_uses_default_top_five():
    """工作流中的 RuleAgent 不应该继续硬编码 Top3。"""
    workflow = build_audit_workflow()
    case = _build_case("case_001")
    rules = [
        CategoryRule(
            level1="信软技术服务",
            level2=f"软件和信息技术{index}",
            level3=f"软件开发{index}",
            module="业务领域",
            keywords=["软件"],
        )
        for index in range(1, 6)
    ]

    result = workflow.invoke(
        {
            "cases": [case],
            "rules": rules,
            "evidence_provider": FakeEvidenceProvider(),
            "classification_provider": FastClassificationProvider(),
        }
    )

    rule_assessment = next(
        assessment
        for assessment in result["assessments"]["case_001"]
        if assessment.agent_name == "rule_agent"
    )
    assert rule_assessment.output["candidate_count"] == 5


def test_level2_multi_category_supported_result_is_auto_approved():
    """二级多分类被 LLM 合法支持时，不应因 level3 为空被降级到人工复核。"""
    workflow = build_audit_workflow()
    case = AuditCase(
        case_id="case_planting",
        batch_id="batch_001",
        row_number=2,
        employee_name="刘丹",
        company_raw="青山农业有限公司 https://planting.example.com",
        company_name="青山农业有限公司",
        website_url="https://planting.example.com",
        entered_level1="种植业",
        entered_subcategory="蔬菜作物,水果作物",
        status="pending",
    )

    result = workflow.invoke(
        {
            "cases": [case],
            "rules": _planting_rules(),
            "evidence_provider": PlantingEvidenceProvider(),
            "classification_provider": Level2PartialPathClassificationProvider(
                api_key="fake",
                base_url="https://example.com",
                model="fake-model",
            ),
            "expected_actions": {"case_planting": "approved"},
        }
    )

    decision = result["decisions"][0]
    risk_assessment = next(
        assessment
        for assessment in result["assessments"]["case_planting"]
        if assessment.agent_name == "risk_agent"
    )

    assert decision.action.value == "approved"
    assert decision.risk_score < 40
    assert risk_assessment.output["risk_score"] < 40
    assert result["metrics"]["accuracy"] == 1.0


class SlowEvidenceProvider:
    """测试并发用的慢证据提供器。"""

    def __init__(self):
        self.active_count = 0
        self.max_active = 0
        self.lock = Lock()

    def fetch(self, case_id: str, company_name: str) -> EvidencePackage:
        with self.lock:
            self.active_count += 1
            self.max_active = max(self.max_active, self.active_count)

        time.sleep(0.05)

        with self.lock:
            self.active_count -= 1

        return _evidence(case_id=case_id, company_name=company_name)


class FastClassificationProvider:
    """快速返回审批结论的测试分类 provider。"""

    def classify(self, audit_case, evidence, candidate_rules) -> SemanticClassificationResult:
        return _classification_result()


class Level2PartialPathClassificationProvider(OpenAICompatibleClassificationProvider):
    """模拟真实 LLM 返回合法二级候选路径，matched_level3 为空。"""

    def _call_llm(self, prompt: str) -> str:
        return """
        {
          "result": "supports_entered_category",
          "confidence": 88,
          "matched_level1": "种植业",
          "matched_level2": "蔬菜作物",
          "matched_level3": "",
          "matched_category_candidate_ids": ["category_1", "category_2"],
          "unsupported_entered_values": [],
          "evidence_quotes": ["官网显示公司从事蔬菜种植和水果种植。"],
          "reason": "证据同时支持蔬菜作物和水果作物。",
          "suggestion": ""
        }
        """


class PlantingEvidenceProvider:
    """构造同时支持蔬菜和水果种植的证据。"""

    def fetch(self, case_id: str, company_name: str) -> EvidencePackage:
        return EvidencePackage(
            case_id=case_id,
            company_name=company_name,
            sources=["fake"],
            business_scope="公司主要从事蔬菜种植、水果种植和农产品销售。",
            snippets=[
                EvidenceSnippet(source="fake", text="建设蔬菜种植基地", url=""),
                EvidenceSnippet(source="fake", text="开展水果种植和采摘业务", url=""),
            ],
            quality_score=90,
            errors=[],
        )


class SlowClassificationProvider:
    """测试并发用的慢分类 provider。"""

    def __init__(self):
        self.active_count = 0
        self.max_active = 0
        self.lock = Lock()

    def classify(self, audit_case, evidence, candidate_rules) -> SemanticClassificationResult:
        with self.lock:
            self.active_count += 1
            self.max_active = max(self.max_active, self.active_count)

        time.sleep(0.05)

        with self.lock:
            self.active_count -= 1

        return _classification_result()


def _build_case(case_id: str) -> AuditCase:
    """构造测试用审批单。"""
    return AuditCase(
        case_id=case_id,
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


def _software_rule() -> CategoryRule:
    """构造测试用软件开发规则。"""
    return CategoryRule(
        level1="信软技术服务",
        level2="软件和信息技术",
        level3="软件开发",
        module="业务领域",
        keywords=["软件开发", "系统集成"],
    )


def _planting_rules() -> list[CategoryRule]:
    """构造二级候选对应的三级规则。"""
    return [
        CategoryRule(
            level1="种植业",
            level2="蔬菜作物",
            level3="叶菜类",
            module="业务领域",
            keywords=["蔬菜作物", "蔬菜种植"],
        ),
        CategoryRule(
            level1="种植业",
            level2="水果作物",
            level3="仁果类",
            module="业务领域",
            keywords=["水果作物", "水果种植"],
        ),
    ]


def _evidence(case_id: str, company_name: str) -> EvidencePackage:
    """构造测试用证据包。"""
    return EvidencePackage(
        case_id=case_id,
        company_name=company_name,
        sources=["fake"],
        business_scope="公司主要提供软件开发和系统集成服务。",
        snippets=[
            EvidenceSnippet(
                source="fake",
                text="提供软件开发服务",
                url="",
            )
        ],
        quality_score=90,
        errors=[],
    )


def _classification_result() -> SemanticClassificationResult:
    """构造测试用分类结果。"""
    return SemanticClassificationResult(
        result="supports_entered_category",
        confidence=90,
        matched_level1="信软技术服务",
        matched_level2="软件和信息技术",
        matched_level3="软件开发",
        evidence_quotes=["提供软件开发服务"],
        reason="证据支持员工录入分类。",
        suggestion="",
    )
