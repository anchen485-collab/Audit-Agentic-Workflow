import re
from typing import Any

from app.agents.base import run_agent_step
from app.domain.decisions import DecisionAction, DecisionStatus
from app.domain.errors import LLMProviderAuthError
from app.domain.models import (
    AgentAssessment,
    ApprovalDecision,
    AuditCase,
    CandidateRuleSet,
    EvidencePackage,
)
from app.services.category_text import split_entered_subcategories
from app.services.evidence_service import has_sufficient_evidence

GENERIC_EVIDENCE_KEYWORDS = {
    "生态",
    "网站",
    "会展",
    "协会",
    "会议",
    "公众号",
    "银行",
    "基金",
    "保险",
    "法律",
    "物流",
    "人资",
    "产业园",
    "联盟",
    "智库",
    "大赛",
    "院校",
    "报刊",
    "杂志",
    "人才",
    "学会",
    "全产业链",
    "经营",
    "咨询",
    "规划",
    "项目建议书",
    "可研",
    "勘察",
    "设计",
    "造价",
    "监理",
    "审图",
    "施工",
    "检测",
    "安装",
    "销售",
    "研发",
    "生产",
}

FERTILIZER_PROVIDER_KEYWORDS = {
    "肥料",
    "有机肥",
    "水溶肥",
    "复合肥",
    "复混肥",
    "生物肥",
    "农资",
    "作物营养",
}

CROP_LEVEL2_CATEGORIES = {
    "粮食作物",
    "经济作物",
    "水果作物",
    "蔬菜作物",
    "药用作物",
    "花卉作物",
    "其他园艺作物",
    "饲料作物",
}

SERVICE_TARGET_KEYWORDS = {
    "适用于",
    "应用于",
    "用于",
    "服务于",
    "针对",
    "效果明显",
    "增产",
    "提质",
}

STRONG_PLANTING_KEYWORDS = {
    "种植基地",
    "农作物种植",
    "水果种植",
    "蔬菜种植",
    "药材种植",
    "中药材种植",
    "粮食种植",
    "花卉种植",
}

COMPANY_NAME_PATTERN = re.compile(
    r"[\u4e00-\u9fffA-Za-z0-9（）()·]{2,}(?:有限责任公司|股份有限公司|集团有限公司|有限公司|公司)"
)


