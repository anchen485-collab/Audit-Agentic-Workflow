import json
from time import perf_counter
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

from app.agents.classification_agent import classify_audit_case
from app.domain.decisions import DecisionAction
from app.domain.errors import LLMInvalidCandidateError, LLMInvalidJsonError, LLMOutputError, LLMProviderAuthError
from app.domain.models import AuditCase, CandidateRuleSet, CategoryRule, EvidencePackage
from app.observability.logging import get_audit_logger

logger = get_audit_logger("agents.llm_classification_provider")


class SemanticClassificationResult(BaseModel):
    """LLM 只输出语义判断，不输出最终审批动作。"""

    result: str = Field(
        description="语义判断结果：supports_entered_category/conflicts_with_entered_category/insufficient_evidence/uncertain",
    )
    confidence: int = Field(ge=0, le=100, description="判断置信度")
    matched_candidate_rule_id: str = Field(default="", description="证据匹配到的候选规则 ID，例如 rule_1")
    matched_level1: str = Field(default="", description="证据匹配到的候选规则一级分类")
    matched_level2: str = Field(default="", description="证据匹配到的候选规则二级分类")
    matched_level3: str = Field(default="", description="证据匹配到的候选规则三级分类")
    matched_category_candidate_ids: list[str] = Field(default_factory=list, description="证据支持的分类候选 ID 列表")
    unsupported_entered_values: list[str] = Field(default_factory=list, description="证据未覆盖的员工录入细分值")
    evidence_quotes: list[str] = Field(default_factory=list, description="支撑判断的证据片段")
    reason: str = Field(description="判断原因")
    suggestion: str = Field(default="", description="建议修正分类或补充信息")
    normalization_warning: str = Field(default="", description="系统对 LLM 输出做降级或修正时的说明")

    def matched_path(self) -> tuple[str, str, str]:
        """返回 LLM 选择的分类路径，方便做候选规则合法性校验。"""
        return (
            self.matched_level1.strip(),
            self.matched_level2.strip(),
            self.matched_level3.strip(),
        )


class ClassificationProvider(Protocol):
    """审批判断 provider 协议。"""

    def classify(
            self,
            audit_case: AuditCase,
            evidence: EvidencePackage,
            candidate_rules: CandidateRuleSet,
    ) -> SemanticClassificationResult:
        """判断一条审批单。"""


class MockClassificationProvider:
    """mock 审批判断 provider，用确定性规则模拟 LLM。"""

    def classify(
            self,
            audit_case: AuditCase,
            evidence: EvidencePackage,
            candidate_rules: CandidateRuleSet,
    ) -> SemanticClassificationResult:
        decision = classify_audit_case(
            audit_case=audit_case,
            evidence=evidence,
            candidate_rules=candidate_rules,
        )

        return _semantic_result_from_decision(decision.action, decision.confidence, decision.reason, candidate_rules)


def _semantic_result_from_decision(
    action: DecisionAction,
    confidence: int,
    reason: str,
    candidate_rules: CandidateRuleSet,
) -> SemanticClassificationResult:
    """把 mock 确定性审批结论转换成语义判断结果。"""
    matched_rule = candidate_rules.candidates[0] if candidate_rules.candidates else None

    if action == DecisionAction.APPROVED:
        result = "supports_entered_category"
        matched_rule = _find_entered_candidate(candidate_rules) or matched_rule
    elif action == DecisionAction.REJECTED:
        result = "conflicts_with_entered_category"
    elif action == DecisionAction.NEEDS_MORE_EVIDENCE:
        result = "insufficient_evidence"
    else:
        result = "uncertain"

    return SemanticClassificationResult(
        result=result,
        confidence=confidence,
        matched_candidate_rule_id=_find_candidate_rule_id(candidate_rules, matched_rule),
        matched_category_candidate_ids=_supported_category_candidate_ids(action, candidate_rules),
        matched_level1=matched_rule.level1 if matched_rule else "",
        matched_level2=matched_rule.level2 if matched_rule else "",
        matched_level3=matched_rule.level3 if matched_rule else "",
        evidence_quotes=[],
        reason=reason,
        suggestion=_format_rule_path(matched_rule) if action == DecisionAction.REJECTED else "",
    )


def _supported_category_candidate_ids(action: DecisionAction, candidate_rules: CandidateRuleSet) -> list[str]:
    """mock provider 已经由确定性规则判断通过时，回填全部被支持的分类候选 ID。"""
    if action != DecisionAction.APPROVED:
        return []

    return [
        candidate_id
        for candidate_id, _ in _category_candidate_items(candidate_rules)
    ]


