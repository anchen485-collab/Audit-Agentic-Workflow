import json
from pathlib import Path

from app.domain.models import AuditCase, CategoryRule
from app.infrastructure.rule_repository import load_category_rules
from app.services.category_text import split_entered_subcategories
from app.services.rule_retriever import RuleRecallConfig, retrieve_candidate_rules

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RULE_FILE = PROJECT_ROOT / "data" / "rules" / "category_rules.demo.json"
SAMPLE_FILE = PROJECT_ROOT / "tests" / "fixtures" / "sample_cases.json"

EXPECTED_LEVEL3_BY_CASE_ID = {
    "case_001": "软件开发",
    "case_002": "医疗设备",
    "case_003": "种植业",
    "case_004": "软件开发",
    "case_005": "肥料制造",
    "case_006": "商务会展",
    "case_007": "软件开发",
    "case_008": "种植业",
    "case_009": "软件开发",
    "case_010": "软件开发",
}


def test_retrieve_candidate_rules_returns_default_top_five():
    """默认最多召回 5 条不同分类路径，平衡候选完整性和 prompt 成本。"""
    rules = load_category_rules(RULE_FILE)
    audit_case = AuditCase(
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

    rule_set = retrieve_candidate_rules(audit_case, rules)

    assert len(rule_set.candidates) <= 5
    assert rule_set.candidates[0].level3 == "软件开发"
    assert rule_set.entered_path_exists is True


def test_retrieve_candidate_rules_marks_unknown_entered_path():
    """员工录入分类不存在时，应该明确标记，后续进入人工复核。"""
    rules = load_category_rules(RULE_FILE)
    audit_case = AuditCase(
        case_id="case_010",
        batch_id="batch_001",
        row_number=11,
        employee_name="王十二",
        company_raw="深圳新界互动科技有限公司 https://xinjie.example.com",
        company_name="深圳新界互动科技有限公司",
        website_url="https://xinjie.example.com",
        entered_level1="未来产业服务",
        entered_subcategory="元宇宙生态运营",
        entered_stage="录入",
        status="pending",
    )

    rule_set = retrieve_candidate_rules(audit_case, rules)

    assert rule_set.entered_path_exists is False
    assert "软件开发" in [rule.level3 for rule in rule_set.candidates]


def test_retrieve_candidate_rules_accepts_subcategory_as_level2_when_level2_is_empty():
    """员工没有单独录入二级列时，细分命中二级分类也应该认为路径存在。"""
    rules = [
        CategoryRule(
            level1="渔业",
            level2="海水捕捞",
            level3="远洋捕捞",
            module="业务领域",
            keywords=["捕捞", "远洋"],
        )
    ]
    audit_case = AuditCase(
        case_id="case_fishery_001",
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

    rule_set = retrieve_candidate_rules(audit_case, rules)

    assert rule_set.entered_path_exists is True
    assert rule_set.candidates[0].level2 == "海水捕捞"


def test_retrieve_candidate_rules_uses_level2_when_employee_provides_it():
    """员工录入了二级列时，应该用一级、二级、细分一起判断分类路径。"""
    rules = [
        CategoryRule(
            level1="渔业",
            level2="捕捞服务",
            level3="海水捕捞",
            module="业务领域",
            keywords=["捕捞"],
        )
    ]
    audit_case = AuditCase(
        case_id="case_fishery_002",
        batch_id="batch_001",
        row_number=2,
        employee_name="刘丹",
        company_raw="示例渔业有限公司 https://example.com",
        company_name="示例渔业有限公司",
        website_url="https://example.com",
        entered_level1="渔业",
        entered_level2="捕捞服务",
        entered_subcategory="海水捕捞",
        status="pending",
    )

    rule_set = retrieve_candidate_rules(audit_case, rules)

    assert rule_set.entered_path_exists is True
    assert rule_set.candidates[0].level3 == "海水捕捞"


def test_retrieve_candidate_rules_splits_multiple_subcategories():
    """细分单元格里录入多个分类时，应该拆开后逐项匹配规则库。"""
    rules = [
        CategoryRule(
            level1="渔业",
            level2="海水捕捞",
            level3="近海捕捞",
            module="业务领域",
            keywords=["海水捕捞"],
        ),
        CategoryRule(
            level1="渔业",
            level2="淡水捕捞",
            level3="内陆捕捞",
            module="业务领域",
            keywords=["淡水捕捞"],
        ),
    ]
    audit_case = AuditCase(
        case_id="case_fishery_003",
        batch_id="batch_001",
        row_number=2,
        employee_name="刘丹",
        company_raw="示例渔业有限公司 https://example.com",
        company_name="示例渔业有限公司",
        website_url="https://example.com",
        entered_level1="渔业",
        entered_subcategory="海水捕捞,淡水捕捞",
        status="pending",
    )

    rule_set = retrieve_candidate_rules(audit_case, rules)

    assert rule_set.entered_path_exists is True
    assert {rule.level2 for rule in rule_set.candidates} == {"海水捕捞", "淡水捕捞"}


def test_split_entered_subcategories_uses_comma_separator():
    """员工细分只按逗号拆分，不能把分类路径里的斜杠误拆成多个细分。"""
    assert split_entered_subcategories("蔬菜作物,水果作物") == ["蔬菜作物", "水果作物"]
    assert split_entered_subcategories("蔬菜作物，水果作物") == ["蔬菜作物", "水果作物"]
    assert split_entered_subcategories("种植业 / 蔬菜作物") == ["种植业 / 蔬菜作物"]


def test_sample_cases_rule_recall_rate_reaches_90_percent():
    """10 条样例的目标分类召回率应该达到 90% 以上。"""
    rules = load_category_rules(RULE_FILE)
    sample_cases = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))

    hit_count = 0

    for index, sample_case in enumerate(sample_cases, start=2):
        input_data = sample_case["input"]
        audit_case = AuditCase(
            case_id=sample_case["case_id"],
            batch_id="sample_batch",
            row_number=index,
            employee_name=input_data["employee_name"],
            company_raw=input_data["company_raw"],
            company_name=input_data["company_name"],
            website_url=input_data["website_url"],
            entered_level1=input_data["entered_level1"],
            entered_subcategory=input_data["entered_subcategory"],
            entered_stage=input_data["entered_stage"],
            status="pending",
        )

        rule_set = retrieve_candidate_rules(audit_case, rules)
        recalled_level3 = {rule.level3 for rule in rule_set.candidates}
        expected_level3 = EXPECTED_LEVEL3_BY_CASE_ID[sample_case["case_id"]]

        if expected_level3 in recalled_level3:
            hit_count += 1

    recall_rate = hit_count / len(sample_cases)

    assert recall_rate >= 0.9