class ClassificationAgent:
    """语义分类 Agent，负责判断外部证据是否支持员工录入分类。"""

    agent_name = "classification_agent"

    def __init__(self, provider):
        self.provider = provider

    def run(
        self,
        audit_case: AuditCase,
        evidence: EvidencePackage,
        candidate_rules: CandidateRuleSet,
    ):
        """执行语义分类判断，并输出统一 AgentAssessment。"""
        fallback_result = self._fallback_result(audit_case.case_id)

        return run_agent_step(
            agent_name=self.agent_name,
            func=lambda: self._classify(audit_case, evidence, candidate_rules),
            fallback_value=fallback_result,
        )

    def _classify(
        self,
        audit_case: AuditCase,
        evidence: EvidencePackage,
        candidate_rules: CandidateRuleSet,
    ) -> tuple[Any, list[str], dict[str, Any], int]:
        """调用 mock provider 或真实 LLM provider。"""
        if not has_sufficient_evidence(evidence):
            result = self._insufficient_evidence_result(evidence)
            output = result.model_dump(mode="json")
            output["case_id"] = audit_case.case_id
            output["evidence_error_type"] = classify_evidence_insufficient_type(evidence)

            return result, [result.reason], output, result.confidence

        if _is_target_company_mismatch(audit_case, evidence):
            if _has_fertilizer_service_target_risk(evidence, candidate_rules):
                result = _fertilizer_service_target_result()
                output = result.model_dump(mode="json")
                output["case_id"] = audit_case.case_id
                output["evidence_error_type"] = "service_target_risk"

                return result, [result.reason], output, result.confidence

            result = self._company_mismatch_result(evidence)
            output = result.model_dump(mode="json")
            output["case_id"] = audit_case.case_id
            output["evidence_error_type"] = "company_mismatch"

            return result, [result.reason], output, result.confidence

        if _has_explicit_abnormal_granularity(candidate_rules):
            result = self._abnormal_granularity_result(audit_case.case_id, candidate_rules)
            output = result.model_dump(mode="json")
            output["case_id"] = audit_case.case_id
            output["entered_subcategory_granularity"] = candidate_rules.entered_subcategory_granularity
            output["granularity_reason"] = candidate_rules.granularity_reason

            return result, [result.reason], output, result.confidence

        try:
            result = self.provider.classify(
                audit_case=audit_case,
                evidence=evidence,
                candidate_rules=candidate_rules,
            )
        except LLMProviderAuthError:
            raise
        except Exception as error:
            result = _semantic_result_from_deterministic_fallback(
                audit_case=audit_case,
                evidence=evidence,
                candidate_rules=candidate_rules,
                error=error,
            )
        result = _ensure_all_level2_categories_supported(result, candidate_rules)
        result = _downgrade_fertilizer_service_target_result(result, evidence, candidate_rules)
        findings = [result.reason]
        output = result.model_dump(mode="json")
        output["case_id"] = audit_case.case_id

        return result, findings, output, result.confidence

    def _insufficient_evidence_result(self, evidence: EvidencePackage):
        """证据不足时直接生成语义结果，避免让 LLM 基于企业名或关键词猜测。"""
        from app.agents.llm_classification_provider import SemanticClassificationResult

        return SemanticClassificationResult(
            result="insufficient_evidence",
            confidence=80,
            matched_level1="",
            matched_level2="",
            matched_level3="",
            evidence_quotes=[],
            reason=build_insufficient_evidence_reason(evidence),
            suggestion="请补充企业官网、有效业务介绍或可验证的外部证据后再审批。",
        )

    def _company_mismatch_result(self, evidence: EvidencePackage):
        """官网内容明显属于其他企业时，按证据不足处理。"""
        from app.agents.llm_classification_provider import SemanticClassificationResult

        return SemanticClassificationResult(
            result="insufficient_evidence",
            confidence=80,
            matched_level1="",
            matched_level2="",
            matched_level3="",
            evidence_quotes=[],
            reason=f"官网证据与目标企业不一致：{_extract_other_company_names(evidence)}",
            suggestion="请核对员工录入官网是否属于目标企业，或补充正确官网后再审批。",
        )

    def _fallback_result(self, case_id: str):
        """LLM 或分类 provider 异常时的兜底结果。"""
        from app.agents.llm_classification_provider import SemanticClassificationResult

        return SemanticClassificationResult(
            result="uncertain",
            confidence=0,
            matched_level1="",
            matched_level2="",
            matched_level3="",
            evidence_quotes=[],
            reason="Classification Agent 执行失败，默认转入人工复核。",
            suggestion="请人工审核该记录。",
        )

    def _abnormal_granularity_result(self, case_id: str, candidate_rules: CandidateRuleSet):
        """细分粒度异常时不调用 LLM，直接转人工复核。"""
        from app.agents.llm_classification_provider import SemanticClassificationResult

        return SemanticClassificationResult(
            result="uncertain",
            confidence=85,
            matched_level1="",
            matched_level2="",
            matched_level3="",
            evidence_quotes=[],
            reason=_granularity_review_reason(candidate_rules),
            suggestion="请人工确认员工录入的细分分类粒度后再审批。",
        )


def build_insufficient_evidence_reason(evidence: EvidencePackage) -> str:
    """根据证据包生成可解释的证据不足原因。"""
    if evidence.errors:
        return f"外部证据不足：{'；'.join(evidence.errors)}"

    if not evidence.business_scope.strip():
        return "外部证据不足：未采集到有效业务描述。"

    if not evidence.snippets:
        return "外部证据不足：未抽取到有效业务片段。"

    return f"外部证据不足：证据质量分为 {evidence.quality_score}，低于自动审批阈值。"