def _find_entered_candidate(candidate_rules: CandidateRuleSet) -> CategoryRule | None:
    """候选规则存在且录入路径有效时，优先返回第一条候选。"""
    if not candidate_rules.entered_path_exists:
        return None

    return candidate_rules.candidates[0] if candidate_rules.candidates else None


def _format_rule_path(rule: CategoryRule | None) -> str:
    """生成完整分类路径，确保处理建议来自最终分类表。"""
    if rule is None:
        return ""

    return f"{rule.level1} / {rule.level2} / {rule.level3}"


class OpenAICompatibleClassificationProvider:
    """OpenAI-compatible 审批判断 provider。"""

    def __init__(
            self,
            api_key: str,
            base_url: str,
            model: str,
            timeout_seconds: float = 30,
            max_retries: int = 2,
            http_post=httpx.post,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        self.http_post = http_post

    def classify(
            self,
            audit_case: AuditCase,
            evidence: EvidencePackage,
            candidate_rules: CandidateRuleSet,
    ) -> SemanticClassificationResult:
        prompt = _build_classification_prompt(
            audit_case=audit_case,
            evidence=evidence,
            candidate_rules=candidate_rules,
        )
        logger.info(
            "开始调用 LLM 审批判断: case_id=%s company=%s model=%s candidate_count=%s evidence_quality=%s",
            audit_case.case_id,
            audit_case.company_name,
            self.model,
            len(candidate_rules.candidates),
            evidence.quality_score,
        )

        start_time = perf_counter()
        try:
            raw_text = self._call_llm(prompt)
        except Exception:
            logger.exception(
                "LLM Agent 分析失败: case_id=%s company=%s duration_ms=%.3f",
                audit_case.case_id,
                audit_case.company_name,
                _elapsed_ms(start_time),
            )
            raise

        try:
            raw_data = json.loads(raw_text)
            result = SemanticClassificationResult.model_validate(raw_data)
            result = _normalize_candidate_rule_result(result, candidate_rules)
            _validate_candidate_rule(result, candidate_rules)
            result = _hydrate_matched_rule_path(result, candidate_rules)
            logger.info(
                "LLM Agent 分析完成: case_id=%s result=%s confidence=%s duration_ms=%.3f",
                audit_case.case_id,
                result.result,
                result.confidence,
                _elapsed_ms(start_time),
            )
            return result
        except json.JSONDecodeError as error:
            logger.warning(
                "LLM 输出解析失败: case_id=%s raw_text=%s",
                audit_case.case_id,
                raw_text[:500],
            )
            raise LLMInvalidJsonError(f"LLM 输出无法解析为审批 JSON：{raw_text[:500]}") from error
        except ValueError as error:
            logger.warning(
                "LLM 输出校验失败: case_id=%s reason=%s",
                audit_case.case_id,
                error,
            )
            raise

    def _call_llm(self, prompt: str) -> str:
        """调用 OpenAI-compatible chat completions 接口。"""
        for attempt in range(self.max_retries + 1):
            try:
                response = self.http_post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "你是企业录入审批助手，只能输出合法 JSON，不要输出 Markdown。",
                            },
                            {
                                "role": "user",
                                "content": prompt,
                            },
                        ],
                        "temperature": 0,
                    },
                    timeout=self.timeout_seconds,
                )
                break
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                if attempt >= self.max_retries:
                    raise

                logger.warning(
                    "LLM 请求失败，准备重试: model=%s attempt=%s max_retries=%s reason=%s",
                    self.model,
                    attempt + 1,
                    self.max_retries,
                    error,
                )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            hint = _build_http_error_hint(error.response.status_code)
            logger.warning(
                "LLM 接口返回错误: model=%s base_url=%s status_code=%s hint=%s",
                self.model,
                self.base_url,
                error.response.status_code,
                hint,
            )
            if error.response.status_code in {401, 403}:
                raise LLMProviderAuthError(hint) from error
            raise LLMOutputError(hint) from error

        data = response.json()
        return data["choices"][0]["message"]["content"]

    def health_check(self) -> dict[str, str | bool]:
        """执行轻量 LLM 连通性检查，不返回 API Key。"""
        try:
            self._call_llm("请只返回合法 JSON：{\"ok\": true}")
        except LLMProviderAuthError as error:
            return {
                "ok": False,
                "error_type": error.error_code,
                "message": str(error),
            }
        except httpx.HTTPStatusError as error:
            return {
                "ok": False,
                "error_type": f"http_{error.response.status_code}",
                "message": _build_http_error_hint(error.response.status_code),
            }
        except httpx.HTTPError:
            return {
                "ok": False,
                "error_type": "llm_network_error",
                "message": "无法连接 LLM 服务，请检查网络、LLM_BASE_URL 或服务商状态。",
            }
        except LLMOutputError as error:
            return {
                "ok": False,
                "error_type": error.error_code,
                "message": str(error),
            }
        except Exception as error:
            return {
                "ok": False,
                "error_type": error.__class__.__name__,
                "message": str(error),
            }

        return {
            "ok": True,
            "error_type": "",
            "message": "LLM 服务连接正常。",
        }


