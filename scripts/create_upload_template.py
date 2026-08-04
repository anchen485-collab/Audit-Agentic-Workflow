from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

DEFAULT_TEMPLATE_FILE = Path("data/templates/audit_upload_template.xlsx")


def create_upload_template(output_file: str | Path = DEFAULT_TEMPLATE_FILE) -> Path:
    """创建员工录入 Excel 模板。"""
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "员工录入"

    headers = ["日期", "姓名", "一级分类", "二级分类", "细分", "企业名称&官网"]
    sheet.append(headers)
    sheet.append(
        [
            "2026-07-29",
            "张三",
            "电力",
            "发电工程",
            "光热",
            "示例企业有限公司 https://example.com",
        ]
    )

    for cell in sheet[1]:
        cell.font = Font(bold=True)

    sheet.column_dimensions["A"].width = 14
    sheet.column_dimensions["B"].width = 12
    sheet.column_dimensions["C"].width = 18
    sheet.column_dimensions["D"].width = 18
    sheet.column_dimensions["E"].width = 18
    sheet.column_dimensions["F"].width = 56

    workbook.save(output_path)
    return output_path


def main() -> None:
    """命令行入口。"""
    output_path = create_upload_template()
    print(f"已生成上传模板：{output_path}")


if __name__ == "__main__":
    main()