def classify_evidence_insufficient_type(evidence: EvidencePackage) -> str:
    """把证据不足细分成可统计类型。"""
    if evidence.errors:
        return "evidence_unavailable"

    if not evidence.business_scope.strip() or not evidence.snippets:
        return "evidence_content_insufficient"

    return "evidence_low_quality"


def _semantic_result_from_deterministic_fallback(
    audit_case: AuditCase,
    evidence: EvidencePackage,
    candidate_rules: CandidateRuleSet,
    error: Exception,
):
    """LLM 调用失败时，用本地确定性规则生成语义结果，降低偶发超时影响。"""
    from app.agents.llm_classification_provider import SemanticClassificationResult

    decision = classify_audit_case(
        audit_case=audit_case,
        evidence=evidence,
        candidate_rules=candidate_rules,
    )
    matched_rule = _find_entered_rule(audit_case, candidate_rules) or (
        candidate_rules.candidates[0] if candidate_rules.candidates else None
    )
    fallback_note = f"LLM 调用失败，已使用确定性规则兜底：{error}。"

    if decision.action == DecisionAction.APPROVED:
        result = "supports_entered_category"
    elif decision.action == DecisionAction.REJECTED:
        result = "conflicts_with_entered_category"
    elif decision.action == DecisionAction.NEEDS_MORE_EVIDENCE:
        result = "insufficient_evidence"
    else:
        result = "uncertain"

    return SemanticClassificationResult(
        result=result,
        confidence=min(decision.confidence, 80),
        matched_level1=matched_rule.level1 if matched_rule else "",
        matched_level2=matched_rule.level2 if matched_rule else "",
        matched_level3=matched_rule.level3 if matched_rule else "",
        matched_category_candidate_ids=_all_category_candidate_ids(candidate_rules)
        if decision.action == DecisionAction.APPROVED
        else [],
        evidence_quotes=[],
        reason=f"{decision.reason} {fallback_note}",
        suggestion=decision.suggestion,
        normalization_warning=fallback_note,
    )


def classify_audit_case(
    audit_case: AuditCase,
    evidence: EvidencePackage,
    candidate_rules: CandidateRuleSet,
) -> ApprovalDecision:
    """根据审批单、证据包和候选规则，生成审批结论。"""
    if not has_sufficient_evidence(evidence):
        return ApprovalDecision(
            case_id=audit_case.case_id,
            action=DecisionAction.NEEDS_MORE_EVIDENCE,
            status=DecisionStatus.PENDING_REVIEW,
            confidence=80,
            risk_score=70,
            reason="外部证据不足，无法判断员工录入分类是否合理。",
            suggestion="请补充企业官网或有效业务介绍。",
            needs_review=True,
        )

    if _has_explicit_abnormal_granularity(candidate_rules):
        return ApprovalDecision(
            case_id=audit_case.case_id,
            action=DecisionAction.NEEDS_HUMAN_REVIEW,
            status=DecisionStatus.PENDING_REVIEW,
            confidence=85,
            risk_score=80,
            reason=_granularity_review_reason(candidate_rules),
            suggestion="请人工确认员工录入的细分分类粒度后再审批。",
            needs_review=True,
        )

    if not candidate_rules.entered_path_exists:
        return ApprovalDecision(
            case_id=audit_case.case_id,
            action=DecisionAction.NEEDS_HUMAN_REVIEW,
            status=DecisionStatus.PENDING_REVIEW,
            confidence=85,
            risk_score=80,
            reason="员工录入分类不在内部规则库中，需要人工确认分类口径。",
            suggestion="请审核员确认该分类是否应加入规则库，或调整为已有分类。",
            needs_review=True,
        )

    if _has_mixed_business_evidence(evidence):
        return ApprovalDecision(
            case_id=audit_case.case_id,
            action=DecisionAction.NEEDS_HUMAN_REVIEW,
            status=DecisionStatus.PENDING_REVIEW,
            confidence=70,
            risk_score=65,
            reason="证据可能同时支持多个业务方向，需要人工确认主营业务。",
            suggestion="请人工确认企业主营业务后再做最终分类。",
            needs_review=True,
        )

    if _has_explicit_granularity(candidate_rules):
        return _classify_by_category_granularity(audit_case, evidence, candidate_rules)

    entered_rule = _find_entered_rule(audit_case, candidate_rules)

    if entered_rule and _evidence_supports_rule(evidence, entered_rule):
        return ApprovalDecision(
            case_id=audit_case.case_id,
            action=DecisionAction.APPROVED,
            status=DecisionStatus.COMPLETED,
            confidence=90,
            risk_score=10,
            reason="外部证据支持员工录入分类，可以自动通过。",
            suggestion="",
            needs_review=False,
        )

    suggested_rule = candidate_rules.candidates[0] if candidate_rules.candidates else None
    suggestion = _build_suggestion(suggested_rule)

    return ApprovalDecision(
        case_id=audit_case.case_id,
        action=DecisionAction.REJECTED,
        status=DecisionStatus.COMPLETED,
        confidence=88,
        risk_score=45,
        reason="外部证据不支持员工录入分类，建议驳回并修正分类。",
        suggestion=suggestion,
        needs_review=False,
    )