def _build_http_error_hint(status_code: int) -> str:
    """根据 HTTP 状态码生成排查提示。"""
    if status_code == 401:
        return "认证失败，请检查 LLM_API_KEY 是否属于当前 LLM_BASE_URL 对应的平台。"

    if status_code == 403:
        return "权限不足，请检查模型权限、账户状态或 API Key 权限。"

    if status_code == 429:
        return "请求过多或额度不足，请检查限流、余额和调用频率。"

    return "请检查 LLM_BASE_URL、模型名称、网络连接和服务商返回信息。"


def _elapsed_ms(start_time: float) -> float:
    """计算从 start_time 到当前时间的毫秒耗时。"""
    return round((perf_counter() - start_time) * 1000, 3)


def _validate_candidate_rule(result: SemanticClassificationResult, candidate_rules: CandidateRuleSet) -> None:
    """校验 LLM 返回的分类必须来自候选规则，避免编造最终分类表之外的建议。"""
    if result.matched_category_candidate_ids:
        category_candidate_ids = _category_candidate_ids(candidate_rules)
        invalid_ids = [
            candidate_id
            for candidate_id in result.matched_category_candidate_ids
            if candidate_id not in category_candidate_ids
        ]
        if invalid_ids:
            raise LLMInvalidCandidateError(f"LLM 返回了不存在的分类候选 ID：{', '.join(invalid_ids)}")

    if result.matched_candidate_rule_id:
        candidate_rule_ids = _candidate_rule_ids(candidate_rules)
        if result.matched_candidate_rule_id not in candidate_rule_ids:
            raise LLMInvalidCandidateError(f"LLM 返回了不存在的候选规则 ID：{result.matched_candidate_rule_id}")
        return

    matched_path = result.matched_path()
    if not any(matched_path):
        return

    candidate_paths = {
        (rule.level1, rule.level2, rule.level3)
        for rule in candidate_rules.candidates
    }
    category_candidate_paths = _category_candidate_paths(candidate_rules)
    if matched_path not in candidate_paths and matched_path not in category_candidate_paths:
        raise LLMInvalidCandidateError(f"LLM 返回了候选规则之外的分类：{' / '.join(matched_path)}")


def _normalize_candidate_rule_result(
    result: SemanticClassificationResult,
    candidate_rules: CandidateRuleSet,
) -> SemanticClassificationResult:
    """对可理解但不完整的 LLM 输出做温和降级，减少 Agent failed。"""
    if candidate_rules.entered_subcategory_granularity in {"mixed", "ambiguous", "unknown"}:
        return _downgrade_to_uncertain(result, "员工录入细分粒度异常，已降级为 uncertain。")

    matched_path = result.matched_path()
    has_partial_path = any(matched_path) and not all(matched_path)

    if result.matched_candidate_rule_id or not has_partial_path:
        return result

    if _is_valid_level2_partial_path(result, candidate_rules):
        return result

    return _downgrade_to_uncertain(result, "LLM 未返回完整候选规则，已降级为 uncertain。")


def _downgrade_to_uncertain(result: SemanticClassificationResult, warning: str) -> SemanticClassificationResult:
    """把不可靠的 LLM 输出降级为 uncertain，并保留原始原因。"""
    return result.model_copy(
        update={
            "result": "uncertain",
            "confidence": min(result.confidence, 50),
            "matched_level1": "",
            "matched_level2": "",
            "matched_level3": "",
            "reason": f"{result.reason} {warning}",
            "suggestion": result.suggestion or "请人工确认企业主营业务和分类口径。",
            "normalization_warning": warning,
        }
    )


