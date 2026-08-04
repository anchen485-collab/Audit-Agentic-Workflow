import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.infrastructure.database import connect_database, init_database


@dataclass
class AuditBatchRecord:
    """审批批次持久化记录。"""

    batch_id: str
    tenant_id: str
    trace_id: str
    input_file: str
    result_file: str
    case_count: int
    decision_count: int
    review_task_count: int
    auto_handled_count: int
    review_count: int
    auto_handled_rate: float
    review_rate: float
    total_duration_ms: float
    created_at: str
    result_dirty: bool = False


def save_batch_record(database_path: Path, record: AuditBatchRecord) -> None:
    """保存审批批次记录。"""
    init_database(database_path)

    with connect_database(database_path) as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO audit_batches (
                batch_id,
                tenant_id,
                trace_id,
                input_file,
                result_file,
                case_count,
                decision_count,
                review_task_count,
                auto_handled_count,
                review_count,
                auto_handled_rate,
                review_rate,
                total_duration_ms,
                created_at,
                result_dirty
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.batch_id,
                record.tenant_id,
                record.trace_id,
                record.input_file,
                record.result_file,
                record.case_count,
                record.decision_count,
                record.review_task_count,
                record.auto_handled_count,
                record.review_count,
                record.auto_handled_rate,
                record.review_rate,
                record.total_duration_ms,
                record.created_at,
                int(record.result_dirty),
            ),
        )
        connection.commit()


def get_batch_record(
    database_path: Path,
    batch_id: str,
    tenant_id: str | None = None,
) -> AuditBatchRecord | None:
    """根据 batch_id 查询审批批次记录。"""
    init_database(database_path)

    with connect_database(database_path) as connection:
        where_clause = "batch_id = ?"
        params: tuple[Any, ...] = (batch_id,)
        if tenant_id:
            where_clause = "batch_id = ? AND tenant_id = ?"
            params = (batch_id, tenant_id)

        row = connection.execute(
            f"""
            SELECT *
            FROM audit_batches
            WHERE {where_clause}
            """,
            params,
        ).fetchone()

    if row is None:
        return None

    return _row_to_record(row)