def _classify_by_category_granularity(
    audit_case: AuditCase,
    evidence: EvidencePackage,
    candidate_rules: CandidateRuleSet,
) -> ApprovalDecision:
    """根据细分粒度分别判断，避免二级证据误通过三级分类。"""
    entered_candidate = _find_entered_category_candidate(candidate_rules)

    if candidate_rules.entered_subcategory_granularity == "level2":
        level2_candidates = _entered_category_candidates(candidate_rules, "level2")
        unsupported_candidates = [
            candidate
            for candidate in level2_candidates
            if not _evidence_supports_category_candidate(evidence, candidate)
        ]

        if level2_candidates and not unsupported_candidates:
            return ApprovalDecision(
                case_id=audit_case.case_id,
                action=DecisionAction.APPROVED,
                status=DecisionStatus.COMPLETED,
                confidence=90,
                risk_score=10,
                reason="员工录入为二级分类，外部证据支持该二级分类，可以自动通过。",
                suggestion="",
                needs_review=False,
            )

        if len(level2_candidates) > 1 and unsupported_candidates:
            unsupported_values = ", ".join(candidate.matched_entered_value for candidate in unsupported_candidates)
            return ApprovalDecision(
                case_id=audit_case.case_id,
                action=DecisionAction.NEEDS_HUMAN_REVIEW,
                status=DecisionStatus.PENDING_REVIEW,
                confidence=82,
                risk_score=65,
                reason=f"员工录入了多个二级分类，但外部证据未覆盖全部细分分类：{unsupported_values}。",
                suggestion="请人工确认未被证据覆盖的员工录入分类是否需要保留或修正。",
                needs_review=True,
            )

        return ApprovalDecision(
            case_id=audit_case.case_id,
            action=DecisionAction.REJECTED,
            status=DecisionStatus.COMPLETED,
            confidence=88,
            risk_score=45,
            reason="外部证据不支持员工录入的二级分类，建议驳回并修正分类。",
            suggestion=_build_category_candidate_suggestion(entered_candidate) or _build_suggestion(
                candidate_rules.candidates[0] if candidate_rules.candidates else None
            ),
            needs_review=False,
        )

    if candidate_rules.entered_subcategory_granularity == "level3":
        if entered_candidate and _evidence_supports_strict_level3_candidate(evidence, entered_candidate):
            return ApprovalDecision(
                case_id=audit_case.case_id,
                action=DecisionAction.APPROVED,
                status=DecisionStatus.COMPLETED,
                confidence=90,
                risk_score=10,
                reason="员工录入为三级分类，外部证据支持该三级分类，可以自动通过。",
                suggestion="",
                needs_review=False,
            )

        suggested_rule = candidate_rules.candidates[0] if candidate_rules.candidates else None
        return ApprovalDecision(
            case_id=audit_case.case_id,
            action=DecisionAction.REJECTED,
            status=DecisionStatus.COMPLETED,
            confidence=88,
            risk_score=45,
            reason="员工录入为三级分类，但外部证据未支持该具体三级分类，建议驳回并修正分类。",
            suggestion=_build_suggestion(suggested_rule),
            needs_review=False,
        )

    return ApprovalDecision(
        case_id=audit_case.case_id,
        action=DecisionAction.NEEDS_HUMAN_REVIEW,
        status=DecisionStatus.PENDING_REVIEW,
        confidence=85,
        risk_score=80,
        reason=_granularity_review_reason(candidate_rules),
        suggestion="请人工确认员工录入的细分分类粒度后再审批。",
        needs_review=True,
    )


