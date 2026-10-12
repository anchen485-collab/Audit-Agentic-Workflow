from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from typing import Any

from app.agents.classification_agent import ClassificationAgent
from app.agents.decision_agent import DecisionAgent
from app.agents.decision_verifier import DecisionVerifier
from app.agents.evidence_agent import EvidenceAgent
from app.agents.explanation_agent import ExplanationAgent
from app.agents.llm_classification_provider import MockClassificationProvider
from app.agents.risk_agent import RiskAgent
from app.agents.rule_agent import RuleAgent
from app.domain.models import AgentAssessment
from app.observability.logging import get_audit_logger
from app.observability.metrics import calculate_audit_metrics
from app.observability.trace import new_trace_id, run_with_trace
from app.services.review_service import create_review_tasks
from app.services.rule_retriever import RuleRecallConfig
from app.workflow.state import AuditWorkflowState

logger = get_audit_logger("workflow.nodes")


def init_trace_node(state: AuditWorkflowState) -> dict[str, Any]:
    """初始化 trace_id，避免并行节点同时写入 trace_id。"""
    return {"trace_id": _trace_id(state)}


def collect_evidence_node(state: AuditWorkflowState) -> dict[str, Any]:
    """执行 Evidence Agent，为每条审批单采集外部证据。"""

    def execute() -> dict[str, Any]:
        agent = EvidenceAgent(provider=state["evidence_provider"])
        evidence_packages = {}
        assessments = {}
        max_workers = _concurrency(state, "evidence_concurrency", 5)
        start_time = perf_counter()

        results = _run_cases_parallel(
            cases=state["cases"],
            max_workers=max_workers,
            worker=agent.run,
        )

        for audit_case, result in results:
            evidence_packages[audit_case.case_id] = result.value
            assessments[audit_case.case_id] = [result.assessment]

        _log_batch_stage_complete(
            stage_name="爬虫批量采集完成",
            case_count=len(state["cases"]),
            max_workers=max_workers,
            wall_duration_ms=_elapsed_ms(start_time),
            assessments=assessments,
        )

        return {
            "evidence_packages": evidence_packages,
            "assessments": assessments,
        }

    return _run_node(state, "evidence_agent", execute)


def retrieve_rules_node(state: AuditWorkflowState) -> dict[str, Any]:
    """执行 Rule Agent，为每条审批单召回候选规则。"""

    def execute() -> dict[str, Any]:
        rule_sets = {}
        assessments = {}

        agent = RuleAgent(rules=state["rules"], config=_rule_recall_config(state))
        results = _run_cases_parallel(
            cases=state["cases"],
            max_workers=_concurrency(state, "rule_concurrency", 8),
            worker=agent.run,
        )

        for audit_case, result in results:
            rule_sets[audit_case.case_id] = result.value
            assessments[audit_case.case_id] = [result.assessment]

        return {
            "rule_sets": rule_sets,
            "assessments": assessments,
        }

    return _run_node(state, "rule_agent", execute)


def classify_semantics_node(state: AuditWorkflowState) -> dict[str, Any]:
    """执行 Classification Agent，判断外部证据是否支持员工录入。"""

    def execute() -> dict[str, Any]:
        classification_provider = state.get("classification_provider") or MockClassificationProvider()
        agent = ClassificationAgent(provider=classification_provider)
        classification_results = {}
        assessments = {}
        max_workers = _concurrency(state, "classification_concurrency", 3)
        start_time = perf_counter()

        def classify_case(audit_case):
            return agent.run(
                audit_case=audit_case,
                evidence=state["evidence_packages"][audit_case.case_id],
                candidate_rules=state["rule_sets"][audit_case.case_id],
            )

        results = _run_cases_parallel(
            cases=state["cases"],
            max_workers=max_workers,
            worker=classify_case,
        )

        for audit_case, result in results:
            classification_results[audit_case.case_id] = result.value
            assessments[audit_case.case_id] = [result.assessment]

        _log_batch_stage_complete(
            stage_name="Classification Agent 批量分析完成",
            case_count=len(state["cases"]),
            max_workers=max_workers,
            wall_duration_ms=_elapsed_ms(start_time),
            assessments=assessments,
        )

        return {
            "classification_results": classification_results,
            "assessments": assessments,
        }

    return _run_node(state, "classification_agent", execute)


