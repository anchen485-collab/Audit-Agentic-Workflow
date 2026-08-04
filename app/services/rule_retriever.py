import re
from dataclasses import dataclass

from app.domain.models import AuditCase, CandidateCategory, CandidateRuleSet, CategoryRule
from app.services.category_text import split_entered_subcategories


@dataclass(frozen=True)
class RuleRecallConfig:
    """规则召回配置，避免在调用点散落 TopK 魔法数字。"""

    default_top_k: int = 5
    max_top_k: int = 8
    exact_match_score_threshold: int = 7


@dataclass
class ScoredRule:
    """带分数的候选规则，只在规则召回内部使用。"""

    rule: CategoryRule
    score: int
    reasons: list[str]
    original_index: int
    exact_entered_matches: list[str]


@dataclass
class CategoryIndex:
    """分类索引：用标准化后的分类名快速查找二级、三级和完整路径。"""

    level2_by_key: dict[tuple[str, str], list[CategoryRule]]
    level3_by_key: dict[tuple[str, str], list[CategoryRule]]
    full_path_by_key: dict[tuple[str, str, str], list[CategoryRule]]


@dataclass
class EnteredSubcategoryMatchResult:
    """员工细分粒度识别结果。"""

    granularity: str
    level2_matches: list[CandidateCategory]
    level3_matches: list[CandidateCategory]
    unmatched_values: list[str]
    ambiguous_values: list[str]
    reason: str


def retrieve_candidate_rules(
    audit_case: AuditCase,
    rules: list[CategoryRule],
    limit: int | None = None,
    config: RuleRecallConfig | None = None,
) -> CandidateRuleSet:
    """根据审批单内容召回候选分类规则。

    召回策略分三步：
    1. 对规则打分后按分类路径去重，避免重复路径占满候选位。
    2. 优先保留员工录入细分精确命中的规则。
    3. 再按得分补足默认 Top5，总量最多 Top8。
    """
    recall_config = _resolve_config(limit=limit, config=config)
    granularity_result = classify_entered_subcategory_granularity(audit_case, rules)
    scored_rules = [
        _score_rule(audit_case=audit_case, rule=rule, original_index=index)
        for index, rule in enumerate(rules)
    ]
    matched_rules = [item for item in scored_rules if item.score > 0]
    raw_match_count = len(matched_rules)
    deduped_rules = _deduplicate_scored_rules(matched_rules)
    exact_matches = _find_exact_entered_matches(
        audit_case=audit_case,
        deduped_rules=deduped_rules,
        threshold=recall_config.exact_match_score_threshold,
    )
    target_size = _calculate_dynamic_limit(
        default_top_k=recall_config.default_top_k,
        max_top_k=recall_config.max_top_k,
        exact_match_count=len(exact_matches),
    )
    selected_rules = _select_candidate_rules(
        exact_matches=exact_matches,
        deduped_rules=deduped_rules,
        target_size=target_size,
    )
    truncated = len(exact_matches) > target_size

    entered_path_exists = _entered_path_exists_by_granularity(granularity_result)
    retrieval_reason = _build_retrieval_reason(
        selected_rules=selected_rules,
        entered_path_exists=entered_path_exists,
        raw_match_count=raw_match_count,
        deduped_match_count=len(deduped_rules),
        exact_match_count=len(exact_matches),
        truncated=truncated,
        max_top_k=recall_config.max_top_k,
    )
    retrieval_reason = f"{retrieval_reason} {granularity_result.reason}".strip()

    return CandidateRuleSet(
        case_id=audit_case.case_id,
        entered_path_exists=entered_path_exists,
        candidates=[item.rule for item in selected_rules],
        retrieval_reason=retrieval_reason,
        recall_default_top_k=recall_config.default_top_k,
        recall_max_top_k=recall_config.max_top_k,
        raw_match_count=raw_match_count,
        deduped_match_count=len(deduped_rules),
        exact_match_count=len(exact_matches),
        truncated=truncated,
        category_candidates=[
            *granularity_result.level2_matches,
            *granularity_result.level3_matches,
        ],
        entered_subcategory_granularity=granularity_result.granularity,
        granularity_reason=granularity_result.reason,
        unmatched_values=granularity_result.unmatched_values,
        ambiguous_values=granularity_result.ambiguous_values,
    )


