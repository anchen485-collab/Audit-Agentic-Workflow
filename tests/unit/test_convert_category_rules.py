import json

from openpyxl import Workbook

from scripts.convert_category_rules import convert_category_rules_excel, write_category_rules_json


def test_convert_category_rules_excel_fills_blank_category_cells(tmp_path):
    """规则 Excel 中空白分类列应该沿用上一条有效分类。"""
    input_file = tmp_path / "rules.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["一级品类", "二级品类", "三级品类", "模块名称", "子模块列表"])
    sheet.append(["电力", "发电工程", "光热", "环节", "经营、咨询、规划"])
    sheet.append([None, None, None, "生态", "网站、会展"])
    sheet.append([None, None, "水电", "发电方式", "堤坝式水电站、抽水蓄能水电站"])
    workbook.save(input_file)

    rules = convert_category_rules_excel(input_file)

    assert len(rules) == 3
    assert rules[1].level1 == "电力"
    assert rules[1].level2 == "发电工程"
    assert rules[1].level3 == "光热"
    assert rules[1].module == "生态"
    assert "会展" in rules[1].keywords
    assert rules[2].level3 == "水电"


def test_write_category_rules_json_outputs_valid_json(tmp_path):
    """转换后的规则应该能写成合法 JSON。"""
    input_file = tmp_path / "rules.xlsx"
    output_file = tmp_path / "category_rules.json"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["一级品类", "二级品类", "三级品类", "模块名称", "子模块列表"])
    sheet.append(["电力", "发电工程", "光热", "环节", "经营、咨询"])
    workbook.save(input_file)

    rules = convert_category_rules_excel(input_file)
    write_category_rules_json(rules, output_file)

    raw_rules = json.loads(output_file.read_text(encoding="utf-8"))
    assert raw_rules[0]["level1"] == "电力"
    assert raw_rules[0]["level3"] == "光热"
    assert "经营" in raw_rules[0]["keywords"]
