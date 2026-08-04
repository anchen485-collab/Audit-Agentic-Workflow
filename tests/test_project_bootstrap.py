from pathlib import Path


def test_day2_sample_cases_exist():
    """确认 Day 2 的样例数据已经放在新项目中。"""
    sample_cases_path = Path("tests/fixtures/sample_cases.json")

    assert sample_cases_path.exists()