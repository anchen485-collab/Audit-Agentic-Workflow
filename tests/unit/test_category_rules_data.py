from pathlib import Path

from app.infrastructure.rule_repository import load_category_rules

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RULE_FILE = PROJECT_ROOT / "data" / "rules" / "category_rules.json"


def test_security_rules_use_standard_level1_name():
    """正式规则表中的安保类一级分类应该使用业务标准名称。"""
    rules = load_category_rules(RULE_FILE)
    security_rules = [rule for rule in rules if rule.level3 == "安全技术防范"]

    assert security_rules
    assert {rule.level1 for rule in security_rules} == {"安全保护服务"}
    assert all(rule.level1 != "安保服务" for rule in rules)
