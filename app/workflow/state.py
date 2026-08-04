import operator
from typing import Annotated, NotRequired, Protocol, TypedDict

from app.agents.explanation_agent import ExplanationResult
from app.agents.llm_classification_provider import ClassificationProvider, SemanticClassificationResult
from app.agents.risk_agent import RiskAssessment
from app.domain.models import (
    AgentAssessment,
    ApprovalDecision,
    AuditCase,
    CandidateRuleSet,
    CategoryRule,
    EvidencePackage,
    ReviewTask,
)
from app.observability.trace import TraceEvent


class EvidenceProvider(Protocol):
    """证据提供器协议，mock provider 和真实爬虫 provider 都可以实现它。"""

    def fetch(self, case_id: str, company_name: str, website_url: str = "") -> EvidencePackage:
        """获取企业证据包。"""


def merge_assessments(
    left: dict[str, list[AgentAssessment]] | None,
    right: dict[str, list[AgentAssessment]] | None,
) -> dict[str, list[AgentAssessment]]:
    """合并多个 workflow 节点返回的 AgentAssessment。"""
    merged: dict[str, list[AgentAssessment]] = {}

    for source in (left or {}, right or {}):
        for case_id, assessments in source.items():
            merged.setdefault(case_id, []).extend(assessments)

    return merged


class AuditWorkflowState(TypedDict):
    """LangGraph 审批工作流状态。"""

    cases: list[AuditCase]
    rules: list[CategoryRule]
    evidence_provider: EvidenceProvider

    classification_provider: NotRequired[ClassificationProvider]
    expected_actions: NotRequired[dict[str, str]]
    trace_id: NotRequired[str]
    evidence_concurrency: NotRequired[int]
    classification_concurrency: NotRequired[int]
    rule_concurrency: NotRequired[int]
    rule_recall_default_top_k: NotRequired[int]
    rule_recall_max_top_k: NotRequired[int]
    rule_recall_exact_match_score_threshold: NotRequired[int]
    lightweight_agent_concurrency: NotRequired[int]

    rule_sets: NotRequired[dict[str, CandidateRuleSet]]
    evidence_packages: NotRequired[dict[str, EvidencePackage]]
    classification_results: NotRequired[dict[str, SemanticClassificationResult]]
    risk_assessments: NotRequired[dict[str, RiskAssessment]]
    explanations: NotRequired[dict[str, ExplanationResult]]
    decisions: NotRequired[list[ApprovalDecision]]
    review_tasks: NotRequired[list[ReviewTask]]
    metrics: NotRequired[dict[str, float | int]]

    trace_events: Annotated[list[TraceEvent], operator.add]
    assessments: Annotated[dict[str, list[AgentAssessment]], merge_assessments]
