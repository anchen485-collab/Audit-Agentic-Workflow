import json
from pathlib import Path

from app.infrastructure.evidence_provider import MockCompanyEvidenceProvider
from app.infrastructure.rule_repository import load_category_rules
from app.workflow.audit_workflow import build_audit_workflow

try:
    from scripts.run_eval import DEFAULT_EVIDENCE_FILE, DEFAULT_RULES_FILE, _build_audit_cases
except ModuleNotFoundError:
    from run_eval import DEFAULT_EVIDENCE_FILE, DEFAULT_RULES_FILE, _build_audit_cases

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_CASES_FILE = PROJECT_ROOT / "tests" / "fixtures" / "sample_cases.json"


def main() -> None:
    """打印一条样例的多 Agent trace，方便演示完整链路。"""
    raw_cases = json.loads(SAMPLE_CASES_FILE.read_text(encoding="utf-8"))[:1]
    audit_cases = _build_audit_cases(raw_cases)

    result = build_audit_workflow().invoke(
        {
            "cases": audit_cases,
            "rules": load_category_rules(DEFAULT_RULES_FILE),
            "evidence_provider": MockCompanyEvidenceProvider(DEFAULT_EVIDENCE_FILE),
            "expected_actions": {
                item["case_id"]: item["expected_action"]
                for item in raw_cases
            },
        }
    )

    case_id = audit_cases[0].case_id
    print(f"case_id: {case_id}")
    print("trace events:")
    for event in result["trace_events"]:
        print(f"- {event.node_name} | {event.status} | {event.duration_ms}ms")

    print("agent assessments:")
    for assessment in result["assessments"][case_id]:
        print(f"- {assessment.agent_name} | {assessment.status} | confidence={assessment.confidence}")

    print("decision:")
    print(result["decisions"][0].model_dump_json(indent=2))


if __name__ == "__main__":
    main()
