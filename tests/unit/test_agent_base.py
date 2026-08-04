from app.agents.base import AgentStatus, build_agent_assessment, run_agent_step
from app.domain.errors import LLMInvalidJsonError


def test_build_agent_assessment_success():
    assessment = build_agent_assessment(
        agent_name="evidence_agent",
        status=AgentStatus.SUCCESS,
        confidence=90,
        findings=["采集到官网简介"],
        output={"quality_score": 85},
        duration_ms=12.3456,
    )

    assert assessment.agent_name == "evidence_agent"
    assert assessment.status == "success"
    assert assessment.confidence == 90
    assert assessment.findings == ["采集到官网简介"]
    assert assessment.output["quality_score"] == 85
    assert assessment.duration_ms == 12.346


def test_run_agent_step_success():
    def fake_agent_logic():
        return (
            {"result": "ok"},
            ["完成测试逻辑"],
            {"count": 1},
            88,
        )

    result = run_agent_step(
        agent_name="fake_agent",
        func=fake_agent_logic,
        fallback_value={},
    )

    assert result.value == {"result": "ok"}
    assert result.assessment.status == "success"
    assert result.assessment.confidence == 88
    assert result.assessment.duration_ms >= 0


def test_run_agent_step_failed_returns_fallback():
    def broken_agent_logic():
        raise RuntimeError("测试异常")

    result = run_agent_step(
        agent_name="broken_agent",
        func=broken_agent_logic,
        fallback_value={"fallback": True},
    )

    assert result.value == {"fallback": True}
    assert result.assessment.status == "failed"
    assert result.assessment.confidence == 0
    assert "测试异常" in result.assessment.output["error"]
    assert result.assessment.output["error_code"] == "RuntimeError"


def test_run_agent_step_failed_records_structured_audit_error():
    """Agent 失败时应该记录结构化错误类型，方便导出和统计。"""

    def broken_agent_logic():
        raise LLMInvalidJsonError("LLM 输出无法解析为审批 JSON：bad json")

    result = run_agent_step(
        agent_name="classification_agent",
        func=broken_agent_logic,
        fallback_value={"fallback": True},
    )

    assert result.assessment.status == "failed"
    assert result.assessment.output["error_code"] == "llm_invalid_json"
    assert "JSON 输出约束" in result.assessment.output["suggestion"]