def assess_risk_node(state: AuditWorkflowState) -> dict[str, Any]:
    """执行 Risk Agent，对每条审批单做风险分层。"""

    def execute() -> dict[str, Any]:
        agent = RiskAgent()
        risk_assessments = {}
        assessments = {}

        def assess_case(audit_case):
            return agent.run(
                audit_case=audit_case,
                evidence=state["evidence_packages"][audit_case.case_id],
                candidate_rules=state["rule_sets"][audit_case.case_id],
                classification_result=state["classification_results"][audit_case.case_id],
            )

        results = _run_cases_parallel(
            cases=state["cases"],
            max_workers=_concurrency(state, "lightweight_agent_concurrency", 8),
            worker=assess_case,
        )

        for audit_case, result in results:
            risk_assessments[audit_case.case_id] = result.value
            assessments[audit_case.case_id] = [result.assessment]

        return {
            "risk_assessments": risk_assessments,
            "assessments": assessments,
        }

    return _run_node(state, "risk_agent", execute)


def decide_action_node(state: AuditWorkflowState) -> dict[str, Any]:
    """执行 Decision Agent，生成最终审批结论。"""

    def execute() -> dict[str, Any]:
        agent = DecisionAgent()
        decisions = []
        assessments = {}

        def decide_case(audit_case):
            return agent.run(
                audit_case=audit_case,
                evidence=state["evidence_packages"][audit_case.case_id],
                candidate_rules=state["rule_sets"][audit_case.case_id],
                classification_result=state["classification_results"][audit_case.case_id],
                risk_assessment=state["risk_assessments"][audit_case.case_id],
            )

        results = _run_cases_parallel(
            cases=state["cases"],
            max_workers=_concurrency(state, "lightweight_agent_concurrency", 8),
            worker=decide_case,
        )

        for audit_case, result in results:
            decisions.append(result.value)
            assessments[audit_case.case_id] = [result.assessment]

        return {
            "decisions": decisions,
            "assessments": assessments,
        }

    return _run_node(state, "decision_agent", execute)


def verify_decisions_node(state: AuditWorkflowState) -> dict[str, Any]:
    """校验自动审批结论；校验失败的记录转入人工复核。"""

    def execute() -> dict[str, Any]:
        agent = DecisionVerifier()
        decisions_by_case_id = {decision.case_id: decision for decision in state["decisions"]}
        assessments = {}

        def verify_case(audit_case):
            return agent.run(
                audit_case=audit_case,
                evidence=state["evidence_packages"][audit_case.case_id],
                candidate_rules=state["rule_sets"][audit_case.case_id],
                classification_result=state["classification_results"][audit_case.case_id],
                risk_assessment=state["risk_assessments"][audit_case.case_id],
                decision=decisions_by_case_id[audit_case.case_id],
            )

        results = _run_cases_parallel(
            cases=state["cases"],
            max_workers=_concurrency(state, "lightweight_agent_concurrency", 8),
            worker=verify_case,
        )

        verified_decisions = []
        for audit_case, result in results:
            verified_decisions.append(result.value)
            assessments[audit_case.case_id] = [result.assessment]

        return {
            "decisions": verified_decisions,
            "assessments": assessments,
        }

    return _run_node(state, "decision_verifier", execute)


def explain_decisions_node(state: AuditWorkflowState) -> dict[str, Any]:
    """执行 Explanation Agent，生成审核员说明和员工反馈。"""

    def execute() -> dict[str, Any]:
        agent = ExplanationAgent()
        explanations = {}
        assessments = {}

        decisions_by_case_id = {decision.case_id: decision for decision in state["decisions"]}

        def explain_case(audit_case):
            return agent.run(audit_case=audit_case, decision=decisions_by_case_id[audit_case.case_id])

        results = _run_cases_parallel(
            cases=state["cases"],
            max_workers=_concurrency(state, "lightweight_agent_concurrency", 8),
            worker=explain_case,
        )

        for audit_case, result in results:
            decision = decisions_by_case_id[audit_case.case_id]
            explanations[decision.case_id] = result.value
            assessments[decision.case_id] = [result.assessment]

        return {
            "explanations": explanations,
            "assessments": assessments,
        }

    return _run_node(state, "explanation_agent", execute)


def create_review_tasks_node(state: AuditWorkflowState) -> dict[str, Any]:
    """根据审批结论生成需要人工处理的复核任务。"""

    def execute() -> dict[str, Any]:
        return {
            "review_tasks": create_review_tasks(state["decisions"]),
        }

    return _run_node(state, "create_review_tasks", execute)


