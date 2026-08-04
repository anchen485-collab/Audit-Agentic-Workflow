from app.agents.classification_agent import (
    ClassificationAgent,
    build_insufficient_evidence_reason,
    classify_audit_case,
)
from app.agents.llm_classification_provider import SemanticClassificationResult
from app.domain.decisions import DecisionAction
from app.domain.models import (
    AuditCase,
    CandidateCategory,
    CandidateRuleSet,
    CategoryRule,
    EvidencePackage,
    EvidenceSnippet,
)


def _build_case(
    entered_level1: str = "信软技术服务",
    entered_subcategory: str = "软件开发",
) -> AuditCase:
    return AuditCase(
        case_id="case_001",
        batch_id="batch_001",
        row_number=2,
        employee_name="张三",
        company_raw="杭州云启软件有限公司 https://yunqi.example.com",
        company_name="杭州云启软件有限公司",
        website_url="https://yunqi.example.com",
        entered_level1=entered_level1,
        entered_subcategory=entered_subcategory,
        entered_stage="录入",
        status="pending",
    )


def _software_rule() -> CategoryRule:
    return CategoryRule(
        level1="信软技术服务",
        level2="软件和信息技术",
        level3="软件开发",
        module="业务领域",
        keywords=["软件开发", "系统集成", "数据平台"],
    )


def test_classify_approves_when_evidence_supports_entered_rule():
    """证据支持员工录入分类时，应该自动通过。"""
    audit_case = _build_case()
    evidence = EvidencePackage(
        case_id="case_001",
        company_name="杭州云启软件有限公司",
        sources=["mock_company_provider"],
        business_scope="公司主要提供软件开发和系统集成服务。",
        snippets=[
            EvidenceSnippet(
                source="mock_company_provider",
                text="提供软件开发服务",
                url="",
            )
        ],
        quality_score=90,
        errors=[],
    )
    candidate_rules = CandidateRuleSet(
        case_id="case_001",
        entered_path_exists=True,
        candidates=[_software_rule()],
        retrieval_reason="命中软件开发规则。",
    )

    decision = classify_audit_case(audit_case, evidence, candidate_rules)

    assert decision.action == DecisionAction.APPROVED
    assert decision.needs_review is False


def test_classify_needs_more_evidence_when_evidence_quality_is_low():
    """证据质量过低时，应该进入证据不足流程。"""
    audit_case = _build_case()
    evidence = EvidencePackage(
        case_id="case_001",
        company_name="南京星河科技有限公司",
        sources=[],
        business_scope="",
        snippets=[],
        quality_score=0,
        errors=["官网链接缺失"],
    )
    candidate_rules = CandidateRuleSet(
        case_id="case_001",
        entered_path_exists=True,
        candidates=[_software_rule()],
        retrieval_reason="命中软件开发规则。",
    )

    decision = classify_audit_case(audit_case, evidence, candidate_rules)

    assert decision.action == DecisionAction.NEEDS_MORE_EVIDENCE
    assert decision.needs_review is True


def test_classification_agent_skips_llm_when_evidence_insufficient():
    """证据不足时应该直接返回 insufficient_evidence，不再调用 LLM provider。"""
    provider = CountingClassificationProvider()
    agent = ClassificationAgent(provider=provider)

    result = agent.run(
        audit_case=_build_case(),
        evidence=EvidencePackage(
            case_id="case_001",
            company_name="官网失败公司",
            sources=[],
            business_scope="",
            snippets=[],
            quality_score=0,
            errors=["官网访问失败：502 Bad Gateway"],
        ),
        candidate_rules=CandidateRuleSet(
            case_id="case_001",
            entered_path_exists=True,
            candidates=[_software_rule()],
            retrieval_reason="测试规则",
        ),
    )

    assert provider.call_count == 0
    assert result.value.result == "insufficient_evidence"
    assert "官网访问失败" in result.value.reason
    assert result.assessment.output["evidence_error_type"] == "evidence_unavailable"