def _is_valid_level2_partial_path(
    result: SemanticClassificationResult,
    candidate_rules: CandidateRuleSet,
) -> bool:
    """level2 粒度下，level1 + level2 + 空 level3 是合法分类候选。"""
    if candidate_rules.entered_subcategory_granularity != "level2":
        return False

    matched_level1, matched_level2, matched_level3 = result.matched_path()
    if not matched_level1 or not matched_level2 or matched_level3:
        return False

    return (matched_level1, matched_level2, "") in _category_candidate_paths(candidate_rules)


def _hydrate_matched_rule_path(
    result: SemanticClassificationResult,
    candidate_rules: CandidateRuleSet,
) -> SemanticClassificationResult:
    """用候选规则 ID 回填真实规则路径，避免信任 LLM 自己写的分类名称。"""
    matched_rule = _find_candidate_rule_by_id(candidate_rules, result.matched_candidate_rule_id)
    if matched_rule is None:
        return result

    return result.model_copy(
        update={
            "matched_level1": matched_rule.level1,
            "matched_level2": matched_rule.level2,
            "matched_level3": matched_rule.level3,
        }
    )


def _build_classification_prompt(
        audit_case: AuditCase,
        evidence: EvidencePackage,
        candidate_rules: CandidateRuleSet,
) -> str:
    """构造审批判断 prompt。"""
    candidate_rule_text = "\n".join(
        f"- {rule_id}: {rule.level1} / {rule.level2} / {rule.level3}，关键词：{', '.join(rule.keywords)}"
        for rule_id, rule in _candidate_rule_items(candidate_rules)
    )
    category_candidate_text = "\n".join(
        _format_category_candidate_prompt_item(candidate_id, candidate)
        for candidate_id, candidate in _category_candidate_items(candidate_rules)
    )

    evidence_snippets = "\n".join(
        f"- {snippet.text}"
        for snippet in evidence.snippets
    )
    entered_category_path = _build_entered_category_path(audit_case)
    subcategory_note = (
        "细分分类可能是二级分类，也可能是三级分类；"
        "二级分类为空时，请用“一级分类 + 细分分类”判断它是否对应候选规则中的二级或三级；"
        "如果细分分类包含多个值，需要拆开逐项判断。"
    )

    return f"""
        请判断员工录入的企业分类是否合理。
        
        【员工录入】
        企业名称：{audit_case.company_name}
        员工录入分类：{entered_category_path}
        细分分类说明：{subcategory_note}
        细分粒度识别：{candidate_rules.entered_subcategory_granularity}
        粒度识别原因：{candidate_rules.granularity_reason}
        
        【候选规则】
        {candidate_rule_text}

        【分类候选粒度】
        {category_candidate_text or "暂无显式分类候选粒度，请按候选规则判断。"}
        
        【外部证据】
        业务描述：{evidence.business_scope}
        证据质量分：{evidence.quality_score}
        证据片段：
        {evidence_snippets}
        
        【分类路径是否存在】
        {candidate_rules.entered_path_exists}
        
        请只输出 JSON，字段必须如下：
        {{
          "result": "supports_entered_category | conflicts_with_entered_category | insufficient_evidence | uncertain",
          "confidence": 0-100,
          "matched_candidate_rule_id": "只能从候选规则 ID 中选择，例如 rule_1；无法选择时为空字符串",
          "matched_category_candidate_ids": ["只能从分类候选 ID 中选择，例如 category_1；可返回多个"],
          "unsupported_entered_values": ["证据未覆盖的员工录入细分值；没有则为空数组"],
          "matched_level1": "只能从候选规则中选择，无法选择时为空字符串",
          "matched_level2": "只能从候选规则中选择，无法选择时为空字符串",
          "matched_level3": "只能从候选规则中选择，无法选择时为空字符串",
          "evidence_quotes": ["支撑判断的证据片段"],
          "reason": "判断原因",
          "suggestion": "只能基于候选规则给出完整分类路径，不能自己创造分类"
        }}
        
        规则：
        1. 你只做语义判断，不输出最终审批动作。
        2. 证据不足时 result 输出 insufficient_evidence。
        3. 证据支持员工录入分类时 result 输出 supports_entered_category。
        4. 证据明确不支持员工录入分类时 result 输出 conflicts_with_entered_category。
        5. 证据同时覆盖多个明显业务方向或无法判断时 result 输出 uncertain。
        6. 优先返回 matched_candidate_rule_id，不要自己创造分类 ID。
        7. matched_level1/matched_level2/matched_level3 仅作为兼容字段，必须来自候选规则，不允许创造分类。
        8. 如果细分粒度识别为 level2，员工录入的每个逗号分隔值都是一个二级候选。
        9. 如果细分粒度识别为 level2，证据支持该二级分类即可认为支持该员工录入值，matched_level3 可以为空。
        10. 如果细分粒度识别为 level2 且有多个逗号分隔分类，必须逐个判断；
            全部支持时 result 才能输出 supports_entered_category，并返回 matched_category_candidate_ids。
        11. 如果只有部分员工录入值被证据支持，result 输出 uncertain 或 conflicts_with_entered_category，
            并在 unsupported_entered_values 中列出未覆盖的值。
        12. 如果细分粒度识别为 level3，证据必须支持该具体三级分类，不能只因命中二级分类名就通过。
        13. level3 判断不是字符串精确匹配；如果证据中的产品、服务、行业常用称呼、同义词或上下位概念
            能够支撑候选三级分类，可以判定为 supports_entered_category。
        14. 如果细分粒度识别为 mixed、ambiguous 或 unknown，result 必须输出 uncertain。
        15. 如果证据只说明某产品或服务“适用于/用于/服务于”某行业或作物，
            不能直接认定企业主营就是该行业或作物；例如肥料适用于果树、蔬菜，
            不等于企业主营水果作物或蔬菜作物，此时应输出 uncertain 或 conflicts_with_entered_category。
        """.strip()