def build_classification_assessment(decision: ApprovalDecision) -> AgentAssessment:
    """把审批结论包装成统一 AgentAssessment，方便后续 trace。"""
    return AgentAssessment(
        agent_name="classification_agent",
        status="success",
        confidence=decision.confidence,
        findings=[decision.reason],
        output=decision.model_dump(mode="json"),
        duration_ms=0,
    )


def _has_explicit_granularity(candidate_rules: CandidateRuleSet) -> bool:
    """判断粒度字段是否来自新召回流程；兼容旧测试手工构造的 CandidateRuleSet。"""
    return bool(
        candidate_rules.category_candidates
        or candidate_rules.granularity_reason
        or candidate_rules.unmatched_values
        or candidate_rules.ambiguous_values
    )


def _has_explicit_abnormal_granularity(candidate_rules: CandidateRuleSet) -> bool:
    """mixed、ambiguous、unknown 这类异常粒度不能进入自动审批。"""
    if not _has_explicit_granularity(candidate_rules):
        return False

    return candidate_rules.entered_subcategory_granularity in {"mixed", "ambiguous", "unknown"}


def _ensure_all_level2_categories_supported(result, candidate_rules: CandidateRuleSet):
    """多个二级候选时，LLM 必须明确支持全部候选才允许保持 supports 结果。"""
    if result.result != "supports_entered_category":
        return result

    if candidate_rules.entered_subcategory_granularity != "level2":
        return result

    level2_candidates = _entered_category_candidates(candidate_rules, "level2")
    if len(level2_candidates) <= 1:
        return result

    expected_ids = {f"category_{index + 1}" for index, _ in enumerate(candidate_rules.category_candidates)}
    matched_ids = set(result.matched_category_candidate_ids)
    unsupported_values = list(result.unsupported_entered_values)

    for index, candidate in enumerate(candidate_rules.category_candidates):
        candidate_id = f"category_{index + 1}"
        if candidate.granularity != "level2" or candidate_id in matched_ids:
            continue
        unsupported_values.append(candidate.matched_entered_value)

    if expected_ids <= matched_ids and not result.unsupported_entered_values:
        return result

    unique_unsupported_values = list(dict.fromkeys(value for value in unsupported_values if value))
    warning = "LLM 未确认全部二级细分分类均被证据支持，已降级为 uncertain。"
    return result.model_copy(
        update={
            "result": "uncertain",
            "confidence": min(result.confidence, 60),
            "unsupported_entered_values": unique_unsupported_values,
            "reason": f"{result.reason} {warning} 未覆盖：{', '.join(unique_unsupported_values)}。",
            "suggestion": result.suggestion or "请人工确认未被证据覆盖的员工录入分类。",
            "normalization_warning": warning,
        }
    )