def test_retrieve_candidate_rules_deduplicates_same_category_path_before_topk():
    """相同分类路径的重复规则不能占用多个候选名额。"""
    audit_case = _build_security_case("巡逻服务有限公司")
    duplicate_rules = [
        _rule("安全保护服务", "安全服务", "企事业单位治安保卫", "行业类型", ["企事业单位治安保卫"]),
        _rule("安全保护服务", "安全服务", "企事业单位治安保卫", "生态", ["企事业单位治安保卫", "银行"]),
        _rule("安全保护服务", "安全服务", "企事业单位治安保卫", "案例", ["企事业单位治安保卫", "学校"]),
        _rule("安全保护服务", "安全服务", "人力防范", "服务标准化管理", ["人力防范"]),
        _rule("安全保护服务", "安全系统监控服务", "安全技术防范", "技术功能类型", ["安全技术防范"]),
    ]

    rule_set = retrieve_candidate_rules(audit_case, duplicate_rules, config=RuleRecallConfig(default_top_k=3))
    candidate_paths = _candidate_paths(rule_set)

    assert len(candidate_paths) == len(set(candidate_paths))
    assert candidate_paths == [
        "安全保护服务 / 安全服务 / 企事业单位治安保卫",
        "安全保护服务 / 安全服务 / 人力防范",
        "安全保护服务 / 安全系统监控服务 / 安全技术防范",
    ]
    assert rule_set.raw_match_count == 5
    assert rule_set.deduped_match_count == 3
    assert "已按分类路径去重" in rule_set.retrieval_reason


def test_retrieve_candidate_rules_keeps_all_exact_entered_subcategories():
    """员工录入的多个精确细分命中应该全部保留，允许超过默认 Top5。"""
    exact_rules = [
        _rule("安全保护服务", f"服务{i}", f"细分{i}", "业务", [f"细分{i}"])
        for i in range(1, 7)
    ]
    distractor_rules = [
        _rule("安全保护服务", f"干扰{i}", f"干扰细分{i}", "业务", ["安全保护服务"])
        for i in range(1, 4)
    ]
    audit_case = _build_case_with_subcategories([f"细分{i}" for i in range(1, 7)])

    rule_set = retrieve_candidate_rules(audit_case, [*distractor_rules, *exact_rules])

    recalled_level3 = {rule.level3 for rule in rule_set.candidates}
    assert {f"细分{i}" for i in range(1, 7)} <= recalled_level3
    assert len(rule_set.candidates) == 6
    assert rule_set.exact_match_count == 6
    assert rule_set.truncated is False


