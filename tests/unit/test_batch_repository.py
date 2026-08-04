from app.infrastructure.batch_repository import (
    AuditBatchRecord,
    complete_review_task,
    get_batch_record,
    list_agent_assessment_payloads,
    list_batch_records,
    list_case_payloads,
    list_decision_payloads,
    list_evidence_package_payloads,
    list_review_audit_log_payloads,
    list_review_task_payloads,
    new_created_at,
    save_batch_details,
    save_batch_record,
)


def test_save_and_get_batch_record(tmp_path):
    """应该能保存并查询审批批次记录。"""
    database_path = tmp_path / "audit_agent.db"
    record = _build_record("batch_001")

    save_batch_record(database_path, record)

    saved_record = get_batch_record(database_path, "batch_001")

    assert saved_record is not None
    assert saved_record.batch_id == "batch_001"
    assert saved_record.trace_id == "trace_001"
    assert saved_record.review_task_count == 4


def test_list_batch_records_returns_recent_records(tmp_path):
    """应该能查询最近审批批次记录。"""
    database_path = tmp_path / "audit_agent.db"

    save_batch_record(database_path, _build_record("batch_001"))
    save_batch_record(database_path, _build_record("batch_002"))

    records = list_batch_records(database_path, limit=10)

    assert len(records) == 2
    assert {record.batch_id for record in records} == {"batch_001", "batch_002"}


def test_batch_queries_can_filter_by_tenant(tmp_path):
    """按租户查询时，不能返回其他租户的批次。"""
    database_path = tmp_path / "audit_agent.db"

    save_batch_record(database_path, _build_record("batch_a", tenant_id="tenant_a"))
    save_batch_record(database_path, _build_record("batch_b", tenant_id="tenant_b"))

    records = list_batch_records(database_path, limit=10, tenant_id="tenant_a")
    hidden_record = get_batch_record(database_path, "batch_b", tenant_id="tenant_a")

    assert [record.batch_id for record in records] == ["batch_a"]
    assert hidden_record is None


def test_get_batch_record_returns_none_when_missing(tmp_path):
    """查询不存在的批次时，应该返回 None。"""
    database_path = tmp_path / "audit_agent.db"

    record = get_batch_record(database_path, "missing_batch")

    assert record is None


def test_save_batch_details_persists_cases_decisions_tasks_and_assessments(tmp_path):
    """应该能保存并查询批次明细数据。"""
    database_path = tmp_path / "audit_agent.db"

    save_batch_details(
        database_path=database_path,
        batch_id="batch_001",
        cases=[{"case_id": "case_001", "company_name": "Acme"}],
        decisions=[{"case_id": "case_001", "action": "needs_human_review"}],
        review_tasks=[{"task_id": "review_case_001", "case_id": "case_001", "status": "pending"}],
        assessments={
            "case_001": [
                {"agent_name": "evidence_agent", "status": "success"},
                {"agent_name": "rule_agent", "status": "success"},
            ]
        },
        evidence_packages={
            "case_001": {
                "case_id": "case_001",
                "company_name": "Acme",
                "sources": ["website"],
                "business_scope": "软件开发服务",
                "snippets": [],
                "quality_score": 80,
                "errors": [],
            }
        },
    )

    assert len(list_case_payloads(database_path, "batch_001")) == 1
    assert len(list_decision_payloads(database_path, "batch_001")) == 1
    assert len(list_review_task_payloads(database_path, status="pending")) == 1
    saved_evidence = list_evidence_package_payloads(database_path, "batch_001")
    assert len(saved_evidence) == 1
    assert saved_evidence[0]["business_scope"] == "软件开发服务"
    saved_assessments = list_agent_assessment_payloads(database_path, "batch_001", "case_001")
    assert len(saved_assessments) == 2
    assert saved_assessments[0]["batch_id"] == "batch_001"
    assert saved_assessments[0]["case_id"] == "case_001"


def test_complete_review_task_records_manual_decision_time(tmp_path):
    """提交人工复核结论时，应该记录审核人、最终动作和审核时间。"""
    database_path = tmp_path / "audit_agent.db"
    save_batch_record(database_path, _build_record("batch_001"))
    save_batch_details(
        database_path=database_path,
        batch_id="batch_001",
        cases=[{"case_id": "case_001", "company_name": "Acme"}],
        decisions=[{"case_id": "case_001", "action": "needs_human_review"}],
        review_tasks=[{"task_id": "review_case_001", "case_id": "case_001", "status": "pending"}],
        assessments={},
    )

    task = complete_review_task(
        database_path=database_path,
        task_id="review_case_001",
        reviewer="audit_user",
        final_action="approved",
    )

    assert task is not None
    assert task["status"] == "completed"
    assert task["reviewer"] == "audit_user"
    assert task["final_action"] == "approved"
    assert task["reviewed_at"]

    decisions = list_decision_payloads(database_path, "batch_001")
    assert decisions[0]["manual_final_action"] == "approved"
    assert decisions[0]["manual_reviewer"] == "audit_user"
    assert decisions[0]["manual_reviewed_at"] == task["reviewed_at"]

    record = get_batch_record(database_path, "batch_001")
    assert record is not None
    assert record.result_dirty is True

    logs = list_review_audit_log_payloads(database_path, case_id="case_001")
    assert len(logs) == 1
    assert logs[0]["old_action"] == "needs_human_review"
    assert logs[0]["new_action"] == "approved"
    assert logs[0]["reviewer"] == "audit_user"


def test_review_task_queries_and_submit_can_filter_by_tenant(tmp_path):
    """复核任务查询和提交都应该受租户边界限制。"""
    database_path = tmp_path / "audit_agent.db"
    save_batch_record(database_path, _build_record("batch_a", tenant_id="tenant_a"))
    save_batch_record(database_path, _build_record("batch_b", tenant_id="tenant_b"))
    save_batch_details(
        database_path=database_path,
        batch_id="batch_a",
        tenant_id="tenant_a",
        cases=[{"case_id": "case_a", "company_name": "Acme A"}],
        decisions=[{"case_id": "case_a", "action": "needs_human_review"}],
        review_tasks=[{"task_id": "review_case_a", "case_id": "case_a", "status": "pending"}],
        assessments={},
    )
    save_batch_details(
        database_path=database_path,
        batch_id="batch_b",
        tenant_id="tenant_b",
        cases=[{"case_id": "case_b", "company_name": "Acme B"}],
        decisions=[{"case_id": "case_b", "action": "needs_human_review"}],
        review_tasks=[{"task_id": "review_case_b", "case_id": "case_b", "status": "pending"}],
        assessments={},
    )

    tenant_tasks = list_review_task_payloads(database_path, tenant_id="tenant_a")
    forbidden_task = complete_review_task(
        database_path=database_path,
        task_id="review_case_b",
        reviewer="reviewer_a",
        final_action="approved",
        tenant_id="tenant_a",
    )

    assert [task["task_id"] for task in tenant_tasks] == ["review_case_a"]
    assert forbidden_task is None


def _build_record(batch_id: str, tenant_id: str = "default") -> AuditBatchRecord:
    """构造测试批次记录。"""
    return AuditBatchRecord(
        batch_id=batch_id,
        tenant_id=tenant_id,
        trace_id="trace_001",
        input_file="storage/uploads/input.xlsx",
        result_file="storage/outputs/result.xlsx",
        case_count=10,
        decision_count=10,
        review_task_count=4,
        auto_handled_count=6,
        review_count=4,
        auto_handled_rate=0.6,
        review_rate=0.4,
        total_duration_ms=123.4,
        created_at=new_created_at(),
    )