def build_metrics_node(state: AuditWorkflowState) -> dict[str, Any]:
    """汇总审批工作流指标。"""

    def execute() -> dict[str, Any]:
        return {
            "metrics": calculate_audit_metrics(
                decisions=state["decisions"],
                review_tasks=state["review_tasks"],
                assessments=state.get("assessments", {}),
                trace_events=state.get("trace_events", []),
                expected_actions=state.get("expected_actions"),
            ),
        }

    return _run_node(state, "build_metrics", execute)


def _run_node(state: AuditWorkflowState, node_name: str, func) -> dict[str, Any]:
    """用 TraceEvent 包装一个 LangGraph 节点。"""
    trace_id = _trace_id(state)
    logger.info("工作流节点开始: trace_id=%s node=%s", trace_id, node_name)

    result, event = run_with_trace(
        trace_id=trace_id,
        node_name=node_name,
        func=func,
    )
    logger.info(
        "工作流节点完成: trace_id=%s node=%s status=%s duration_ms=%.3f",
        trace_id,
        node_name,
        event.status,
        event.duration_ms,
    )

    return {
        **result,
        "trace_events": [event],
    }


def _trace_id(state: AuditWorkflowState) -> str:
    """兼容旧测试：调用方不传 trace_id 时自动生成。"""
    return state.get("trace_id") or new_trace_id()


def _log_batch_stage_complete(
    stage_name: str,
    case_count: int,
    max_workers: int,
    wall_duration_ms: float,
    assessments: dict[str, list[AgentAssessment]],
) -> None:
    """输出批量阶段耗时，方便在终端判断慢在爬虫还是 Agent 分析。"""
    agent_duration_ms = round(
        sum(assessment.duration_ms for case_assessments in assessments.values() for assessment in case_assessments),
        3,
    )
    logger.info(
        "%s: case_count=%s max_workers=%s wall_duration_ms=%.3f agent_duration_ms=%.3f",
        stage_name,
        case_count,
        min(max_workers, max(case_count, 1)),
        wall_duration_ms,
        agent_duration_ms,
    )


def _run_cases_parallel(cases, max_workers: int, worker: Callable[[Any], Any]) -> list[tuple[Any, Any]]:
    """按 case 并行执行 worker，并保持返回结果顺序和输入 cases 一致。"""
    if not cases:
        return []

    worker_count = max(1, min(max_workers, len(cases)))
    if worker_count == 1:
        return [(audit_case, worker(audit_case)) for audit_case in cases]

    logger.info("批内并行执行开始: case_count=%s max_workers=%s", len(cases), worker_count)
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = list(executor.map(lambda audit_case: (audit_case, worker(audit_case)), cases))

    logger.info("批内并行执行完成: case_count=%s max_workers=%s", len(cases), worker_count)
    return results


def _concurrency(state: AuditWorkflowState, key: str, default: int) -> int:
    """从工作流状态读取并发数，非法值自动回退。"""
    raw_value = state.get(key, default)
    try:
        return max(1, int(raw_value))
    except (TypeError, ValueError):
        return default


def _rule_recall_config(state: AuditWorkflowState) -> RuleRecallConfig:
    """从工作流状态读取规则召回配置，非法值自动回退默认值。"""
    return RuleRecallConfig(
        default_top_k=_bounded_int(state.get("rule_recall_default_top_k"), default=5, minimum=1, maximum=12),
        max_top_k=_bounded_int(state.get("rule_recall_max_top_k"), default=8, minimum=1, maximum=12),
        exact_match_score_threshold=_bounded_int(
            state.get("rule_recall_exact_match_score_threshold"),
            default=7,
            minimum=1,
            maximum=30,
        ),
    )


def _bounded_int(raw_value: Any, default: int, minimum: int, maximum: int) -> int:
    """把配置值限制在安全范围内，避免错误配置扩大 prompt。"""
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default

    return min(max(value, minimum), maximum)


def _elapsed_ms(start_time: float) -> float:
    """计算从 start_time 到当前时间的毫秒耗时。"""
    return round((perf_counter() - start_time) * 1000, 3)


def assessment_names(assessments: dict[str, list[AgentAssessment]], case_id: str) -> list[str]:
    """测试和 demo 使用：提取某条 case 的 Agent 名称列表。"""
    return [assessment.agent_name for assessment in assessments.get(case_id, [])]