def test_build_insufficient_evidence_reason_prefers_provider_errors():
    """有采集错误时，证据不足原因应该优先展示真实错误。"""
    reason = build_insufficient_evidence_reason(
        EvidencePackage(
            case_id="case_001",
            company_name="官网失败公司",
            sources=[],
            business_scope="",
            snippets=[],
            quality_score=0,
            errors=["官网访问失败：403 Forbidden"],
        )
    )

    assert "官网访问失败：403 Forbidden" in reason


def test_build_insufficient_evidence_reason_handles_empty_business_scope():
    """没有业务描述时，应该明确提示未采集到有效业务描述。"""
    reason = build_insufficient_evidence_reason(
        EvidencePackage(
            case_id="case_001",
            company_name="空证据公司",
            sources=["website"],
            business_scope="",
            snippets=[EvidenceSnippet(source="website", text="公司简介", url="")],
            quality_score=80,
            errors=[],
        )
    )

    assert "未采集到有效业务描述" in reason


def test_build_insufficient_evidence_reason_handles_empty_snippets():
    """没有证据片段时，应该明确提示未抽取到有效业务片段。"""
    reason = build_insufficient_evidence_reason(
        EvidencePackage(
            case_id="case_001",
            company_name="空片段公司",
            sources=["website"],
            business_scope="公司提供业务服务。",
            snippets=[],
            quality_score=80,
            errors=[],
        )
    )

    assert "未抽取到有效业务片段" in reason


def test_classify_needs_human_review_when_entered_path_not_exists():
    """员工录入分类不存在于规则库时，应该进入人工复核。"""
    audit_case = _build_case(
        entered_level1="未来产业服务",
        entered_subcategory="元宇宙生态运营",
    )
    evidence = EvidencePackage(
        case_id="case_001",
        company_name="深圳新界互动科技有限公司",
        sources=["mock_company_provider"],
        business_scope="公司提供数字孪生展示系统和软件开发服务。",
        snippets=[
            EvidenceSnippet(
                source="mock_company_provider",
                text="提供数字孪生展示系统和软件开发服务",
                url="",
            )
        ],
        quality_score=76,
        errors=[],
    )
    candidate_rules = CandidateRuleSet(
        case_id="case_001",
        entered_path_exists=False,
        candidates=[_software_rule()],
        retrieval_reason="员工录入分类不在规则库中。",
    )

    decision = classify_audit_case(audit_case, evidence, candidate_rules)

    assert decision.action == DecisionAction.NEEDS_HUMAN_REVIEW
    assert decision.needs_review is True


def test_classify_rejects_when_evidence_does_not_support_entered_rule():
    """证据不支持员工录入分类时，应该自动驳回。"""
    audit_case = _build_case(
        entered_level1="机械设备厂",
        entered_subcategory="医疗设备",
    )
    evidence = EvidencePackage(
        case_id="case_001",
        company_name="广州会联展览服务有限公司",
        sources=["mock_company_provider"],
        business_scope="公司主要承办行业展会、会议论坛和会务服务。",
        snippets=[
            EvidenceSnippet(
                source="mock_company_provider",
                text="提供展台设计搭建和会务服务",
                url="",
            )
        ],
        quality_score=84,
        errors=[],
    )
    candidate_rules = CandidateRuleSet(
        case_id="case_001",
        entered_path_exists=True,
        candidates=[_software_rule()],
        retrieval_reason="召回会展服务相关规则。",
    )

    decision = classify_audit_case(audit_case, evidence, candidate_rules)

    assert decision.action == DecisionAction.REJECTED
    assert decision.needs_review is False


def test_classify_ignores_generic_ecology_keywords_when_matching_evidence():
    """会展、会议等生态泛词不能让医疗设备分类误通过。"""
    audit_case = _build_case(
        entered_level1="机械设备厂",
        entered_subcategory="医疗设备",
    )
    evidence = EvidencePackage(
        case_id="case_001",
        company_name="广州会联展览服务有限公司",
        sources=["mock_company_provider"],
        business_scope="公司主要承办行业展会、会议论坛、展台设计搭建、品牌展示和会务服务。",
        snippets=[
            EvidenceSnippet(
                source="mock_company_provider",
                text="提供展台设计搭建和会务服务",
                url="",
            )
        ],
        quality_score=84,
        errors=[],
    )
    candidate_rules = CandidateRuleSet(
        case_id="case_001",
        entered_path_exists=True,
        candidates=[_medical_device_ecology_rule()],
        retrieval_reason="召回医疗设备规则。",
    )

    decision = classify_audit_case(audit_case, evidence, candidate_rules)

    assert decision.action == DecisionAction.REJECTED