def test_retrieve_candidate_rules_caps_dynamic_recall_at_top8():
    """精确命中超过 Top8 时应该截断，并在召回原因中说明。"""
    rules = [
        _rule("安全保护服务", f"服务{i}", f"细分{i}", "业务", [f"细分{i}"])
        for i in range(1, 11)
    ]
    audit_case = _build_case_with_subcategories([f"细分{i}" for i in range(1, 11)])

    rule_set = retrieve_candidate_rules(audit_case, rules)

    assert len(rule_set.candidates) == 8
    assert rule_set.exact_match_count == 10
    assert rule_set.truncated is True
    assert "超过最大候选数 Top8" in rule_set.retrieval_reason


def test_retrieve_candidate_rules_supports_legacy_limit_parameter():
    """短期保留 limit 参数，方便旧测试和回滚场景显式限制候选数。"""
    rules = [
        _rule("安全保护服务", f"服务{i}", f"细分{i}", "业务", [f"细分{i}"])
        for i in range(1, 5)
    ]
    audit_case = _build_case_with_subcategories(["细分1"])

    rule_set = retrieve_candidate_rules(audit_case, rules, limit=2)

    assert len(rule_set.candidates) <= 2
    assert rule_set.recall_default_top_k == 2
    assert rule_set.recall_max_top_k == 2


def test_retrieve_identifies_entered_subcategory_as_level3():
    """员工细分填三级分类时，应该识别为 level3 并精确保留该三级候选。"""
    rules = [
        _rule("卫生和社会工作", "医院", "专科医院", "业务领域", ["专科医院", "骨科医院"]),
        _rule("卫生和社会工作", "医院", "民族医院", "业务领域", ["民族医院"]),
        _rule("卫生和社会工作", "基层医疗卫生服务", "门诊部", "业务领域", ["门诊"]),
    ]
    audit_case = _build_health_case("专科医院")

    rule_set = retrieve_candidate_rules(audit_case, rules, config=RuleRecallConfig(default_top_k=1, max_top_k=1))

    assert rule_set.entered_subcategory_granularity == "level3"
    assert rule_set.entered_path_exists is True
    assert [candidate.granularity for candidate in rule_set.category_candidates] == ["level3"]
    assert _category_candidate_paths(rule_set) == ["卫生和社会工作 / 医院 / 专科医院"]
    assert "专科医院" in {rule.level3 for rule in rule_set.candidates}


def test_retrieve_identifies_entered_subcategory_as_level2():
    """员工细分填二级分类时，应该保留二级候选本身，并聚合其下三级子类。"""
    rules = [
        _rule("卫生和社会工作", "医院", f"医院子类{i}", "业务领域", [f"医院子类{i}"])
        for i in range(1, 13)
    ]
    audit_case = _build_health_case("医院")

    rule_set = retrieve_candidate_rules(audit_case, rules, config=RuleRecallConfig(default_top_k=3, max_top_k=3))

    assert rule_set.entered_subcategory_granularity == "level2"
    assert rule_set.entered_path_exists is True
    assert len(rule_set.candidates) == 3
    assert len(rule_set.category_candidates) == 1
    assert rule_set.category_candidates[0].granularity == "level2"
    assert rule_set.category_candidates[0].level2 == "医院"
    assert rule_set.category_candidates[0].level3 == ""
    assert rule_set.category_candidates[0].child_count == 12
    assert len(rule_set.category_candidates[0].children) == 12
    assert "员工录入细分命中二级分类" in rule_set.granularity_reason


def test_retrieve_marks_mixed_level2_and_level3_values():
    """同一条细分里同时填二级和三级分类时，应该标记 mixed，交给人工确认。"""
    rules = [
        _rule("卫生和社会工作", "医院", "专科医院", "业务领域", ["专科医院"]),
        _rule("卫生和社会工作", "提供住宿社会工作", "老年人养护服务", "业务领域", ["养老"]),
    ]
    audit_case = _build_health_case("医院，老年人养护服务")

    rule_set = retrieve_candidate_rules(audit_case, rules)

    assert rule_set.entered_subcategory_granularity == "mixed"
    assert rule_set.entered_path_exists is False
    assert "混合了二级和三级分类" in rule_set.granularity_reason


