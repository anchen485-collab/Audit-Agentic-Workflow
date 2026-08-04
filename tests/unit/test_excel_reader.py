import pytest
from openpyxl import Workbook

from app.infrastructure.excel_reader import MissingExcelHeaderError, parse_company_field, read_audit_excel


def create_excel_file(path, rows):
    """创建测试用 Excel 文件。"""
    workbook = Workbook()
    sheet = workbook.active

    for row in rows:
        sheet.append(row)

    workbook.save(path)


def test_read_audit_excel_reads_valid_rows(tmp_path):
    """读取合法 Excel 时，应该返回结构化行数据。"""
    file_path = tmp_path / "audit.xlsx"
    create_excel_file(
        file_path,
        [
            ["日期", "姓名", "一级分类", "细分", "企业名称&官网"],
            ["2026-07-25", "张三", "信软技术服务", "软件开发", "杭州云启软件有限公司 https://example.com"],
            ["2026-07-25", "李四", "农业", "种植业", "黑龙江丰禾农业发展有限公司"],
        ],
    )

    rows = read_audit_excel(file_path)

    assert len(rows) == 2
    assert rows[0].row_number == 2
    assert rows[0].employee_name == "张三"
    assert rows[0].company_name == "杭州云启软件有限公司"
    assert rows[0].website_url == "https://example.com"
    assert rows[1].company_name == "黑龙江丰禾农业发展有限公司"
    assert rows[1].website_url == ""


def test_read_audit_excel_reads_hidden_cell_hyperlink(tmp_path):
    """企业官网写在单元格超链接里时，也应该读取到 website_url。"""
    file_path = tmp_path / "audit.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["日期", "姓名", "一级分类", "细分", "企业名称&官网"])
    sheet.append(["2026-07-25", "张三", "渔业", "淡水捕捞", "Archipelago Marine Research Ltd"])
    company_cell = sheet["E2"]
    company_cell.hyperlink = "https://www.archipelago.ca/"
    workbook.save(file_path)

    rows = read_audit_excel(file_path)

    assert rows[0].company_name == "Archipelago Marine Research Ltd"
    assert rows[0].website_url == "https://www.archipelago.ca/"


def test_read_audit_excel_reads_optional_level2_column(tmp_path):
    """Excel 有二级分类列时，应该读取员工录入的二级分类。"""
    file_path = tmp_path / "audit.xlsx"
    create_excel_file(
        file_path,
        [
            ["日期", "姓名", "一级分类", "二级分类", "细分", "企业名称&官网"],
            ["2026-07-25", "张三", "电力", "发电工程", "光热", "光热企业 https://example.com"],
        ],
    )

    rows = read_audit_excel(file_path)

    assert rows[0].entered_level2 == "发电工程"


def test_read_audit_excel_rejects_missing_headers(tmp_path):
    """缺少必要表头时，应该抛出清晰错误。"""
    file_path = tmp_path / "bad.xlsx"
    create_excel_file(
        file_path,
        [
            ["日期", "姓名", "一级分类", "企业名称&官网"],
            ["2026-07-25", "张三", "信软技术服务", "杭州云启软件有限公司"],
        ],
    )

    with pytest.raises(MissingExcelHeaderError) as error:
        read_audit_excel(file_path)

    assert "细分" in str(error.value)


def test_read_audit_excel_skips_empty_rows(tmp_path):
    """完全空白的行应该跳过。"""
    file_path = tmp_path / "empty_rows.xlsx"
    create_excel_file(
        file_path,
        [
            ["日期", "姓名", "一级分类", "细分", "企业名称&官网"],
            [None, None, None, None, None],
            ["2026-07-25", "张三", "信软技术服务", "软件开发", "杭州云启软件有限公司"],
        ],
    )

    rows = read_audit_excel(file_path)

    assert len(rows) == 1
    assert rows[0].row_number == 3


def test_parse_company_field_extracts_url():
    """企业字段中带 URL 时，应该拆出企业名和官网。"""
    company_name, website_url = parse_company_field("杭州云启软件有限公司 https://example.com/about")

    assert company_name == "杭州云启软件有限公司"
    assert website_url == "https://example.com/about"


def test_parse_company_field_supports_www_url():
    """企业字段中只有 www 开头的网址时，也应该能识别。"""
    company_name, website_url = parse_company_field("杭州云启软件有限公司 www.example.com")

    assert company_name == "杭州云启软件有限公司"
    assert website_url == "https://www.example.com"