def test_classify_supports_medical_device_by_business_synonyms():
    """医疗器械、医用检测设备等证据可以支持医疗设备分类。"""
    audit_case = _build_case(
        entered_level1="机械设备厂",
        entered_subcategory="医疗设备",
    )
    evidence = EvidencePackage(
        case_id="case_001",
        company_name="广州康复设备有限公司",
        sources=["mock_company_provider"],
        business_scope="公司专注医用检测设备、康复设备、医疗器械配套系统的研发、生产和销售。",
        snippets=[
            EvidenceSnippet(
                source="mock_company_provider",
                text="提供医疗器械配套系统研发生产",
                url="",
            )
        ],
        quality_score=88,
        errors=[],
    )
    candidate_rules = CandidateRuleSet(
        case_id="case_001",
        entered_path_exists=True,
        candidates=[_medical_device_ecology_rule()],
        retrieval_reason="召回医疗设备规则。",
    )

    decision = classify_audit_case(audit_case, evidence, candidate_rules)

    assert decision.action == DecisionAction.APPROVED


def test_classification_accepts_supported_level2_category():
    """员工填的是二级分类时，证据支持该二级业务方向即可自动通过。"""
    audit_case = _build_case(
        entered_level1="卫生和社会工作",
        entered_subcategory="医院",
    )
    evidence = EvidencePackage(
        case_id="case_001",
        company_name="测试医院",
        sources=["website"],
        business_scope="该机构主要提供医院诊疗、住院和门诊医疗服务。",
        snippets=[EvidenceSnippet(source="website", text="提供医院诊疗服务", url="https://example.com")],
        quality_score=90,
        errors=[],
    )
    candidate_rules = CandidateRuleSet(
        case_id="case_001",
        entered_path_exists=True,
        candidates=[
            CategoryRule(
                level1="卫生和社会工作",
                level2="医院",
                level3="专科医院",
                module="业务领域",
                keywords=["专科医院"],
            )
        ],
        category_candidates=[
            CandidateCategory(
                level1="卫生和社会工作",
                level2="医院",
                granularity="level2",
                matched_entered_value="医院",
                child_count=1,
                keywords=["医院", "诊疗", "住院", "门诊"],
            )
        ],
        entered_subcategory_granularity="level2",
        granularity_reason="员工录入细分命中二级分类。",
        retrieval_reason="命中二级医院。",
    )

    decision = classify_audit_case(audit_case, evidence, candidate_rules)

    assert decision.action == DecisionAction.APPROVED
    assert "二级分类" in decision.reason


def test_level2_multi_subcategories_require_all_values_supported():
    """员工一次填多个二级分类时，证据必须覆盖全部录入值才能自动通过。"""
    audit_case = _build_case(
        entered_level1="种植业",
        entered_subcategory="蔬菜作物,水果作物",
    )
    candidate_rules = _level2_multi_candidate_rules()
    partial_evidence = EvidencePackage(
        case_id="case_001",
        company_name="青山农业有限公司",
        sources=["website"],
        business_scope="公司主要从事蔬菜种植和农产品销售。",
        snippets=[EvidenceSnippet(source="website", text="建设蔬菜种植基地", url="https://example.com")],
        quality_score=90,
        errors=[],
    )
    full_evidence = EvidencePackage(
        case_id="case_001",
        company_name="青山农业有限公司",
        sources=["website"],
        business_scope="公司主要从事蔬菜种植、水果种植和农产品销售。",
        snippets=[
            EvidenceSnippet(source="website", text="建设蔬菜种植基地", url="https://example.com"),
            EvidenceSnippet(source="website", text="开展水果种植和采摘业务", url="https://example.com"),
        ],
        quality_score=90,
        errors=[],
    )

    partial_decision = classify_audit_case(audit_case, partial_evidence, candidate_rules)
    full_decision = classify_audit_case(audit_case, full_evidence, candidate_rules)

    assert partial_decision.action == DecisionAction.NEEDS_HUMAN_REVIEW
    assert "水果作物" in partial_decision.reason
    assert full_decision.action == DecisionAction.APPROVED