def _format_category_candidate_prompt_item(candidate_id: str, candidate) -> str:
    """格式化二级/三级分类候选，帮助 LLM 理解员工录入粒度。"""
    path = " / ".join(part for part in [candidate.level1, candidate.level2, candidate.level3] if part)
    child_note = f"，三级子类数量：{candidate.child_count}" if candidate.granularity == "level2" else ""
    keywords = ", ".join(candidate.keywords)
    return f"- {candidate_id}: 粒度：{candidate.granularity}，路径：{path}{child_note}，关键词：{keywords}"


def _build_entered_category_path(audit_case: AuditCase) -> str:
    """构造给 LLM 看的员工录入分类路径。"""
    parts = [
        audit_case.entered_level1,
        audit_case.entered_level2,
        audit_case.entered_subcategory,
    ]
    return " / ".join(part.strip() for part in parts if part and part.strip())


def _candidate_rule_id(index: int) -> str:
    """生成本次 prompt 内稳定的候选规则 ID。"""
    return f"rule_{index + 1}"


def _candidate_rule_items(candidate_rules: CandidateRuleSet) -> list[tuple[str, CategoryRule]]:
    """返回候选规则 ID 和规则对象的配对。"""
    return [
        (_candidate_rule_id(index), rule)
        for index, rule in enumerate(candidate_rules.candidates)
    ]


def _candidate_rule_ids(candidate_rules: CandidateRuleSet) -> set[str]:
    """返回本次 prompt 中允许 LLM 使用的候选规则 ID。"""
    return {rule_id for rule_id, _ in _candidate_rule_items(candidate_rules)}


def _category_candidate_id(index: int) -> str:
    """生成本次 prompt 内稳定的分类候选 ID。"""
    return f"category_{index + 1}"


def _category_candidate_items(candidate_rules: CandidateRuleSet) -> list[tuple[str, Any]]:
    """返回分类候选 ID 和候选对象的配对。"""
    return [
        (_category_candidate_id(index), candidate)
        for index, candidate in enumerate(candidate_rules.category_candidates)
    ]


def _category_candidate_ids(candidate_rules: CandidateRuleSet) -> set[str]:
    """返回本次 prompt 中允许 LLM 使用的分类候选 ID。"""
    return {candidate_id for candidate_id, _ in _category_candidate_items(candidate_rules)}


def _category_candidate_paths(candidate_rules: CandidateRuleSet) -> set[tuple[str, str, str]]:
    """返回二级/三级分类候选路径，二级候选的 level3 为空。"""
    return {
        (candidate.level1, candidate.level2, candidate.level3)
        for _, candidate in _category_candidate_items(candidate_rules)
    }


def _find_candidate_rule_by_id(candidate_rules: CandidateRuleSet, rule_id: str) -> CategoryRule | None:
    """根据本次 prompt 内的候选规则 ID 回查规则。"""
    for current_rule_id, rule in _candidate_rule_items(candidate_rules):
        if current_rule_id == rule_id:
            return rule

    return None


def _find_candidate_rule_id(candidate_rules: CandidateRuleSet, target_rule: CategoryRule | None) -> str:
    """根据规则对象回查本次 prompt 内的候选规则 ID。"""
    if target_rule is None:
        return ""

    for rule_id, rule in _candidate_rule_items(candidate_rules):
        if rule == target_rule:
            return rule_id

    return ""