def classify_entered_subcategory_granularity(
    audit_case: AuditCase,
    rules: list[CategoryRule],
) -> EnteredSubcategoryMatchResult:
    """识别员工细分列填的是二级分类、三级分类，还是存在异常粒度。"""
    index = _build_category_index(rules)
    entered_values = _split_entered_subcategories(audit_case.entered_subcategory)
    level2_matches: list[CandidateCategory] = []
    level3_matches: list[CandidateCategory] = []
    unmatched_values: list[str] = []
    ambiguous_values: list[str] = []

    level1_keys = [_normalize_category_text(value) for value in _split_entered_level1_values(audit_case)]
    for entered_value in entered_values:
        value_key = _normalize_category_text(entered_value)
        level2_rules = [
            rule
            for level1_key in level1_keys
            for rule in index.level2_by_key.get((level1_key, value_key), [])
        ]
        level3_rules = [
            rule
            for level1_key in level1_keys
            for rule in index.level3_by_key.get((level1_key, value_key), [])
        ]

        if level2_rules and level3_rules:
            ambiguous_values.append(entered_value)
            continue

        if level3_rules:
            level2_names = {_normalize_category_text(rule.level2) for rule in level3_rules}
            if len(level2_names) > 1:
                ambiguous_values.append(entered_value)
                continue

            level3_matches.extend(
                _build_level3_candidate(rule, matched_entered_value=entered_value)
                for rule in level3_rules
            )
            continue

        if level2_rules:
            level2_matches.append(_build_level2_candidate(level2_rules, matched_entered_value=entered_value))
            continue

        unmatched_values.append(entered_value)

    return _build_granularity_result(
        level2_matches=level2_matches,
        level3_matches=level3_matches,
        unmatched_values=unmatched_values,
        ambiguous_values=ambiguous_values,
    )


def _resolve_config(limit: int | None, config: RuleRecallConfig | None) -> RuleRecallConfig:
    """合并兼容参数和新配置；limit 只用于旧调用显式限制候选数。"""
    if limit is not None:
        safe_limit = max(1, int(limit))
        threshold = config.exact_match_score_threshold if config else RuleRecallConfig().exact_match_score_threshold
        return RuleRecallConfig(
            default_top_k=safe_limit,
            max_top_k=safe_limit,
            exact_match_score_threshold=threshold,
        )

    return config or RuleRecallConfig()


def _build_category_index(rules: list[CategoryRule]) -> CategoryIndex:
    """构建分类索引，索引 key 使用标准化文本，返回值保留原始规则名用于展示。"""
    level2_by_key: dict[tuple[str, str], list[CategoryRule]] = {}
    level3_by_key: dict[tuple[str, str], list[CategoryRule]] = {}
    full_path_by_key: dict[tuple[str, str, str], list[CategoryRule]] = {}

    for rule in _deduplicate_rules_by_path(rules):
        level1_key = _normalize_category_text(rule.level1)
        level2_key = _normalize_category_text(rule.level2)
        level3_key = _normalize_category_text(rule.level3)

        level2_by_key.setdefault((level1_key, level2_key), []).append(rule)
        level3_by_key.setdefault((level1_key, level3_key), []).append(rule)
        full_path_by_key.setdefault((level1_key, level2_key, level3_key), []).append(rule)

    return CategoryIndex(
        level2_by_key=level2_by_key,
        level3_by_key=level3_by_key,
        full_path_by_key=full_path_by_key,
    )


def _deduplicate_rules_by_path(rules: list[CategoryRule]) -> list[CategoryRule]:
    """按完整分类路径去重，避免重复规则污染候选和子类统计。"""
    unique_rules: dict[tuple[str, str, str], CategoryRule] = {}
    for rule in rules:
        unique_rules.setdefault(_normalized_category_path_key(rule), rule)

    return list(unique_rules.values())


def _build_level2_candidate(rules: list[CategoryRule], matched_entered_value: str) -> CandidateCategory:
    """把一个二级分类和它下面的三级子类聚合成一个二级候选。"""
    unique_children = _deduplicate_rules_by_path(rules)
    first_rule = unique_children[0]

    return CandidateCategory(
        level1=first_rule.level1,
        level2=first_rule.level2,
        level3="",
        granularity="level2",
        matched_entered_value=matched_entered_value,
        child_count=len(unique_children),
        children=unique_children,
        keywords=_merge_candidate_keywords(unique_children, include_level3=True),
    )


