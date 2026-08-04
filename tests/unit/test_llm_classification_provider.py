import json

import httpx
import pytest

from app.agents.llm_classification_provider import (
    MockClassificationProvider,
    OpenAICompatibleClassificationProvider,
    SemanticClassificationResult,
    _build_classification_prompt,
    _validate_candidate_rule,
)
from app.domain.errors import LLMInvalidJsonError, LLMOutputError
from app.domain.models import (
    AuditCase,
    CandidateCategory,
    CandidateRuleSet,
    CategoryRule,
    EvidencePackage,
    EvidenceSnippet,
)


def test_mock_classification_provider_returns_structured_result():
    """mock provider 只返回语义判断，不直接返回最终审批动作。"""
    provider = MockClassificationProvider()

    audit_case = _build_case()
    evidence = _build_evidence()
    candidate_rules = _build_candidate_rules()

    result = provider.classify(
        audit_case=audit_case,
        evidence=evidence,
        candidate_rules=candidate_rules,
    )

    assert isinstance(result, SemanticClassificationResult)
    assert not hasattr(result, "action")
    assert result.result == "supports_entered_category"
    assert result.confidence >= 0
    assert result.reason


def test_classification_prompt_does_not_treat_empty_level2_as_missing_business_path():
    """没有二级列时，prompt 不应该诱导 LLM 输出“未填写二级”。"""
    audit_case = AuditCase(
        case_id="case_001",
        batch_id="batch_001",
        row_number=2,
        employee_name="刘丹",
        company_raw="示例渔业有限公司 https://example.com",
        company_name="示例渔业有限公司",
        website_url="https://example.com",
        entered_level1="渔业",
        entered_subcategory="海水捕捞",
        status="pending",
    )

    prompt = _build_classification_prompt(
        audit_case=audit_case,
        evidence=_build_evidence(),
        candidate_rules=_build_candidate_rules(),
    )

    assert "未填写二级" not in prompt
    assert "细分分类可能是二级分类，也可能是三级分类" in prompt
    assert "如果细分分类包含多个值，需要拆开逐项判断" in prompt
    assert "员工录入分类：渔业 / 海水捕捞" in prompt
    assert "细分粒度识别" in prompt
    assert "如果细分粒度识别为 level3，证据必须支持该具体三级分类" in prompt
    assert "level3 判断不是字符串精确匹配" in prompt
    assert "同义词或上下位概念" in prompt
    assert "rule_1:" in prompt
    assert "matched_candidate_rule_id" in prompt


class FakeOpenAIProvider(OpenAICompatibleClassificationProvider):
    """测试用真实 provider，避免调用外部接口。"""

    def _call_llm(self, prompt: str) -> str:
        return """
        {
          "result": "supports_entered_category",
          "confidence": 90,
          "matched_candidate_rule_id": "rule_1",
          "matched_level1": "信软技术服务",
          "matched_level2": "软件和信息技术",
          "matched_level3": "软件开发",
          "evidence_quotes": ["官网介绍显示，公司提供软件开发和系统集成服务。"],
          "reason": "证据支持员工录入分类。",
          "suggestion": ""
        }
        """


class InvalidJsonOpenAIProvider(OpenAICompatibleClassificationProvider):
    """测试用 provider：模拟 LLM 返回非法 JSON。"""

    def _call_llm(self, prompt: str) -> str:
        return "this is not json"


class PartialPathOpenAIProvider(OpenAICompatibleClassificationProvider):
    """测试用 provider：模拟 LLM 只返回了部分旧分类路径。"""

    def _call_llm(self, prompt: str) -> str:
        return """
        {
          "result": "conflicts_with_entered_category",
          "confidence": 88,
          "matched_level1": "信软技术服务",
          "matched_level2": "",
          "matched_level3": "",
          "evidence_quotes": ["官网只显示软件服务。"],
          "reason": "证据没有返回完整候选规则。",
          "suggestion": ""
        }
        """


class Level2PartialPathOpenAIProvider(OpenAICompatibleClassificationProvider):
    """测试用 provider：模拟 LLM 返回合法二级候选路径。"""

    def _call_llm(self, prompt: str) -> str:
        return """
        {
          "result": "supports_entered_category",
          "confidence": 88,
          "matched_level1": "种植业",
          "matched_level2": "蔬菜作物",
          "matched_level3": "",
          "matched_category_candidate_ids": ["category_1"],
          "unsupported_entered_values": [],
          "evidence_quotes": ["官网显示公司种植蔬菜。"],
          "reason": "证据支持蔬菜作物。",
          "suggestion": ""
        }
        """


