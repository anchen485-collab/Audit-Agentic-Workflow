from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import AgentExecutionResult, run_agent_step
from app.domain.decisions import DecisionAction
from app.domain.models import ApprovalDecision, AuditCase


class ExplanationResult(BaseModel):
    """Explanation Agent 输出的两类解释。"""

    case_id: str = Field(description="审批单 ID")
    internal_reason: str = Field(description="给审核员看的内部说明")
    employee_feedback: str = Field(description="给录入员工看的反馈")


class ExplanationAgent:
    """审批解释 Agent。"""

    agent_name = "explanation_agent"

    def run(
        self,
        audit_case: AuditCase,
        decision: ApprovalDecision,
    ) -> AgentExecutionResult[ExplanationResult]:
        """生成审核员说明和员工反馈。"""
        fallback_explanation = ExplanationResult(
            case_id=audit_case.case_id,
            internal_reason=decision.reason,
            employee_feedback=decision.suggestion or "请等待人工审核结果。",
        )

        return run_agent_step(
            agent_name=self.agent_name,
            func=lambda: self._explain(audit_case, decision),
            fallback_value=fallback_explanation,
        )

    def _explain(
        self,
        audit_case: AuditCase,
        decision: ApprovalDecision,
    ) -> tuple[ExplanationResult, list[str], dict[str, Any], int]:
        """构造可读解释。"""
        internal_reason = (
            f"企业：{audit_case.company_name}；员工录入分类："
            f"{audit_case.entered_level1} / {audit_case.entered_subcategory}；"
            f"审批结论：{decision.action.value}；原因：{decision.reason}"
        )
        employee_feedback = self._employee_feedback(decision)
        explanation = ExplanationResult(
            case_id=audit_case.case_id,
            internal_reason=internal_reason,
            employee_feedback=employee_feedback,
        )
        findings = [internal_reason, employee_feedback]

        return explanation, findings, explanation.model_dump(mode="json"), 85

    def _employee_feedback(self, decision: ApprovalDecision) -> str:
        """根据审批动作生成给录入员工看的反馈。"""
        if decision.action == DecisionAction.APPROVED:
            return "录入分类已通过。"

        if decision.action == DecisionAction.REJECTED:
            return decision.suggestion or "录入分类与外部证据不一致，请修改后重新提交。"

        if decision.action == DecisionAction.NEEDS_MORE_EVIDENCE:
            return decision.suggestion or "企业证据不足，请补充官网或业务说明。"

        return decision.suggestion or "该记录需要人工复核，请等待审核员处理。"
