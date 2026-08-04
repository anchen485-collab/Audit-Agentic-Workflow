import argparse
import json
import re
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from app.domain.models import CategoryRule

DEFAULT_OUTPUT_FILE = Path("data/rules/category_rules.json")
DEMO_RULE_FILE = Path("data/rules/category_rules.demo.json")
DEFAULT_INPUT_CANDIDATES = [
    Path.home() / "Desktop" / "document" / "最终分类表.xlsx",
    Path("D:/audit/docs/最终分类表.xlsx"),
]

HEADER_ALIASES = {
    "level1": ["一级品类", "一级分类"],
    "level2": ["二级品类", "二级分类"],
    "level3": ["三级品类", "三级分类", "细分"],
    "module": ["模块名称", "模块"],
    "keywords": ["子模块列表", "关键词", "关键字"],
}

KEYWORD_SPLIT_PATTERN = re.compile(r"[、，,；;\n\r\t|/]+")


def convert_category_rules_excel(input_file: str | Path, sheet_name: str | None = None) -> list[CategoryRule]:
    """把内部分类规则 Excel 转换成系统使用的 CategoryRule 列表。"""
    workbook = load_workbook(input_file, read_only=True, data_only=True)
    sheet = workbook[sheet_name] if sheet_name else workbook.active

    rows = sheet.iter_rows(values_only=True)
    try:
        headers = [_cell_to_text(value) for value in next(rows)]
    except StopIteration:
        raise ValueError("规则 Excel 不能为空。") from None

    header_map = _build_header_map(headers)
    current_level1 = ""
    current_level2 = ""
    current_level3 = ""
    rules: list[CategoryRule] = []

    for row in rows:
        level1 = _cell_to_text(_row_value(row, header_map["level1"])) or current_level1
        level2 = _cell_to_text(_row_value(row, header_map["level2"])) or current_level2
        level3 = _cell_to_text(_row_value(row, header_map["level3"])) or current_level3
        module = _cell_to_text(_row_value(row, header_map["module"]))
        keyword_text = _cell_to_text(_row_value(row, header_map["keywords"]))

        if level1:
            current_level1 = level1
        if level2:
            current_level2 = level2
        if level3:
            current_level3 = level3

        if not current_level1 or not current_level2 or not current_level3:
            continue

        if not module and not keyword_text:
            continue

        keywords = _build_keywords(
            level1=current_level1,
            level2=current_level2,
            level3=current_level3,
            module=module,
            keyword_text=keyword_text,
        )
        rules.append(
            CategoryRule(
                level1=current_level1,
                level2=current_level2,
                level3=current_level3,
                module=module or "未分组",
                keywords=keywords,
            )
        )

    if not rules:
        raise ValueError("规则 Excel 没有转换出任何有效规则。")

    return rules


def write_category_rules_json(rules: list[CategoryRule], output_file: str | Path) -> Path:
    """把 CategoryRule 列表写入 JSON 文件。"""
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps([rule.model_dump(mode="json") for rule in rules], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def find_default_input_file() -> Path:
    """寻找默认的内部分类规则 Excel。"""
    for candidate in DEFAULT_INPUT_CANDIDATES:
        if candidate.exists():
            return candidate

    searched = "、".join(str(path) for path in DEFAULT_INPUT_CANDIDATES)
    raise FileNotFoundError(f"未找到默认规则 Excel，请使用 --input 指定文件。已查找：{searched}")


def backup_demo_rules(source_file: Path = DEFAULT_OUTPUT_FILE, backup_file: Path = DEMO_RULE_FILE) -> None:
    """首次转换前备份 demo 规则，避免样例评测没有稳定规则文件。"""
    if backup_file.exists() or not source_file.exists():
        return

    backup_file.write_text(source_file.read_text(encoding="utf-8"), encoding="utf-8")


def _build_header_map(headers: list[str]) -> dict[str, int]:
    """根据表头别名构建列索引。"""
    normalized_headers = {_normalize_header(header): index for index, header in enumerate(headers) if header}
    header_map = {}

    for field_name, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            index = normalized_headers.get(_normalize_header(alias))
            if index is not None:
                header_map[field_name] = index
                break

    missing_fields = [field_name for field_name in HEADER_ALIASES if field_name not in header_map]
    if missing_fields:
        raise ValueError(f"规则 Excel 缺少必要表头：{', '.join(missing_fields)}")

    return header_map


def _build_keywords(level1: str, level2: str, level3: str, module: str, keyword_text: str) -> list[str]:
    """生成去重后的关键词列表。"""
    keywords = [level1, level2, level3, module]
    keywords.extend(
        keyword.strip()
        for keyword in KEYWORD_SPLIT_PATTERN.split(keyword_text)
        if keyword.strip()
    )
    return _dedupe([keyword for keyword in keywords if keyword])


def _dedupe(values: list[str]) -> list[str]:
    """按原顺序去重。"""
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _row_value(row: tuple[Any, ...], index: int) -> Any:
    """安全读取某一列的值。"""
    if index >= len(row):
        return ""
    return row[index]


def _cell_to_text(value: Any) -> str:
    """把单元格值转换成字符串。"""
    if value is None:
        return ""
    return str(value).strip()


def _normalize_header(value: str) -> str:
    """标准化表头，降低空格差异带来的影响。"""
    return re.sub(r"\s+", "", value).lower()


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="把内部分类规则 Excel 转换为 category_rules.json。")
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="规则 Excel 路径，默认读取桌面 document/最终分类表.xlsx。",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_FILE, help="输出 JSON 路径。")
    parser.add_argument("--sheet", default=None, help="要读取的 sheet 名称，默认读取第一个 sheet。")
    args = parser.parse_args()

    input_file = args.input or find_default_input_file()
    backup_demo_rules()
    rules = convert_category_rules_excel(input_file=input_file, sheet_name=args.sheet)
    output_file = write_category_rules_json(rules=rules, output_file=args.output)

    print(f"已生成规则 JSON：{output_file}")
    print(f"规则数量：{len(rules)}")


if __name__ == "__main__":
    main()