def _all_category_candidate_ids(candidate_rules: CandidateRuleSet) -> list[str]:
    """返回全部分类候选 ID，用于确定性通过时补齐多二级分类命中结果。"""
    return [
        f"category_{index + 1}"
        for index, _ in enumerate(candidate_rules.category_candidates)
    ]


def _is_target_company_mismatch(audit_case: AuditCase, evidence: EvidencePackage) -> bool:
    """判断采集到的官网内容是否明显属于另一家公司。"""
    target_company = audit_case.company_name.strip()
    if not target_company:
        return False

    evidence_text = _combined_evidence_text(evidence)
    if target_company in evidence_text:
        return False

    return bool(_other_company_names(target_company, evidence_text))


def _extract_other_company_names(evidence: EvidencePackage) -> str:
    """从证据文本中提取疑似其他企业名称，用于审批原因展示。"""
    company_names = COMPANY_NAME_PATTERN.findall(_combined_evidence_text(evidence))
    unique_names = list(dict.fromkeys(company_names))
    return "、".join(unique_names[:3]) or "证据文本未出现目标企业名称"


def _other_company_names(target_company: str, evidence_text: str) -> list[str]:
    """找出证据文本中不是目标企业的公司名。"""
    company_names = COMPANY_NAME_PATTERN.findall(evidence_text)
    return [
        company_name
        for company_name in dict.fromkeys(company_names)
        if company_name != target_company and target_company not in company_name
    ]


def _downgrade_fertilizer_service_target_result(
    result,
    evidence: EvidencePackage,
    candidate_rules: CandidateRuleSet,
):
    """肥料/农资企业的服务对象不能直接当作企业主营作物分类。"""
    if result.result != "supports_entered_category":
        return result

    if not _has_fertilizer_service_target_risk(evidence, candidate_rules):
        return result

    uncertain_result = _fertilizer_service_target_result()
    return result.model_copy(
        update={
            "result": uncertain_result.result,
            "confidence": min(result.confidence, uncertain_result.confidence),
            "reason": f"{result.reason} {uncertain_result.reason}",
            "suggestion": uncertain_result.suggestion,
            "normalization_warning": uncertain_result.normalization_warning,
        }
    )


def _fertilizer_service_target_result():
    """生成肥料/农资服务对象风险的语义结果。"""
    from app.agents.llm_classification_provider import SemanticClassificationResult

    warning = "官网证据显示企业主营更像肥料/农资产品，果树、蔬菜等只是产品服务对象。"
    return SemanticClassificationResult(
        result="uncertain",
        confidence=65,
        matched_level1="",
        matched_level2="",
        matched_level3="",
        evidence_quotes=[],
        reason=f"{warning} 不能直接等同于企业主营作物分类，需要人工确认。",
        suggestion="请人工确认企业主营业务是否为作物种植，或改为最终分类表中的肥料/农资相关分类。",
        normalization_warning=warning,
    )


def _has_fertilizer_service_target_risk(
    evidence: EvidencePackage,
    candidate_rules: CandidateRuleSet,
) -> bool:
    """识别“肥料适用于某作物”被误判成“企业主营某作物”的风险。"""
    if candidate_rules.entered_subcategory_granularity != "level2":
        return False

    crop_candidates = [
        candidate
        for candidate in _entered_category_candidates(candidate_rules, "level2")
        if candidate.level1 == "种植业" and candidate.level2 in CROP_LEVEL2_CATEGORIES
    ]
    if not crop_candidates:
        return False

    evidence_text = _combined_evidence_text(evidence)
    has_fertilizer_provider = any(keyword in evidence_text for keyword in FERTILIZER_PROVIDER_KEYWORDS)
    has_service_target = any(keyword in evidence_text for keyword in SERVICE_TARGET_KEYWORDS)
    has_strong_planting = _has_strong_planting_evidence(evidence_text)

    return has_fertilizer_provider and has_service_target and not has_strong_planting