def test_classification_requires_level3_evidence_for_level3_input():
    """员工填三级分类时，只命中二级词不能自动通过该三级分类。"""
    audit_case = _build_case(
        entered_level1="卫生和社会工作",
        entered_subcategory="专科医院",
    )
    evidence = EvidencePackage(
        case_id="case_001",
        company_name="测试医院",
        sources=["website"],
        business_scope="该机构主要提供医院诊疗、住院和门诊医疗服务。",
        snippets=[EvidenceSnippet(source="website", text="提供医院诊疗服务", url="https://example.com")],
        quality_score=90,
        errors=[],
    )
    candidate_rules = CandidateRuleSet(
        case_id="case_001",
        entered_path_exists=True,
        candidates=[
            CategoryRule(
                level1="卫生和社会工作",
                level2="医院",
                level3="专科医院",
                module="业务领域",
                keywords=["专科医院", "骨科医院"],
            )
        ],
        category_candidates=[
            CandidateCategory(
                level1="卫生和社会工作",
                level2="医院",
                level3="专科医院",
                granularity="level3",
                matched_entered_value="专科医院",
                keywords=["专科医院", "骨科医院"],
            )
        ],
        entered_subcategory_granularity="level3",
        granularity_reason="员工录入细分命中三级分类。",
        retrieval_reason="命中三级专科医院。",
    )

    decision = classify_audit_case(audit_case, evidence, candidate_rules)

    assert decision.action == DecisionAction.REJECTED
    assert "三级分类" in decision.reason


def test_classification_routes_mixed_or_ambiguous_granularity_to_review():
    """mixed 和 ambiguous 粒度不能自动通过，应该转人工复核。"""
    audit_case = _build_case(
        entered_level1="卫生和社会工作",
        entered_subcategory="医院、专科医院",
    )
    evidence = EvidencePackage(
        case_id="case_001",
        company_name="测试医院",
        sources=["website"],
        business_scope="该机构主要提供医院和专科医院诊疗服务。",
        snippets=[EvidenceSnippet(source="website", text="提供专科医院诊疗服务", url="https://example.com")],
        quality_score=90,
        errors=[],
    )

    for granularity in ["mixed", "ambiguous", "unknown"]:
        candidate_rules = CandidateRuleSet(
            case_id="case_001",
            entered_path_exists=True,
            candidates=[_software_rule()],
            entered_subcategory_granularity=granularity,
            granularity_reason="细分粒度异常。",
            retrieval_reason="测试异常粒度。",
        )

        decision = classify_audit_case(audit_case, evidence, candidate_rules)

        assert decision.action == DecisionAction.NEEDS_HUMAN_REVIEW


def test_classification_agent_marks_mismatched_company_evidence_as_insufficient():
    """官网证据明显属于另一家公司时，应直接判定证据不足且不调用 LLM。"""
    provider = CountingClassificationProvider()
    agent = ClassificationAgent(provider=provider)
    audit_case = AuditCase(
        case_id="case_mismatch_company",
        batch_id="batch_001",
        row_number=2,
        employee_name="刘丹",
        company_raw="普洱淞茂谷林下中药材开发有限公司 http://www.jxddny.com/",
        company_name="普洱淞茂谷林下中药材开发有限公司",
        website_url="http://www.jxddny.com/",
        entered_level1="种植业",
        entered_subcategory="药用作物",
        status="pending",
    )
    evidence = EvidencePackage(
        case_id=audit_case.case_id,
        company_name=audit_case.company_name,
        sources=["website"],
        business_scope="江西大道农业发展有限公司是一家专门从事黄精育苗、种植、加工、收购、销售于一体的公司。",
        snippets=[
            EvidenceSnippet(
                source="website",
                text="江西大道农业发展有限公司主营黄精种苗、九制黄精、黄精茶和黄精酒。",
                url="http://www.jxddny.com/",
            )
        ],
        quality_score=100,
        errors=[],
    )
    candidate_rules = _plant_level2_candidate_rules(["药用作物"])

    result = agent.run(audit_case=audit_case, evidence=evidence, candidate_rules=candidate_rules)

    assert provider.call_count == 0
    assert result.value.result == "insufficient_evidence"
    assert "官网证据与目标企业不一致" in result.value.reason