def test_openai_provider_rejects_rule_outside_candidates():
    """LLM 编造候选规则之外的分类时，应该被结构化校验拦住。"""
    raw = {
        "result": "conflicts_with_entered_category",
        "confidence": 90,
        "matched_level1": "不存在的一级",
        "matched_level2": "不存在的二级",
        "matched_level3": "不存在的三级",
        "evidence_quotes": ["证据片段"],
        "reason": "证据更像不存在的分类。",
        "suggestion": "不存在的一级 / 不存在的二级 / 不存在的三级",
    }

    result = SemanticClassificationResult.model_validate(raw)

    with pytest.raises(LLMOutputError):
        _validate_candidate_rule(result, _build_candidate_rules())


def test_semantic_result_accepts_matched_candidate_rule_id():
    """新的 LLM 协议应该支持按候选规则 ID 返回匹配结果。"""
    result = SemanticClassificationResult.model_validate(
        {
            "result": "conflicts_with_entered_category",
            "confidence": 80,
            "matched_candidate_rule_id": "rule_1",
            "evidence_quotes": ["官网显示提供软件开发服务。"],
            "reason": "证据更支持 rule_1。",
            "suggestion": "rule_1",
        }
    )

    assert result.matched_candidate_rule_id == "rule_1"


def test_validate_candidate_rule_rejects_invalid_candidate_rule_id():
    """LLM 返回不存在的候选规则 ID 时，应该被拦截。"""
    result = SemanticClassificationResult(
        result="conflicts_with_entered_category",
        confidence=80,
        matched_candidate_rule_id="rule_999",
        evidence_quotes=[],
        reason="证据更支持不存在的规则。",
        suggestion="rule_999",
    )

    with pytest.raises(LLMOutputError):
        _validate_candidate_rule(result, _build_candidate_rules())


def test_validate_candidate_rule_allows_empty_id_for_uncertain_result():
    """uncertain 或证据不足时可以不返回候选规则 ID。"""
    result = SemanticClassificationResult(
        result="uncertain",
        confidence=50,
        matched_candidate_rule_id="",
        evidence_quotes=[],
        reason="无法判断主营业务。",
        suggestion="请人工确认。",
    )

    _validate_candidate_rule(result, _build_candidate_rules())


def test_openai_provider_raises_typed_error_for_invalid_json():
    """LLM 返回非法 JSON 时，应该抛出可识别的错误类型。"""
    provider = InvalidJsonOpenAIProvider(
        api_key="fake",
        base_url="https://example.com",
        model="fake-model",
    )

    with pytest.raises(LLMInvalidJsonError) as error:
        provider.classify(_build_case(), _build_evidence(), _build_candidate_rules())

    assert error.value.error_code == "llm_invalid_json"
    assert "this is not json" in str(error.value)


def test_openai_provider_downgrades_partial_legacy_path_to_uncertain():
    """LLM 只返回部分旧分类路径时，不应该让 Agent failed。"""
    provider = PartialPathOpenAIProvider(
        api_key="fake",
        base_url="https://example.com",
        model="fake-model",
    )

    result = provider.classify(_build_planting_case(), _build_planting_evidence(), _build_level2_candidate_rules())

    assert result.result == "uncertain"
    assert result.normalization_warning
    assert result.matched_path() == ("", "", "")


def test_normalize_allows_partial_path_for_level2_candidate():
    """level2 粒度下，LLM 返回 level1 + level2 且 level3 为空是合法输出。"""
    provider = Level2PartialPathOpenAIProvider(
        api_key="fake",
        base_url="https://example.com",
        model="fake-model",
    )

    result = provider.classify(_build_planting_case(), _build_planting_evidence(), _build_level2_candidate_rules())

    assert result.result == "supports_entered_category"
    assert result.confidence == 88
    assert result.normalization_warning == ""
    assert result.matched_path() == ("种植业", "蔬菜作物", "")


