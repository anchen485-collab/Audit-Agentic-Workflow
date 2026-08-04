import json
from copy import deepcopy
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_CASES_FILE = PROJECT_ROOT / "tests" / "fixtures" / "sample_cases.json"
GOLDEN_CASES_FILE = PROJECT_ROOT / "evals" / "golden_cases.json"


def build_golden_cases() -> list[dict]:
    """基于 10 条标准样例扩展出 30 条 golden cases。"""
    sample_cases = json.loads(SAMPLE_CASES_FILE.read_text(encoding="utf-8"))
    groups = {
        "approved": [item for item in sample_cases if item["expected_action"] == "approved"],
        "rejected": [item for item in sample_cases if item["expected_action"] == "rejected"],
        "needs_more_evidence": [
            item for item in sample_cases if item["expected_action"] == "needs_more_evidence"
        ],
        "needs_human_review": [
            item for item in sample_cases if item["expected_action"] == "needs_human_review"
        ],
    }
    targets = {
        "approved": 10,
        "rejected": 10,
        "needs_more_evidence": 5,
        "needs_human_review": 5,
    }
    golden_cases = []

    for action, target_count in targets.items():
        source_cases = groups[action]
        for index in range(target_count):
            source = deepcopy(source_cases[index % len(source_cases)])
            source["case_id"] = f"golden_{len(golden_cases) + 1:03d}"
            source["source_case_id"] = source_cases[index % len(source_cases)]["case_id"]
            golden_cases.append(source)

    return golden_cases


def main() -> None:
    """生成 evals/golden_cases.json。"""
    GOLDEN_CASES_FILE.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_CASES_FILE.write_text(
        json.dumps(build_golden_cases(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"generated {GOLDEN_CASES_FILE}")


if __name__ == "__main__":
    main()