def test_classification_agent_downgrades_fertilizer_service_targets_to_uncertain():
    """肥料企业只提到产品适用于果树和蔬菜时，不能自动通过作物分类。"""
    agent = ClassificationAgent(provider=SupportsAllClassificationProvider())
    audit_case = AuditCase(
        case_id="case_fertilizer_targets",
        batch_id="batch_001",
        row_number=2,
        employee_name="刘丹",
        company_raw="青岛八福仙生物科技有限公司 http://www.bafuxian.com/",
        company_name="青岛八福仙生物科技有限公司",
        website_url="http://www.bafuxian.com/",
        entered_level1="种植业",
        entered_subcategory="水果作物,蔬菜作物",
        status="pending",
    )
    evidence = EvidencePackage(
        case_id=audit_case.case_id,
        company_name=audit_case.company_name,
        sources=["website"],
        business_scope="公司是有机肥厂家，生产有机肥料、有机无机复混肥料、生物肥料和水溶肥料。",
        snippets=[
            EvidenceSnippet(
                source="website",
                text="肥料在果树、蔬菜、根茎类、茶桑、粮油等经济作物效果明显。",
                url="http://www.bafuxian.com/",
            )
        ],
        quality_score=100,
        errors=[],
    )
    candidate_rules = _plant_level2_candidate_rules(["水果作物", "蔬菜作物"])

    result = agent.run(audit_case=audit_case, evidence=evidence, candidate_rules=candidate_rules)

    assert result.value.result == "uncertain"
    assert "肥料" in result.value.reason
    assert "服务对象" in result.value.reason


def test_classification_agent_uses_deterministic_fallback_when_provider_times_out():
    """LLM 超时但确定性规则可判断时，不应该直接降级成人工复核。"""
    agent = ClassificationAgent(provider=TimeoutClassificationProvider())
    audit_case = _build_case()
    evidence = EvidencePackage(
        case_id=audit_case.case_id,
        company_name=audit_case.company_name,
        sources=["website"],
        business_scope="杭州云启软件有限公司主要提供软件开发和系统集成服务。",
        snippets=[
            EvidenceSnippet(
                source="website",
                text="杭州云启软件有限公司为客户提供软件开发服务。",
                url="https://yunqi.example.com",
            )
        ],
        quality_score=90,
        errors=[],
    )
    candidate_rules = CandidateRuleSet(
        case_id=audit_case.case_id,
        entered_path_exists=True,
        candidates=[_software_rule()],
        retrieval_reason="员工录入分类命中软件开发规则。",
    )

    result = agent.run(audit_case=audit_case, evidence=evidence, candidate_rules=candidate_rules)

    assert result.value.result == "supports_entered_category"
    assert "确定性规则兜底" in result.value.reason


def test_company_mismatch_fertilizer_service_target_routes_to_uncertain():
    """肥料服务对象误分类应进入人工复核，不应被公司名保护提前改成证据不足。"""
    provider = CountingClassificationProvider()
    agent = ClassificationAgent(provider=provider)
    audit_case = AuditCase(
        case_id="case_fertilizer_mismatch_name",
        batch_id="batch_001",
        row_number=2,
        employee_name="刘丹",
        company_raw="青岛八福仙生物科技有限公司 http://www.bafuxian.com/",
        company_name="青岛八福仙生物科技有限公司",
        website_url="http://www.bafuxian.com/",
        entered_level1="种植业",
        entered_subcategory="水果作物,蔬菜作物",
        status="pending",
    )
    evidence = EvidencePackage(
        case_id=audit_case.case_id,
        company_name=audit_case.company_name,
        sources=["website"],
        business_scope="四川什邡德美实业有限公司是一家肥料生产企业，主营有机肥、水溶肥，根据农场种植的作物提供施肥方案。",
        snippets=[
            EvidenceSnippet(
                source="website",
                text="肥料产品适用于果树、蔬菜等经济作物。",
                url="http://www.bafuxian.com/",
            )
        ],
        quality_score=100,
        errors=[],
    )
    candidate_rules = _plant_level2_candidate_rules(["水果作物", "蔬菜作物"])

    result = agent.run(audit_case=audit_case, evidence=evidence, candidate_rules=candidate_rules)

    assert provider.call_count == 0
    assert result.value.result == "uncertain"
    assert "服务对象" in result.value.reason