def test_validate_candidate_rule_accepts_level2_category_candidate():
    """二级候选路径必须能通过候选合法性校验。"""
    result = SemanticClassificationResult(
        result="supports_entered_category",
        confidence=88,
        matched_level1="种植业",
        matched_level2="蔬菜作物",
        matched_level3="",
        evidence_quotes=[],
        reason="证据支持蔬菜作物。",
        suggestion="",
    )

    _validate_candidate_rule(result, _build_level2_candidate_rules())


def test_validate_candidate_rule_rejects_unknown_level2_category():
    """LLM 返回不存在的二级候选时，仍然必须被校验拦截。"""
    result = SemanticClassificationResult(
        result="supports_entered_category",
        confidence=88,
        matched_level1="种植业",
        matched_level2="不存在作物",
        matched_level3="",
        evidence_quotes=[],
        reason="证据支持不存在作物。",
        suggestion="",
    )

    with pytest.raises(LLMOutputError):
        _validate_candidate_rule(result, _build_level2_candidate_rules())


def test_prompt_includes_category_candidate_ids():
    """prompt 应该给二级/三级分类候选展示稳定 ID，方便 LLM 返回多个命中候选。"""
    prompt = _build_classification_prompt(
        audit_case=_build_planting_case(),
        evidence=_build_planting_evidence(),
        candidate_rules=_build_level2_candidate_rules(),
    )

    assert "category_1" in prompt
    assert "category_2" in prompt
    assert "matched_category_candidate_ids" in prompt
    assert "matched_level3 可以为空" in prompt


def test_semantic_result_supports_multiple_category_candidate_ids():
    """LLM 结果应该能表达多个二级候选都被证据支持，以及哪些录入值未被支持。"""
    result = SemanticClassificationResult(
        result="supports_entered_category",
        confidence=90,
        matched_category_candidate_ids=["category_1", "category_2"],
        unsupported_entered_values=[],
        evidence_quotes=[],
        reason="证据同时支持蔬菜作物和水果作物。",
        suggestion="",
    )

    assert result.matched_category_candidate_ids == ["category_1", "category_2"]
    assert result.unsupported_entered_values == []