def _build_level3_candidate(rule: CategoryRule, matched_entered_value: str) -> CandidateCategory:
    """把一条三级规则转换成新的分类候选模型。"""
    return CandidateCategory(
        level1=rule.level1,
        level2=rule.level2,
        level3=rule.level3,
        granularity="level3",
        matched_entered_value=matched_entered_value,
        child_count=0,
        children=[],
        keywords=_merge_candidate_keywords([rule], include_level3=True),
    )


def _merge_candidate_keywords(rules: list[CategoryRule], include_level3: bool) -> list[str]:
    """合并候选分类关键词，保留顺序并去重。"""
    keywords: list[str] = []
    seen: set[str] = set()

    for rule in rules:
        values = [rule.level1, rule.level2, *rule.keywords]
        if include_level3:
            values.append(rule.level3)

        for value in values:
            normalized_value = value.strip()
            if not normalized_value or normalized_value in seen:
                continue
            keywords.append(normalized_value)
            seen.add(normalized_value)

    return keywords


def _build_granularity_result(
    level2_matches: list[CandidateCategory],
    level3_matches: list[CandidateCategory],
    unmatched_values: list[str],
    ambiguous_values: list[str],
) -> EnteredSubcategoryMatchResult:
    """根据命中情况汇总最终粒度结论。"""
    level2_matches = _deduplicate_category_candidates(level2_matches)
    level3_matches = _deduplicate_category_candidates(level3_matches)

    if ambiguous_values:
        return EnteredSubcategoryMatchResult(
            granularity="ambiguous",
            level2_matches=level2_matches,
            level3_matches=level3_matches,
            unmatched_values=unmatched_values,
            ambiguous_values=ambiguous_values,
            reason=f"员工录入细分存在多个可能分类路径：{', '.join(ambiguous_values)}。",
        )

    if level2_matches and level3_matches:
        return EnteredSubcategoryMatchResult(
            granularity="mixed",
            level2_matches=level2_matches,
            level3_matches=level3_matches,
            unmatched_values=unmatched_values,
            ambiguous_values=[],
            reason="同一条记录的细分混合了二级和三级分类，需要人工确认录入口径。",
        )

    if unmatched_values:
        return EnteredSubcategoryMatchResult(
            granularity="unknown",
            level2_matches=level2_matches,
            level3_matches=level3_matches,
            unmatched_values=unmatched_values,
            ambiguous_values=[],
            reason=f"员工录入细分不在当前规则库中：{', '.join(unmatched_values)}。",
        )

    if level2_matches:
        return EnteredSubcategoryMatchResult(
            granularity="level2",
            level2_matches=level2_matches,
            level3_matches=[],
            unmatched_values=[],
            ambiguous_values=[],
            reason="员工录入细分命中二级分类，已聚合该二级分类下的三级子类作为辅助信息。",
        )

    if level3_matches:
        return EnteredSubcategoryMatchResult(
            granularity="level3",
            level2_matches=[],
            level3_matches=level3_matches,
            unmatched_values=[],
            ambiguous_values=[],
            reason="员工录入细分命中三级分类，已精确召回完整分类路径。",
        )

    return EnteredSubcategoryMatchResult(
        granularity="unknown",
        level2_matches=[],
        level3_matches=[],
        unmatched_values=[],
        ambiguous_values=[],
        reason="员工录入细分为空或未命中当前规则库。",
    )


def _deduplicate_category_candidates(candidates: list[CandidateCategory]) -> list[CandidateCategory]:
    """按候选路径去重，避免重复规则导致页面展示膨胀。"""
    unique: dict[tuple[str, str, str, str], CandidateCategory] = {}
    for candidate in candidates:
        key = (
            _normalize_category_text(candidate.level1),
            _normalize_category_text(candidate.level2),
            _normalize_category_text(candidate.level3),
            candidate.granularity,
        )
        unique.setdefault(key, candidate)

    return list(unique.values())


