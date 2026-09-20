from langgraph.graph import END, START, StateGraph

from app.workflow.nodes import (
    assess_risk_node,
    build_metrics_node,
    classify_semantics_node,
    collect_evidence_node,
    create_review_tasks_node,
    decide_action_node,
    explain_decisions_node,
    init_trace_node,
    retrieve_rules_node,
    verify_decisions_node,
)
from app.workflow.state import AuditWorkflowState


def build_audit_workflow():
    """构建多 Agent 审批 LangGraph 工作流。"""
    builder = StateGraph(AuditWorkflowState)

    builder.add_node("init_trace", init_trace_node)
    builder.add_node("evidence_agent", collect_evidence_node)
    builder.add_node("rule_agent", retrieve_rules_node)
    builder.add_node("classification_agent", classify_semantics_node)
    builder.add_node("risk_agent", assess_risk_node)
    builder.add_node("decision_agent", decide_action_node)
    builder.add_node("decision_verifier", verify_decisions_node)
    builder.add_node("explanation_agent", explain_decisions_node)
    builder.add_node("create_review_tasks", create_review_tasks_node)
    builder.add_node("build_metrics", build_metrics_node)

    builder.add_edge(START, "init_trace")
    builder.add_edge("init_trace", "evidence_agent")
    builder.add_edge("init_trace", "rule_agent")
    builder.add_edge("evidence_agent", "classification_agent")
    builder.add_edge("rule_agent", "classification_agent")
    builder.add_edge("classification_agent", "risk_agent")
    builder.add_edge("risk_agent", "decision_agent")
    builder.add_edge("decision_agent", "decision_verifier")
    builder.add_edge("decision_verifier", "explanation_agent")
    builder.add_edge("explanation_agent", "create_review_tasks")
    builder.add_edge("create_review_tasks", "build_metrics")
    builder.add_edge("build_metrics", END)

    return builder.compile()
