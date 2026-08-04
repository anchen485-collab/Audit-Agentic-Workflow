from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import AgentExecutionResult, run_agent_step
from app.agents.llm_classification_provider import SemanticClassificationResult
from app.domain.models import AuditCase, CandidateRuleSet, EvidencePackage


class RiskLevel(StrEnum):
    """审批风险等级。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskAssessment(BaseModel):
    """Risk Agent 输出的风险评估结果。"""

    case_id: str = Field(description="审批单 ID")
    risk_level: RiskLevel = Field(description="风险等级")
    risk_score: int = Field(ge=0, le=100, description="风险分，越高越不适合自动处理")
    reasons: list[str] = Field(default_factory=list, description="风险原因列表")


class RiskAgent:
    """风险分层 Agent。"""

    agent_name = "risk_agent"

    def run(
        self,
        audit_case: AuditCase,
        evidence: EvidencePackage,
        candidate_rules: CandidateRuleSet,
        classification_result: SemanticClassificationResult,
    ) -> AgentExecutionResult[RiskAssessment]:
        """评估单条审批单的自动处理风险。"""
        fallback_risk = RiskAssessment(
            case_id=audit_case.case_id,
            risk_level=RiskLevel.HIGH,
            risk_score=100,
            reasons=["Risk Agent 执行失败，默认进入高风险。"],
        )

        return run_agent_step(
            agent_name=self.agent_name,
            func=lambda: self._assess(
                audit_case=audit_case,
                evidence=evidence,
                candidate_rules=candidate_rules,
                classification_result=classification_result,
            ),
            fallback_value=fallback_risk,
        )

    def _assess(
        self,
        audit_case: AuditCase,
        evidence: EvidencePackage,
        candidate_rules: CandidateRuleSet,
        classification_result: SemanticClassificationResult,
    ) -> tuple[RiskAssessment, list[str], dict[str, Any], int]:
        """执行风险评分。"""
        risk_score = 0
        reasons: list[str] = []

        if evidence.quality_score < 60:
            risk_score += 70
            reasons.append("证据质量分低于自动审批阈值。")

        if not evidence.business_scope.strip() or not evidence.snippets:
            risk_score += 20
            reasons.append("证据描述或证据片段不完整。")

        if evidence.errors:
            risk_score += 20
            reasons.extend(evidence.errors)

        if not candidate_rules.entered_path_exists:
            risk_score += 80
            reasons.append("员工录入分类不在内部规则库中。")

        if not candidate_rules.candidates:
            risk_score += 30
            reasons.append("没有召回候选规则。")

        if classification_result.confidence < 70:
            risk_score += 35
            reasons.append("语义判断置信度较低。")

        if classification_result.result == "uncertain":
            risk_score += 40
            reasons.append("语义判断结果不确定。")

        if classification_result.result == "insufficient_evidence":
            risk_score += 30
            reasons.append("语义判断认为需要补充证据。")

        risk_score = min(risk_score, 100)
        risk_level = self._risk_level(risk_score)
        risk = RiskAssessment(
            case_id=audit_case.case_id,
            risk_level=risk_level,
            risk_score=risk_score,
            reasons=reasons or ["未发现明显风险。"],
        )

        return risk, risk.reasons, risk.model_dump(mode="json"), 90

    def _risk_level(self, risk_score: int) -> RiskLevel:
        """把风险分转换成风险等级。"""
        if risk_score >= 70:
            return RiskLevel.HIGH

        if risk_score >= 40:
            return RiskLevel.MEDIUM

        return RiskLevel.LOW