class SupportsAllClassificationProvider:
    """测试用 provider，模拟 LLM 认为全部员工录入分类都被证据支持。"""

    def classify(self, audit_case, evidence, candidate_rules):
        return SemanticClassificationResult(
            result="supports_entered_category",
            confidence=95,
            matched_candidate_rule_id="rule_1",
            matched_category_candidate_ids=[
                f"category_{index + 1}"
                for index, _ in enumerate(candidate_rules.category_candidates)
            ],
            matched_level1="种植业",
            matched_level2="水果作物",
            matched_level3="",
            evidence_quotes=["肥料适用于果树和蔬菜。"],
            reason="证据显示产品适用于果树和蔬菜，因此支持员工录入分类。",
            suggestion="种植业 / 水果作物；种植业 / 蔬菜作物",
        )


def _plant_level2_candidate_rules(level2_values: list[str]) -> CandidateRuleSet:
    """构造种植业二级分类候选，模拟真实规则召回结果。"""
    rules = [
        CategoryRule(
            level1="种植业",
            level2=level2,
            level3=_default_level3_for_level2(level2),
            module="业务领域",
            keywords=[level2, *_default_keywords_for_level2(level2)],
        )
        for level2 in level2_values
    ]

    return CandidateRuleSet(
        case_id="case_001",
        entered_path_exists=True,
        candidates=rules,
        category_candidates=[
            CandidateCategory(
                level1="种植业",
                level2=rule.level2,
                level3="",
                granularity="level2",
                matched_entered_value=rule.level2,
                child_count=1,
                children=[rule],
                keywords=[rule.level2, *rule.keywords],
            )
            for rule in rules
        ],
        entered_subcategory_granularity="level2",
        granularity_reason="员工录入细分命中二级分类。",
        retrieval_reason="员工录入分类存在于规则库。",
    )


def _default_level3_for_level2(level2: str) -> str:
    """为测试规则补一个合法三级分类。"""
    mapping = {
        "水果作物": "瓜果类",
        "蔬菜作物": "食用菌",
        "药用作物": "根茎类",
    }
    return mapping.get(level2, "其他")


def _default_keywords_for_level2(level2: str) -> list[str]:
    """为测试规则补充能触发语义判断的关键词。"""
    mapping = {
        "水果作物": ["果树", "西瓜", "甜瓜"],
        "蔬菜作物": ["蔬菜", "食用菌"],
        "药用作物": ["黄精", "中药材"],
    }
    return mapping.get(level2, [])


def _medical_device_ecology_rule() -> CategoryRule:
    """构造带生态泛词的医疗设备规则，模拟正式规则表里的重复路径。"""
    return CategoryRule(
        level1="机械设备厂",
        level2="专用设备厂",
        level3="医疗设备",
        module="生态",
        keywords=["机械设备厂", "专用设备厂", "医疗设备", "生态", "网站", "会展", "协会", "会议"],
    )


def _level2_multi_candidate_rules() -> CandidateRuleSet:
    """构造两个二级候选，模拟员工细分用逗号录入多个分类。"""
    return CandidateRuleSet(
        case_id="case_001",
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


class CountingClassificationProvider:
    """测试用 provider，用于确认证据不足时不会被调用。"""

    def __init__(self):
        self.call_count = 0

    def classify(self, audit_case, evidence, candidate_rules):
        self.call_count += 1
        return SemanticClassificationResult(
            result="supports_entered_category",
            confidence=90,
            matched_level1="",
            matched_level2="",
            matched_level3="",
            evidence_quotes=[],
            reason="不应该被调用",
            suggestion="",
        )


class TimeoutClassificationProvider:
    """测试用 provider，模拟 LLM 调用最终超时。"""

    def classify(self, audit_case, evidence, candidate_rules):
        raise TimeoutError("llm timeout")