def _has_strong_planting_evidence(evidence_text: str) -> bool:
    """判断证据是否明确描述企业自己从事种植，而不是仅描述产品适用作物。"""
    if any(keyword in evidence_text for keyword in STRONG_PLANTING_KEYWORDS):
        return True

    return bool(re.search(r"(从事|开展|主营|专业)[^。；，,.]{0,30}种植", evidence_text))


def _combined_evidence_text(evidence: EvidencePackage) -> str:
    """合并业务描述和片段文本，方便做轻量确定性判断。"""
    return " ".join(
        [
            evidence.business_scope,
            *[snippet.text for snippet in evidence.snippets],
        ]
    )


def _granularity_review_reason(candidate_rules: CandidateRuleSet) -> str:
    """生成细分粒度异常的人工复核原因。"""
    if candidate_rules.granularity_reason:
        return candidate_rules.granularity_reason

    if candidate_rules.entered_subcategory_granularity == "mixed":
        return "员工录入细分混合了二级和三级分类，需要人工确认录入口径。"

    if candidate_rules.entered_subcategory_granularity == "ambiguous":
        return "员工录入细分存在多个可能分类路径，需要人工确认正确分类。"

    return "员工录入细分不在当前规则库中，需要人工确认分类口径。"


def _find_entered_category_candidate(candidate_rules: CandidateRuleSet):
    """从新候选模型中找到员工录入粒度对应的第一个候选。"""
    target_granularity = candidate_rules.entered_subcategory_granularity
    for candidate in candidate_rules.category_candidates:
        if candidate.granularity == target_granularity:
            return candidate

    return None


def _entered_category_candidates(candidate_rules: CandidateRuleSet, granularity: str):
    """返回指定粒度下的全部员工录入候选。"""
    return [
        candidate
        for candidate in candidate_rules.category_candidates
        if candidate.granularity == granularity
    ]


def _evidence_supports_category_candidate(evidence: EvidencePackage, candidate) -> bool:
    """判断证据是否支持二级候选，允许使用二级名和聚合关键词。"""
    return _evidence_contains_any_keyword(
        evidence=evidence,
        keywords=[
            candidate.level1,
            candidate.level2,
            *candidate.keywords,
        ],
    )


def _evidence_supports_strict_level3_candidate(evidence: EvidencePackage, candidate) -> bool:
    """判断证据是否支持三级候选；三级录入不能只靠二级分类名通过。"""
    excluded_keywords = {candidate.level1, candidate.level2}
    strict_keywords = [
        candidate.level3,
        *[keyword for keyword in candidate.keywords if keyword not in excluded_keywords],
    ]

    return _evidence_contains_any_keyword(evidence=evidence, keywords=strict_keywords)


def _evidence_contains_any_keyword(evidence: EvidencePackage, keywords: list[str]) -> bool:
    """用关键词判断证据是否支持候选分类，并过滤容易误伤的泛词。"""
    evidence_text = " ".join(
        [
            evidence.business_scope,
            *[snippet.text for snippet in evidence.snippets],
        ]
    ).lower()
    seen_keywords = set()

    for keyword in keywords:
        normalized_keyword = keyword.strip()
        if not normalized_keyword or normalized_keyword in GENERIC_EVIDENCE_KEYWORDS:
            continue
        if normalized_keyword in seen_keywords:
            continue

        seen_keywords.add(normalized_keyword)
        if normalized_keyword.lower() in evidence_text:
            return True

    return False


def _build_category_candidate_suggestion(candidate) -> str:
    """把新候选模型转成分类建议路径。"""
    if candidate is None:
        return ""

    return " / ".join(part for part in [candidate.level1, candidate.level2, candidate.level3] if part)