def _entered_path_exists_by_granularity(result: EnteredSubcategoryMatchResult) -> bool:
    """只有明确命中二级或三级粒度时，才认为员工录入分类路径可自动继续判断。"""
    return result.granularity in {"level2", "level3"}


def _score_rule(audit_case: AuditCase, rule: CategoryRule, original_index: int = 0) -> ScoredRule:
    """给单条规则打分，分数越高说明越可能相关。"""
    score = 0
    reasons: list[str] = []
    search_text = _build_search_text(audit_case)
    exact_entered_matches = _exact_entered_matches(audit_case, rule)

    if _entered_level1_matches_rule(audit_case, rule):
        score += 3
        reasons.append(f"员工录入一级分类命中：{rule.level1}")

    if audit_case.entered_level2 and audit_case.entered_level2 == rule.level2:
        score += 3
        reasons.append(f"员工录入二级分类命中：{rule.level2}")

    if exact_entered_matches:
        score += 4
        reasons.append(f"员工录入细分命中：{', '.join(exact_entered_matches)}")

    for keyword in rule.keywords:
        if keyword and keyword.lower() in search_text:
            score += 2
            reasons.append(f"命中关键词：{keyword}")

    return ScoredRule(
        rule=rule,
        score=score,
        reasons=reasons,
        original_index=original_index,
        exact_entered_matches=exact_entered_matches,
    )


def _build_search_text(audit_case: AuditCase) -> str:
    """把审批单里适合做关键词匹配的字段拼成一段文本。"""
    return " ".join(
        [
            audit_case.company_raw,
            audit_case.company_name,
            audit_case.entered_level1,
            audit_case.entered_level2,
            audit_case.entered_subcategory,
        ]
    ).lower()


def _deduplicate_scored_rules(scored_rules: list[ScoredRule]) -> list[ScoredRule]:
    """按完整分类路径去重，同一路径只保留最可靠的一条规则。"""
    best_by_path: dict[tuple[str, str, str], ScoredRule] = {}

    for item in scored_rules:
        path = _category_path_key(item.rule)
        current = best_by_path.get(path)
        if current is None or _dedup_priority(item) > _dedup_priority(current):
            best_by_path[path] = item

    return sorted(
        best_by_path.values(),
        key=lambda item: (-item.score, item.original_index),
    )


def _dedup_priority(item: ScoredRule) -> tuple[int, int, int]:
    """去重优先级：分数高 > 关键词多 > 原始顺序靠前。"""
    return (item.score, len(item.rule.keywords), -item.original_index)


def _find_exact_entered_matches(
    audit_case: AuditCase,
    deduped_rules: list[ScoredRule],
    threshold: int,
) -> list[ScoredRule]:
    """找出员工录入细分精确命中的高置信候选规则。"""
    exact_matches = [
        item
        for item in deduped_rules
        if item.score >= threshold and _entered_path_matches_rule(audit_case, item.rule)
    ]

    return sorted(exact_matches, key=lambda item: (-item.score, item.original_index))


def _calculate_dynamic_limit(default_top_k: int, max_top_k: int, exact_match_count: int) -> int:
    """根据精确命中数量计算本次召回候选数量。"""
    return min(max(default_top_k, exact_match_count), max_top_k)


def _select_candidate_rules(
    exact_matches: list[ScoredRule],
    deduped_rules: list[ScoredRule],
    target_size: int,
) -> list[ScoredRule]:
    """先放入精确命中，再用高分规则补足候选集。"""
    selected: list[ScoredRule] = []
    selected_paths: set[tuple[str, str, str]] = set()

    for item in exact_matches:
        if len(selected) >= target_size:
            break
        _append_if_new(selected, selected_paths, item)

    for item in deduped_rules:
        if len(selected) >= target_size:
            break
        _append_if_new(selected, selected_paths, item)

    return selected


def _append_if_new(
    selected: list[ScoredRule],
    selected_paths: set[tuple[str, str, str]],
    item: ScoredRule,
) -> None:
    """按分类路径追加候选，避免重复。"""
    path = _category_path_key(item.rule)
    if path in selected_paths:
        return

    selected.append(item)
    selected_paths.add(path)


def _entered_path_exists(audit_case: AuditCase, rules: list[CategoryRule]) -> bool:
    """判断员工录入的分类路径是否存在于内部规则库。"""
    for rule in rules:
        if _entered_path_matches_rule(audit_case, rule):
            return True

    return False