def list_batch_records(
    database_path: Path,
    limit: int = 20,
    tenant_id: str | None = None,
) -> list[AuditBatchRecord]:
    """查询最近的审批批次记录。"""
    init_database(database_path)

    with connect_database(database_path) as connection:
        where_clause = "1 = 1"
        params: tuple[Any, ...] = (limit,)
        if tenant_id:
            where_clause = "tenant_id = ?"
            params = (tenant_id, limit)

        rows = connection.execute(
            f"""
            SELECT *
            FROM audit_batches
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    return [_row_to_record(row) for row in rows]


def save_batch_details(
    database_path: Path,
    batch_id: str,
    cases: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    review_tasks: list[dict[str, Any]],
    assessments: dict[str, list[dict[str, Any]]],
    evidence_packages: dict[str, dict[str, Any]] | None = None,
    tenant_id: str = "default",
) -> None:
    """保存批次下的审批单、审批结论、证据包、复核任务和 AgentAssessment 明细。"""
    init_database(database_path)

    with connect_database(database_path) as connection:
        for case in cases:
            case_payload = {
                **case,
                "tenant_id": tenant_id,
            }
            connection.execute(
                """
                INSERT OR REPLACE INTO audit_cases (case_id, batch_id, tenant_id, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (case["case_id"], batch_id, tenant_id, _to_json(case_payload)),
            )

        for decision in decisions:
            decision_payload = {
                **decision,
                "tenant_id": tenant_id,
            }
            connection.execute(
                """
                INSERT OR REPLACE INTO audit_decisions (case_id, batch_id, tenant_id, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (decision["case_id"], batch_id, tenant_id, _to_json(decision_payload)),
            )

        for task in review_tasks:
            task_payload = {
                **task,
                "batch_id": batch_id,
                "tenant_id": tenant_id,
            }
            connection.execute(
                """
                INSERT OR REPLACE INTO review_tasks (
                    task_id,
                    batch_id,
                    case_id,
                    tenant_id,
                    status,
                    reviewer,
                    final_action,
                    payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task["task_id"],
                    batch_id,
                    task["case_id"],
                    tenant_id,
                    task.get("status", "pending"),
                    task.get("reviewer"),
                    task.get("final_action"),
                    _to_json(task_payload),
                ),
            )

        connection.execute("DELETE FROM evidence_packages WHERE batch_id = ?", (batch_id,))
        for case_id, evidence_payload in (evidence_packages or {}).items():
            evidence_payload_with_tenant = {
                **evidence_payload,
                "tenant_id": tenant_id,
            }
            connection.execute(
                """
                INSERT OR REPLACE INTO evidence_packages (case_id, batch_id, tenant_id, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (case_id, batch_id, tenant_id, _to_json(evidence_payload_with_tenant)),
            )

        connection.execute("DELETE FROM agent_assessments WHERE batch_id = ?", (batch_id,))
        for case_id, case_assessments in assessments.items():
            for assessment in case_assessments:
                assessment_payload = {
                    **assessment,
                    "batch_id": batch_id,
                    "case_id": case_id,
                }
                connection.execute(
                    """
                    INSERT INTO agent_assessments (
                        batch_id,
                        case_id,
                        tenant_id,
                        agent_name,
                        status,
                        duration_ms,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch_id,
                        case_id,
                        tenant_id,
                        assessment["agent_name"],
                        assessment["status"],
                        float(assessment.get("duration_ms", 0.0)),
                        _to_json(assessment_payload),
                    ),
                )

        connection.commit()


def list_case_payloads(database_path: Path, batch_id: str) -> list[dict[str, Any]]:
    """查询某个批次的审批单明细。"""
    return _list_payloads(database_path, "audit_cases", "batch_id = ?", (batch_id,))


def list_decision_payloads(database_path: Path, batch_id: str) -> list[dict[str, Any]]:
    """查询某个批次的审批结论明细。"""
    return _list_payloads(database_path, "audit_decisions", "batch_id = ?", (batch_id,))


def list_review_task_payloads(
    database_path: Path,
    status: str | None = None,
    tenant_id: str | None = None,
) -> list[dict[str, Any]]:
    """查询人工复核任务，可按状态过滤。"""
    filters = []
    params = []
    if status:
        filters.append("status = ?")
        params.append(status)
    if tenant_id:
        filters.append("tenant_id = ?")
        params.append(tenant_id)

    where_clause = " AND ".join(filters) if filters else "1 = 1"
    return _list_payloads(database_path, "review_tasks", where_clause, tuple(params))


def list_review_task_payloads_by_batch(database_path: Path, batch_id: str) -> list[dict[str, Any]]:
    """查询某个批次下的人工复核任务。"""
    return _list_payloads(database_path, "review_tasks", "batch_id = ?", (batch_id,))


def list_evidence_package_payloads(database_path: Path, batch_id: str) -> list[dict[str, Any]]:
    """查询某个批次下的证据包明细。"""
    return _list_payloads(database_path, "evidence_packages", "batch_id = ?", (batch_id,))


def list_agent_assessment_payloads(
    database_path: Path,
    batch_id: str,
    case_id: str | None = None,
) -> list[dict[str, Any]]:
    """查询某个批次或某条审批单的 AgentAssessment。"""
    if case_id:
        return _list_payloads(
            database_path,
            "agent_assessments",
            "batch_id = ? AND case_id = ?",
            (batch_id, case_id),
        )

    return _list_payloads(database_path, "agent_assessments", "batch_id = ?", (batch_id,))


def complete_review_task(
    database_path: Path,
    task_id: str,
    reviewer: str,
    final_action: str,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    """提交人工复核结论，并返回更新后的任务。"""
    init_database(database_path)

    with connect_database(database_path) as connection:
        where_clause = "task_id = ?"
        params: tuple[Any, ...] = (task_id,)
        if tenant_id:
            where_clause = "task_id = ? AND tenant_id = ?"
            params = (task_id, tenant_id)

        row = connection.execute(
            f"SELECT batch_id, tenant_id, payload_json FROM review_tasks WHERE {where_clause}",
            params,
        ).fetchone()

        if row is None:
            return None

        payload = json.loads(row["payload_json"])
        payload["batch_id"] = payload.get("batch_id") or row["batch_id"]
        payload["tenant_id"] = payload.get("tenant_id") or row["tenant_id"]
        old_action = payload.get("final_action") or "needs_human_review"
        payload["status"] = "completed"
        payload["reviewer"] = reviewer
        payload["final_action"] = final_action
        payload["reviewed_at"] = new_created_at()

        decision_row = connection.execute(
            "SELECT payload_json FROM audit_decisions WHERE case_id = ?",
            (payload["case_id"],),
        ).fetchone()
        if decision_row is not None:
            decision_payload = json.loads(decision_row["payload_json"])
            decision_payload["manual_final_action"] = final_action
            decision_payload["manual_reviewer"] = reviewer
            decision_payload["manual_reviewed_at"] = payload["reviewed_at"]
            connection.execute(
                """
                UPDATE audit_decisions
                SET payload_json = ?
                WHERE case_id = ?
                """,
                (_to_json(decision_payload), payload["case_id"]),
            )

        connection.execute(
            """
            UPDATE review_tasks
            SET status = ?, reviewer = ?, final_action = ?, payload_json = ?
            WHERE task_id = ?
            """,
            ("completed", reviewer, final_action, _to_json(payload), task_id),
        )
        connection.execute(
            """
            UPDATE audit_batches
            SET result_dirty = 1
            WHERE batch_id = ?
            """,
            (payload["batch_id"],),
        )
        audit_payload = {
            "batch_id": payload["batch_id"],
            "case_id": payload["case_id"],
            "task_id": task_id,
            "old_action": old_action,
            "new_action": final_action,
            "reviewer": reviewer,
            "reviewed_at": payload["reviewed_at"],
            "tenant_id": payload["tenant_id"],
        }
        connection.execute(
            """
            INSERT INTO review_audit_logs (
                batch_id,
                case_id,
                task_id,
                tenant_id,
                old_action,
                new_action,
                reviewer,
                reviewed_at,
                payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["batch_id"],
                payload["case_id"],
                task_id,
                payload["tenant_id"],
                old_action,
                final_action,
                reviewer,
                payload["reviewed_at"],
                _to_json(audit_payload),
            ),
        )
        connection.commit()

    return payload


def mark_batch_result_clean(database_path: Path, batch_id: str) -> None:
    """结果 Excel 已重建后，把 dirty 标记恢复为干净。"""
    init_database(database_path)

    with connect_database(database_path) as connection:
        connection.execute(
            """
            UPDATE audit_batches
            SET result_dirty = 0
            WHERE batch_id = ?
            """,
            (batch_id,),
        )
        connection.commit()


def record_file_access_audit_log(
    database_path: Path,
    user_id: str,
    tenant_id: str,
    batch_id: str,
    action: str,
    client_ip: str,
    user_agent: str,
) -> dict[str, Any]:
    """记录文件访问审计日志，主要用于结果 Excel 下载追踪。"""
    init_database(database_path)
    payload = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "batch_id": batch_id,
        "action": action,
        "client_ip": client_ip,
        "user_agent": user_agent,
        "created_at": new_created_at(),
    }

    with connect_database(database_path) as connection:
        connection.execute(
            """
            INSERT INTO file_access_audit_logs (
                user_id,
                tenant_id,
                batch_id,
                action,
                client_ip,
                user_agent,
                created_at,
                payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                tenant_id,
                batch_id,
                action,
                client_ip,
                user_agent,
                payload["created_at"],
                _to_json(payload),
            ),
        )
        connection.commit()

    return payload


def list_file_access_audit_log_payloads(database_path: Path) -> list[dict[str, Any]]:
    """查询文件访问审计日志。"""
    return _list_payloads(database_path, "file_access_audit_logs", "1 = 1", ())


def list_review_audit_log_payloads(
    database_path: Path,
    case_id: str | None = None,
) -> list[dict[str, Any]]:
    """查询人工复核审计日志，可按审批单过滤。"""
    if case_id:
        return _list_payloads(database_path, "review_audit_logs", "case_id = ?", (case_id,))

    return _list_payloads(database_path, "review_audit_logs", "1 = 1", ())


def new_created_at() -> str:
    """生成 UTC 时间字符串，方便跨环境排序。"""
    return datetime.now(UTC).isoformat()


def _list_payloads(
    database_path: Path,
    table_name: str,
    where_clause: str,
    params: tuple[Any, ...],
) -> list[dict[str, Any]]:
    """查询某张明细表中的 JSON payload。"""
    init_database(database_path)

    with connect_database(database_path) as connection:
        rows = connection.execute(
            f"SELECT payload_json FROM {table_name} WHERE {where_clause}",
            params,
        ).fetchall()

    return [json.loads(row["payload_json"]) for row in rows]


def _to_json(payload: dict[str, Any]) -> str:
    """统一序列化 JSON，保留中文。"""
    return json.dumps(payload, ensure_ascii=False)


def _row_to_record(row) -> AuditBatchRecord:
    """把 SQLite row 转成 AuditBatchRecord。"""
    return AuditBatchRecord(
        batch_id=row["batch_id"],
        tenant_id=row["tenant_id"],
        trace_id=row["trace_id"],
        input_file=row["input_file"],
        result_file=row["result_file"],
        case_count=row["case_count"],
        decision_count=row["decision_count"],
        review_task_count=row["review_task_count"],
        auto_handled_count=row["auto_handled_count"],
        review_count=row["review_count"],
        auto_handled_rate=row["auto_handled_rate"],
        review_rate=row["review_rate"],
        total_duration_ms=row["total_duration_ms"],
        created_at=row["created_at"],
        result_dirty=bool(row["result_dirty"]),
    )
