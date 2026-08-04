import json

import pytest

from app.infrastructure.rule_repository import load_category_rules


def test_load_category_rules_from_json_file(tmp_path):
    """应该能从 JSON 文件加载分类规则。"""
    rule_file = tmp_path / "category_rules.json"
    rule_file.write_text(
        json.dumps(
            [
                {
                    "level1": "信软技术服务",
                    "level2": "软件和信息技术",
                    "level3": "软件开发",
                    "module": "业务领域",
                    "keywords": ["软件开发", "系统集成"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rules = load_category_rules(rule_file)

    assert len(rules) == 1
    assert rules[0].level1 == "信软技术服务"
    assert rules[0].level3 == "软件开发"


def test_load_category_rules_rejects_missing_file(tmp_path):
    """规则文件不存在时，应该抛出清晰错误。"""
    missing_file = tmp_path / "missing.json"

    with pytest.raises(FileNotFoundError):
        load_category_rules(missing_file)


def test_load_category_rules_rejects_invalid_json(tmp_path):
    """规则文件不是合法 JSON 时，应该抛出清晰错误。"""
    rule_file = tmp_path / "category_rules.json"
    rule_file.write_text("{bad json", encoding="utf-8")

    with pytest.raises(ValueError, match="合法 JSON"):
        load_category_rules(rule_file)