def test_openai_provider_retries_timeout_once_and_then_succeeds():
    """LLM 接口偶发超时时，provider 应有限重试并返回第二次成功结果。"""
    call_count = {"value": 0}

    def flaky_post(*args, **kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            raise httpx.ReadTimeout("read timeout")

        return _fake_classification_response()

    provider = OpenAICompatibleClassificationProvider(
        api_key="fake",
        base_url="https://example.com",
        model="fake-model",
        http_post=flaky_post,
    )

    result = provider.classify(_build_planting_case(), _build_planting_evidence(), _build_level2_candidate_rules())

    assert call_count["value"] == 2
    assert result.result == "supports_entered_category"


def test_openai_provider_health_check_success():
    """LLM 健康检查成功时应该返回 ok=true。"""
    provider = OpenAICompatibleClassificationProvider(
        api_key="fake",
        base_url="https://example.com",
        model="fake-model",
        http_post=lambda *args, **kwargs: _fake_llm_response(200),
    )

    result = provider.health_check()

    assert result["ok"] is True


def test_openai_provider_health_check_reports_401():
    """LLM 健康检查遇到 401 时应该返回认证失败提示。"""
    provider = OpenAICompatibleClassificationProvider(
        api_key="bad-key",
        base_url="https://example.com",
        model="fake-model",
        http_post=lambda *args, **kwargs: _fake_llm_response(401),
    )

    result = provider.health_check()

    assert result["ok"] is False
    assert result["error_type"] == "llm_provider_auth"
    assert "认证失败" in result["message"]


def test_openai_provider_health_check_reports_network_error():
    """LLM 健康检查遇到网络异常时应该返回明确提示。"""

    def broken_post(*args, **kwargs):
        raise httpx.ConnectError("network down")

    provider = OpenAICompatibleClassificationProvider(
        api_key="fake",
        base_url="https://example.com",
        model="fake-model",
        http_post=broken_post,
    )

    result = provider.health_check()

    assert result["ok"] is False
    assert result["error_type"] == "llm_network_error"


def _build_case() -> AuditCase:
    """构造一条测试用审批单。"""
    return AuditCase(
        case_id="case_001",
        batch_id="batch_001",
        row_number=2,
        employee_name="张三",
        company_raw="杭州云启软件有限公司 https://yunqi.example.com",
        company_name="杭州云启软件有限公司",
        website_url="https://yunqi.example.com",
        entered_level1="信软技术服务",
        entered_subcategory="软件开发",
        entered_stage="录入",
        status="pending",
    )


def _build_evidence() -> EvidencePackage:
    """构造一份测试用的企业证据包。"""
    return EvidencePackage(
        case_id="case_001",
        company_name="杭州云启软件有限公司",
        sources=["mock_company_provider"],
        business_scope="公司主要提供软件开发、系统集成和数据平台建设服务。",
        snippets=[
            EvidenceSnippet(
                source="mock_company_provider",
                text="官网介绍显示，公司提供软件开发和系统集成服务。",
                url="",
            )
        ],
        quality_score=90,
        errors=[],
    )


def _build_candidate_rules() -> CandidateRuleSet:
    """构造一组测试用的候选规则。"""
    return CandidateRuleSet(
        case_id="case_001",
        entered_path_exists=True,
        candidates=[
            CategoryRule(
                level1="信软技术服务",
                level2="软件和信息技术",
                level3="软件开发",
                module="业务领域",
                keywords=["软件开发", "系统集成", "数据平台"],
            )
        ],
        retrieval_reason="测试场景中命中软件开发规则。",
    )


def _build_planting_case() -> AuditCase:
    """构造二级多分类测试审批单。"""
    return AuditCase(
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


def _build_planting_evidence() -> EvidencePackage:
    """构造同时支持蔬菜和水果种植的证据。"""
    return EvidencePackage(
        case_id="case_planting",
        company_name="青山农业有限公司",
        sources=["website"],
        business_scope="公司主要从事蔬菜种植、水果种植和农产品销售。",
        snippets=[
            EvidenceSnippet(source="website", text="开展蔬菜种植基地运营", url=""),
            EvidenceSnippet(source="website", text="开展水果种植和采摘业务", url=""),
        ],
        quality_score=90,
        errors=[],
    )


def _build_level2_candidate_rules() -> CandidateRuleSet:
    """构造包含两个二级分类候选的候选集。"""
    return CandidateRuleSet(
        case_id="case_planting",
        entered_path_exists=True,
        candidates=[
            CategoryRule(
                level1="种植业",
                level2="蔬菜作物",
                level3="叶菜类",
                module="业务领域",
                keywords=["蔬菜种植", "叶菜"],
            ),
            CategoryRule(
                level1="种植业",
                level2="水果作物",
                level3="仁果类",
                module="业务领域",
                keywords=["水果种植", "采摘"],
            ),
        ],
        category_candidates=[
            CandidateCategory(
                level1="种植业",
                level2="蔬菜作物",
                granularity="level2",
                matched_entered_value="蔬菜作物",
                child_count=1,
                keywords=["蔬菜作物", "蔬菜种植"],
            ),
            CandidateCategory(
                level1="种植业",
                level2="水果作物",
                granularity="level2",
                matched_entered_value="水果作物",
                child_count=1,
                keywords=["水果作物", "水果种植"],
            ),
        ],
        entered_subcategory_granularity="level2",
        granularity_reason="员工录入细分命中二级分类。",
        retrieval_reason="命中二级作物分类。",
    )


def _fake_llm_response(status_code: int) -> httpx.Response:
    """构造 OpenAI-compatible 响应。"""
    request = httpx.Request("POST", "https://example.com/chat/completions")
    if status_code != 200:
        return httpx.Response(status_code=status_code, request=request, json={"error": "failed"})

    return httpx.Response(
        status_code=200,
        request=request,
        json={
            "choices": [
                {
                    "message": {
                        "content": "{\"ok\": true}",
                    }
                }
            ]
        },
    )


def _fake_classification_response() -> httpx.Response:
    """构造一个合法的审批语义判断响应。"""
    request = httpx.Request("POST", "https://example.com/chat/completions")
    return httpx.Response(
        status_code=200,
        request=request,
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "result": "supports_entered_category",
                                "confidence": 90,
                                "matched_candidate_rule_id": "",
                                "matched_category_candidate_ids": ["category_1", "category_2"],
                                "matched_level1": "种植业",
                                "matched_level2": "蔬菜作物",
                                "matched_level3": "",
                                "evidence_quotes": ["官网显示公司种植蔬菜和水果。"],
                                "reason": "证据支持员工录入分类。",
                                "suggestion": "",
                            },
                            ensure_ascii=False,
                        ),
                    }
                }
            ]
        },
    )
