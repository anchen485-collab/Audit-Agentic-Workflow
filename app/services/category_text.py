import re

SUBCATEGORY_SEPARATOR_PATTERN = re.compile(r"[,，]+")


def split_entered_subcategories(value: str) -> list[str]:
    """按员工 Excel 约定拆分细分列：只用英文逗号和中文逗号分隔多个分类。"""
    return [
        item.strip()
        for item in SUBCATEGORY_SEPARATOR_PATTERN.split(value or "")
        if item.strip()
    ]