def _entered_path_matches_rule(audit_case: AuditCase, rule: CategoryRule) -> bool:
    """判断员工录入路径是否命中单条规则。

    注意：员工 Excel 里的“细分”字段可能录入二级分类，也可能录入三级分类。
    因此没有单独二级列时，不能把它理解成“二级缺失”。
    """
    if not _entered_level1_matches_rule(audit_case, rule):
        return False

    entered_level2 = audit_case.entered_level2.strip()
    entered_subcategories = _split_entered_subcategories(audit_case.entered_subcategory)

    if entered_level2:
        same_level2 = entered_level2 == rule.level2
        same_subcategory = any(value in {rule.level2, rule.level3} for value in entered_subcategories)
        return same_level2 and same_subcategory

    return _entered_subcategory_matches_rule(audit_case, rule)


def _entered_subcategory_matches_rule(audit_case: AuditCase, rule: CategoryRule) -> bool:
    """判断细分字段是否命中规则，兼容一个单元格填写多个细分。"""
    return bool(_exact_entered_matches(audit_case, rule))


def _exact_entered_matches(audit_case: AuditCase, rule: CategoryRule) -> list[str]:
    """返回细分字段中命中规则二级或三级的值。"""
    entered_subcategories = _split_entered_subcategories(audit_case.entered_subcategory)
    rule_categories = {rule.level2, rule.level3}

    return [value for value in entered_subcategories if value in rule_categories]


def _entered_level1_matches_rule(audit_case: AuditCase, rule: CategoryRule) -> bool:
    """判断员工录入的一个或多个一级分类是否命中当前规则。"""
    return rule.level1 in _split_entered_level1_values(audit_case)


def _split_entered_level1_values(audit_case: AuditCase) -> list[str]:
    """拆分员工录入的一级分类，兼容一个单元格填写多个一级分类。"""
    return split_entered_subcategories(audit_case.entered_level1)


def _split_entered_subcategories(value: str) -> list[str]:
    """拆分员工录入的细分字段。"""
    return split_entered_subcategories(value)


def _normalize_category_text(value: str) -> str:
    """标准化分类文本，只用于匹配，不改变最终展示给用户的原始名称。"""
    normalized_value = (value or "").strip().lower()
    normalized_value = re.sub(r"\s+", "", normalized_value)
    normalized_value = normalized_value.replace("（", "(").replace("）", ")")
    return normalized_value


def _category_path_key(rule: CategoryRule) -> tuple[str, str, str]:
    """分类路径唯一键。"""
    return (rule.level1, rule.level2, rule.level3)


def _normalized_category_path_key(rule: CategoryRule) -> tuple[str, str, str]:
    """标准化后的分类路径唯一键，用于去重和索引。"""
    return (
        _normalize_category_text(rule.level1),
        _normalize_category_text(rule.level2),
        _normalize_category_text(rule.level3),
    )


def _format_rule_path(rule: CategoryRule) -> str:
    """格式化完整分类路径，避免只展示三级分类造成混淆。"""
    return f"{rule.level1} / {rule.level2} / {rule.level3}"


def _build_retrieval_reason(
    selected_rules: list[ScoredRule],
    entered_path_exists: bool,
    raw_match_count: int,
    deduped_match_count: int,
    exact_match_count: int,
    truncated: bool,
    max_top_k: int,
) -> str:
    """生成可解释的召回原因，方便后续 trace 和人工复核。"""
    if not selected_rules:
        return "没有命中任何分类规则。"

    path_reason = "员工录入分类存在于规则库。" if entered_path_exists else "员工录入分类不在规则库中。"
    candidate_paths = "；".join(_format_rule_path(item.rule) for item in selected_rules)
    reason_parts = [
        path_reason,
        f"原始命中 {raw_match_count} 条，已按分类路径去重为 {deduped_match_count} 条。",
        f"员工录入细分精确命中 {exact_match_count} 条。",
        f"最终召回候选规则：{candidate_paths}。",
    ]

    if truncated:
        reason_parts.append(f"员工录入分类超过最大候选数 Top{max_top_k}，已截断。")

    return " ".join(reason_parts)