def test_retrieve_marks_ambiguous_level3_name():
    """同名三级分类落在多个二级路径下时，应该标记 ambiguous，避免自动误判。"""
    rules = [
        _rule("居民服务", "家庭服务", "护理服务", "业务领域", ["家庭护理"]),
        _rule("居民服务", "健康服务", "护理服务", "业务领域", ["健康护理"]),
    ]
    audit_case = AuditCase(
        case_id="case_ambiguous",
        batch_id="batch_001",
        row_number=2,
        employee_name="刘丹",
        company_raw="测试居民服务公司",
        company_name="测试居民服务公司",
        website_url="",
        entered_level1="居民服务",
        entered_subcategory="护理服务",
        status="pending",
    )

    rule_set = retrieve_candidate_rules(audit_case, rules)

    assert rule_set.entered_subcategory_granularity == "ambiguous"
    assert rule_set.entered_path_exists is False
    assert "护理服务" in rule_set.ambiguous_values
    assert "存在多个可能分类路径" in rule_set.granularity_reason


def test_retrieve_candidate_rules_matches_multiple_level1_values():
    """一级分类录入多个值时，应分别匹配每个细分所属的一级分类。"""
    rules = [
        _rule("种植业", "水果作物", "核果仁果类", "业务领域", ["水果作物", "苹果", "鲜桃"]),
        _rule("畜牧业", "家畜", "牛", "业务领域", ["家畜", "肉牛"]),
    ]
    audit_case = AuditCase(
        case_id="case_multi_level1",
        batch_id="batch_001",
        row_number=2,
        employee_name="刘丹",
        company_raw="河北恒康伟业农业技术开发集团有限公司 https://www.hbhkwy.cn/",
        company_name="河北恒康伟业农业技术开发集团有限公司",
        website_url="https://www.hbhkwy.cn/",
        entered_level1="种植业,畜牧业",
        entered_subcategory="水果作物,家畜",
        status="pending",
    )

    rule_set = retrieve_candidate_rules(audit_case, rules)

    assert rule_set.entered_subcategory_granularity == "level2"
    assert rule_set.entered_path_exists is True
    assert {(candidate.level1, candidate.level2) for candidate in rule_set.category_candidates} == {
        ("种植业", "水果作物"),
        ("畜牧业", "家畜"),
    }


def _rule(level1: str, level2: str, level3: str, module: str, keywords: list[str]) -> CategoryRule:
    """构造测试用分类规则。"""
    return CategoryRule(
        level1=level1,
        level2=level2,
        level3=level3,
        module=module,
        keywords=keywords,
    )


def _build_security_case(company_name: str) -> AuditCase:
    """构造安保服务多细分测试审批单。"""
    return AuditCase(
        case_id="case_security",
        batch_id="batch_001",
        row_number=2,
        employee_name="刘丹",
        company_raw=company_name,
        company_name=company_name,
        website_url="",
        entered_level1="安全保护服务",
        entered_subcategory="企事业单位治安保卫,人力防范,安全技术防范",
        status="pending",
    )


def _build_case_with_subcategories(subcategories: list[str]) -> AuditCase:
    """构造多细分测试审批单。"""
    return AuditCase(
        case_id="case_multi_subcategory",
        batch_id="batch_001",
        row_number=2,
        employee_name="刘丹",
        company_raw="测试安全服务有限公司",
        company_name="测试安全服务有限公司",
        website_url="",
        entered_level1="安全保护服务",
        entered_subcategory=",".join(subcategories),
        status="pending",
    )


def _build_health_case(entered_subcategory: str) -> AuditCase:
    """构造医疗场景审批单，用于测试二级/三级细分粒度。"""
    return AuditCase(
        case_id="case_health",
        batch_id="batch_001",
        row_number=2,
        employee_name="刘丹",
        company_raw="测试医院有限公司 https://example.com",
        company_name="测试医院有限公司",
        website_url="https://example.com",
        entered_level1="卫生和社会工作",
        entered_subcategory=entered_subcategory,
        status="pending",
    )


def _candidate_paths(rule_set) -> list[str]:
    """把候选规则转成完整分类路径，避免只看三级分类造成误判。"""
    return [
        f"{rule.level1} / {rule.level2} / {rule.level3}"
        for rule in rule_set.candidates
    ]


def _category_candidate_paths(rule_set) -> list[str]:
    """把新分类候选模型转成路径，方便断言粒度识别结果。"""
    return [
        " / ".join(part for part in [candidate.level1, candidate.level2, candidate.level3] if part)
        for candidate in rule_set.category_candidates
    ]