#用来判断即使证据支持员工分类，是否仍然因为业务方向太多而需要人工确认
def _has_mixed_business_evidence(evidence: EvidencePackage) -> bool:
    """判断证据是否明确覆盖多个强业务方向。"""
    evidence_text = " ".join(
        [
            evidence.business_scope,
            *[snippet.text for snippet in evidence.snippets],
        ]
    )

    business_groups = {
        "software": ["软件开发", "软件平台", "数据中台", "工业互联网", "数字孪生"],
        "planting": ["农作物种植", "粮食作物种植", "玉米", "水稻", "种植基地"],
        "exhibition": ["行业展会", "会展活动", "会议论坛", "活动组织", "展台设计"],
        "park_operation": ["产业园运营", "园区运营"],
        "medical_device": ["医用检测设备", "康复设备", "医疗器械"],
        "fertilizer": ["复合肥", "有机肥", "水溶肥", "肥料产品"],
    }

    matched_groups = []

    for group_name, keywords in business_groups.items():
        if any(keyword in evidence_text for keyword in keywords):
            matched_groups.append(group_name)

    return len(matched_groups) >= 2


def _find_entered_rule(
    audit_case: AuditCase,
    candidate_rules: CandidateRuleSet,
):
    """在候选规则里找到员工录入分类对应的规则。"""
    for rule in candidate_rules.candidates:
        if _entered_path_matches_rule(audit_case, rule):
            return rule

    return None


def _entered_path_matches_rule(audit_case: AuditCase, rule) -> bool:
    """判断员工录入路径是否命中规则，兼容“细分”录入二级或三级。"""
    if audit_case.entered_level1 != rule.level1:
        return False

    entered_level2 = audit_case.entered_level2.strip()
    entered_subcategories = _split_entered_subcategories(audit_case.entered_subcategory)
    rule_categories = {rule.level2, rule.level3}

    if entered_level2:
        return entered_level2 == rule.level2 and any(value in rule_categories for value in entered_subcategories)

    return any(value in rule_categories for value in entered_subcategories)


def _split_entered_subcategories(value: str) -> list[str]:
    """拆分员工录入的细分字段，兼容一个单元格填写多个细分。"""
    return split_entered_subcategories(value)


def _evidence_supports_rule(evidence: EvidencePackage, rule) -> bool:
    """用业务关键词判断证据是否支持某条规则，过滤生态类泛词。"""
    evidence_text = " ".join(
        [
            evidence.business_scope,
            *[snippet.text for snippet in evidence.snippets],
        ]
    ).lower()

    for keyword in _business_support_keywords(rule):
        if keyword.lower() in evidence_text:
            return True

    return False


def _business_support_keywords(rule) -> list[str]:
    """生成可用于证据支持判断的业务关键词，避免生态泛词造成误判。"""
    keywords = [
        rule.level1,
        rule.level2,
        rule.level3,
        *rule.keywords,
        *_business_synonyms(rule),
    ]
    useful_keywords = []
    seen_keywords = set()

    for keyword in keywords:
        normalized_keyword = keyword.strip()
        if not normalized_keyword or normalized_keyword in GENERIC_EVIDENCE_KEYWORDS:
            continue
        if normalized_keyword in seen_keywords:
            continue

        useful_keywords.append(normalized_keyword)
        seen_keywords.add(normalized_keyword)

    return useful_keywords


def _business_synonyms(rule) -> list[str]:
    """为常见业务分类补充同义证据词，弥补规则名称和官网表述差异。"""
    if rule.level3 == "医疗设备":
        return ["医用检测设备", "康复设备", "医疗器械", "器械配套系统"]

    if rule.level1 == "会展服务" or "会展" in rule.level3:
        return ["行业展会", "会展活动", "会议论坛", "展台设计", "会务服务"]

    if rule.level3 == "肥料制造":
        return ["复合肥", "有机肥", "水溶肥", "肥料产品"]

    return []


def _build_suggestion(rule) -> str:
    """根据最相关的候选规则生成建议分类。"""
    if rule is None:
        return ""

    return f"{rule.level1} / {rule.level2} / {rule.level3}"
