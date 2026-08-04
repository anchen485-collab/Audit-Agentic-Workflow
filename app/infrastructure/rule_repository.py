import json
from pathlib import Path

from pydantic import ValidationError

from app.domain.models import CategoryRule


def load_category_rules(file_path: str | Path) -> list[CategoryRule]:
    """从 JSON 文件加载内部分类规则。"""
    rule_path = Path(file_path)

    if not rule_path.exists():
        raise FileNotFoundError(f"规则文件不存在：{rule_path}")

    try:
        raw_rules = json.loads(rule_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"规则文件不是合法 JSON：{rule_path}") from error

    if not isinstance(raw_rules, list):
        raise ValueError("规则文件顶层必须是一个列表。")

    try:
        return [CategoryRule.model_validate(rule) for rule in raw_rules]
    except ValidationError as error:
        raise ValueError("规则文件字段结构不符合 CategoryRule 模型。") from error