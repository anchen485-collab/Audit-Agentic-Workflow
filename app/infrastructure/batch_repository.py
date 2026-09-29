import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.domain.errors import (
    CaseRetryConflictError,
    CaseRetryIdempotencyError,
    CaseRetryInProgressError,
    CaseRetryNotFoundError,
)
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


@dataclass(frozen=True)
class CaseRetryAttemptContext:
    """开始重试后返回给服务层的稳定上下文。"""

    attempt_id: str
    batch_id: str
    case_id: str
    tenant_id: str
    idempotency_key: str
    retry_trace_id: str
    retried_by: str
    previous_action: str
    case_payload: dict[str, Any]
    previous_decision: dict[str, Any]
    idempotent_replay: bool = False
    cached_response: dict[str, Any] | None = None


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


def get_case_payload(
    database_path: Path,
    batch_id: str,
    case_id: str,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    """读取一条审批单，重试前必须同时校验批次和租户。"""
    init_database(database_path)
    where_clause = "batch_id = ? AND case_id = ?"
    params: tuple[Any, ...] = (batch_id, case_id)
    if tenant_id:
        where_clause += " AND tenant_id = ?"
        params = (batch_id, case_id, tenant_id)

    with connect_database(database_path) as connection:
        row = connection.execute(
            f"SELECT payload_json FROM audit_cases WHERE {where_clause}",
            params,
        ).fetchone()

    return json.loads(row["payload_json"]) if row is not None else None


def get_decision_payload(
    database_path: Path,
    batch_id: str,
    case_id: str,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    """读取一条当前审批结论，供重试前的人工结论保护使用。"""
    init_database(database_path)
    where_clause = "batch_id = ? AND case_id = ?"
    params: tuple[Any, ...] = (batch_id, case_id)
    if tenant_id:
        where_clause += " AND tenant_id = ?"
        params = (batch_id, case_id, tenant_id)

    with connect_database(database_path) as connection:
        row = connection.execute(
            f"SELECT payload_json FROM audit_decisions WHERE {where_clause}",
            params,
        ).fetchone()

    return json.loads(row["payload_json"]) if row is not None else None


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


def begin_case_retry_attempt(
    database_path: Path,
    batch_id: str,
    case_id: str,
    tenant_id: str | None,
    idempotency_key: str,
    retried_by: str,
    retry_trace_id: str,
    lock_timeout_seconds: int,
) -> CaseRetryAttemptContext:
    """原子获取单条审批单的重试锁，并支持相同幂等键回放结果。"""
    init_database(database_path)
    started_at = new_created_at()

    with connect_database(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        batch_sql = "SELECT tenant_id FROM audit_batches WHERE batch_id = ?"
        batch_params: tuple[Any, ...] = (batch_id,)
        if tenant_id:
            batch_sql += " AND tenant_id = ?"
            batch_params = (batch_id, tenant_id)
        batch_row = connection.execute(batch_sql, batch_params).fetchone()
        if batch_row is None:
            raise CaseRetryNotFoundError("未找到指定审批批次。")

        actual_tenant_id = str(batch_row["tenant_id"])
        case_row = connection.execute(
            """
            SELECT payload_json FROM audit_cases
            WHERE batch_id = ? AND case_id = ? AND tenant_id = ?
            """,
            (batch_id, case_id, actual_tenant_id),
        ).fetchone()
        decision_row = connection.execute(
            """
            SELECT payload_json FROM audit_decisions
            WHERE batch_id = ? AND case_id = ? AND tenant_id = ?
            """,
            (batch_id, case_id, actual_tenant_id),
        ).fetchone()
        if case_row is None or decision_row is None:
            raise CaseRetryNotFoundError("未找到指定批次中的审批单。")

        case_payload = json.loads(case_row["payload_json"])
        previous_decision = json.loads(decision_row["payload_json"])
        completed_review = connection.execute(
            """
            SELECT 1 FROM review_tasks
            WHERE batch_id = ? AND case_id = ? AND tenant_id = ? AND status = 'completed'
            """,
            (batch_id, case_id, actual_tenant_id),
        ).fetchone()
        if previous_decision.get("manual_final_action") or completed_review is not None:
            raise CaseRetryConflictError("该审批单已有人工最终结论，重试不会覆盖人工审核结果。")

        existing = connection.execute(
            """
            SELECT * FROM case_retry_attempts
            WHERE tenant_id = ? AND batch_id = ? AND case_id = ? AND idempotency_key = ?
            """,
            (actual_tenant_id, batch_id, case_id, idempotency_key),
        ).fetchone()
        if existing is not None:
            if existing["status"] == "succeeded":
                cached_response = json.loads(existing["response_json"]) if existing["response_json"] else None
                return CaseRetryAttemptContext(
                    attempt_id=existing["attempt_id"],
                    batch_id=batch_id,
                    case_id=case_id,
                    tenant_id=actual_tenant_id,
                    idempotency_key=idempotency_key,
                    retry_trace_id=existing["retry_trace_id"],
                    retried_by=existing["retried_by"],
                    previous_action=existing["old_action"],
                    case_payload=case_payload,
                    previous_decision=previous_decision,
                    idempotent_replay=True,
                    cached_response=cached_response,
                )
            if existing["status"] == "running":
                if _is_retry_attempt_stale(existing["started_at"], lock_timeout_seconds):
                    _mark_retry_attempt_timed_out(connection, existing, started_at)
                    # 先持久化超时状态，再提示客户端换一个新键；否则异常退出会回滚本次更新。
                    connection.commit()
                    raise CaseRetryIdempotencyError("该幂等键对应的重试已超时，请使用新的幂等键再次提交。")
                raise CaseRetryInProgressError("该审批单正在重试，请稍后查询重试结果。")
            raise CaseRetryIdempotencyError("该幂等键对应的重试已失败，请使用新的幂等键再次提交。")

        running_attempt = connection.execute(
            """
            SELECT attempt_id, started_at, payload_json FROM case_retry_attempts
            WHERE tenant_id = ? AND batch_id = ? AND case_id = ? AND status = 'running'
            """,
            (actual_tenant_id, batch_id, case_id),
        ).fetchone()
        if running_attempt is not None:
            if not _is_retry_attempt_stale(running_attempt["started_at"], lock_timeout_seconds):
                raise CaseRetryInProgressError("该审批单已经有一个重试任务正在执行。")
            _mark_retry_attempt_timed_out(connection, running_attempt, started_at)

        attempt_id = f"retry_{uuid4().hex[:16]}"
        attempt_payload = {
            "attempt_id": attempt_id,
            "batch_id": batch_id,
            "case_id": case_id,
            "tenant_id": actual_tenant_id,
            "idempotency_key": idempotency_key,
            "retry_trace_id": retry_trace_id,
            "retried_by": retried_by,
            "status": "running",
            "old_action": previous_decision.get("action", ""),
            "new_action": None,
            "error_code": None,
            "error_message": None,
            "started_at": started_at,
            "completed_at": None,
        }
        connection.execute(
            """
            INSERT INTO case_retry_attempts (
                attempt_id, batch_id, case_id, tenant_id, idempotency_key,
                retry_trace_id, retried_by, status, old_action, started_at, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?)
            """,
            (
                attempt_id,
                batch_id,
                case_id,
                actual_tenant_id,
                idempotency_key,
                retry_trace_id,
                retried_by,
                attempt_payload["old_action"],
                started_at,
                _to_json(attempt_payload),
            ),
        )

    return CaseRetryAttemptContext(
        attempt_id=attempt_id,
        batch_id=batch_id,
        case_id=case_id,
        tenant_id=actual_tenant_id,
        idempotency_key=idempotency_key,
        retry_trace_id=retry_trace_id,
        retried_by=retried_by,
        previous_action=attempt_payload["old_action"],
        case_payload=case_payload,
        previous_decision=previous_decision,
    )


def replace_case_after_retry(
    database_path: Path,
    attempt_id: str,
    batch_id: str,
    case_id: str,
    tenant_id: str,
    decision: dict[str, Any],
    evidence_package: dict[str, Any],
    assessments: list[dict[str, Any]],
    review_task: dict[str, Any] | None,
    retry_trace_id: str,
    retried_by: str,
) -> dict[str, float | int]:
    """在同一事务内替换当前结果、更新指标并完成重试尝试。"""
    init_database(database_path)

    with connect_database(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        attempt_row = connection.execute(
            """
            SELECT payload_json FROM case_retry_attempts
            WHERE attempt_id = ? AND batch_id = ? AND case_id = ? AND tenant_id = ? AND status = 'running'
            """,
            (attempt_id, batch_id, case_id, tenant_id),
        ).fetchone()
        if attempt_row is None:
            raise CaseRetryConflictError("当前重试任务已失效，请刷新后重新提交。")

        old_decision_row = connection.execute(
            """
            SELECT payload_json FROM audit_decisions
            WHERE batch_id = ? AND case_id = ? AND tenant_id = ?
            """,
            (batch_id, case_id, tenant_id),
        ).fetchone()
        if old_decision_row is None:
            raise CaseRetryNotFoundError("未找到审批单的原始结论。")

        old_decision = json.loads(old_decision_row["payload_json"])
        completed_review = connection.execute(
            """
            SELECT 1 FROM review_tasks
            WHERE batch_id = ? AND case_id = ? AND tenant_id = ? AND status = 'completed'
            """,
            (batch_id, case_id, tenant_id),
        ).fetchone()
        if old_decision.get("manual_final_action") or completed_review is not None:
            raise CaseRetryConflictError("该审批单已有人工最终结论，重试不会覆盖人工审核结果。")

        decision_payload = {**decision, "tenant_id": tenant_id}
        connection.execute(
            """
            UPDATE audit_decisions SET payload_json = ?
            WHERE batch_id = ? AND case_id = ? AND tenant_id = ?
            """,
            (_to_json(decision_payload), batch_id, case_id, tenant_id),
        )

        evidence_payload = {**evidence_package, "tenant_id": tenant_id}
        connection.execute(
            """
            INSERT OR REPLACE INTO evidence_packages (case_id, batch_id, tenant_id, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (case_id, batch_id, tenant_id, _to_json(evidence_payload)),
        )

        connection.execute(
            "DELETE FROM agent_assessments WHERE batch_id = ? AND case_id = ? AND tenant_id = ?",
            (batch_id, case_id, tenant_id),
        )
        for assessment in assessments:
            assessment_payload = {
                **assessment,
                "batch_id": batch_id,
                "case_id": case_id,
                "tenant_id": tenant_id,
            }
            connection.execute(
                """
                INSERT INTO agent_assessments (
                    batch_id, case_id, tenant_id, agent_name, status, duration_ms, payload_json
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

        if review_task is None:
            connection.execute(
                """
                DELETE FROM review_tasks
                WHERE batch_id = ? AND case_id = ? AND tenant_id = ? AND status != 'completed'
                """,
                (batch_id, case_id, tenant_id),
            )
        else:
            review_payload = {**review_task, "batch_id": batch_id, "tenant_id": tenant_id}
            connection.execute(
                """
                INSERT OR REPLACE INTO review_tasks (
                    task_id, batch_id, case_id, tenant_id, status, reviewer, final_action, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_task["task_id"],
                    batch_id,
                    case_id,
                    tenant_id,
                    review_task.get("status", "pending"),
                    review_task.get("reviewer"),
                    review_task.get("final_action"),
                    _to_json(review_payload),
                ),
            )

        metrics = _calculate_persisted_decision_metrics(connection, batch_id, tenant_id)
        connection.execute(
            """
            UPDATE audit_batches
            SET decision_count = ?, review_task_count = ?, auto_handled_count = ?,
                review_count = ?, auto_handled_rate = ?, review_rate = ?, result_dirty = 1
            WHERE batch_id = ? AND tenant_id = ?
            """,
            (
                metrics["decision_count"],
                metrics["review_task_count"],
                metrics["auto_handled_count"],
                metrics["review_count"],
                metrics["auto_handled_rate"],
                metrics["review_rate"],
                batch_id,
                tenant_id,
            ),
        )

        completed_at = new_created_at()
        retry_payload = {
            "batch_id": batch_id,
            "case_id": case_id,
            "tenant_id": tenant_id,
            "attempt_id": attempt_id,
            "retry_trace_id": retry_trace_id,
            "retried_by": retried_by,
            "old_action": old_decision.get("action", ""),
            "new_action": decision.get("action", ""),
            "old_reason": old_decision.get("reason", ""),
            "new_reason": decision.get("reason", ""),
            "retried_at": completed_at,
        }
        connection.execute(
            """
            INSERT INTO case_retry_logs (
                batch_id, case_id, tenant_id, retry_trace_id, retried_by,
                old_action, new_action, retried_at, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                case_id,
                tenant_id,
                retry_trace_id,
                retried_by,
                retry_payload["old_action"],
                retry_payload["new_action"],
                completed_at,
                _to_json(retry_payload),
            ),
        )
        attempt_payload = json.loads(attempt_row["payload_json"])
        attempt_payload.update(
            {
                "status": "succeeded",
                "new_action": decision.get("action", ""),
                "completed_at": completed_at,
            }
        )
        connection.execute(
            """
            UPDATE case_retry_attempts
            SET status = 'succeeded', new_action = ?, completed_at = ?, payload_json = ?
            WHERE attempt_id = ? AND status = 'running'
            """,
            (decision.get("action", ""), completed_at, _to_json(attempt_payload), attempt_id),
        )

    return metrics


def fail_case_retry_attempt(
    database_path: Path,
    attempt_id: str,
    error_code: str,
    error_message: str,
) -> None:
    """记录失败尝试并释放单条审批单的运行锁。"""
    init_database(database_path)
    completed_at = new_created_at()
    safe_message = error_message[:1000]
    with connect_database(database_path) as connection:
        row = connection.execute(
            "SELECT payload_json FROM case_retry_attempts WHERE attempt_id = ? AND status = 'running'",
            (attempt_id,),
        ).fetchone()
        if row is None:
            return
        payload = json.loads(row["payload_json"])
        payload.update(
            {
                "status": "failed",
                "error_code": error_code,
                "error_message": safe_message,
                "completed_at": completed_at,
            }
        )
        connection.execute(
            """
            UPDATE case_retry_attempts
            SET status = 'failed', error_code = ?, error_message = ?, completed_at = ?, payload_json = ?
            WHERE attempt_id = ? AND status = 'running'
            """,
            (error_code, safe_message, completed_at, _to_json(payload), attempt_id),
        )
        connection.commit()


def cache_case_retry_response(database_path: Path, attempt_id: str, response: dict[str, Any]) -> None:
    """缓存成功响应，使客户端重复提交相同幂等键时直接回放。"""
    init_database(database_path)
    with connect_database(database_path) as connection:
        connection.execute(
            """
            UPDATE case_retry_attempts SET response_json = ?
            WHERE attempt_id = ? AND status = 'succeeded'
            """,
            (_to_json(response), attempt_id),
        )
        connection.commit()


def list_case_retry_attempt_payloads(
    database_path: Path,
    batch_id: str,
    case_id: str,
    tenant_id: str | None = None,
) -> list[dict[str, Any]]:
    """按时间倒序查询一条审批单的重试尝试，包括成功和失败记录。"""
    init_database(database_path)
    where_clause = "batch_id = ? AND case_id = ?"
    params: tuple[Any, ...] = (batch_id, case_id)
    if tenant_id:
        where_clause += " AND tenant_id = ?"
        params = (batch_id, case_id, tenant_id)
    with connect_database(database_path) as connection:
        rows = connection.execute(
            f"""
            SELECT payload_json FROM case_retry_attempts
            WHERE {where_clause}
            ORDER BY started_at DESC, rowid DESC
            """,
            params,
        ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


def list_case_retry_log_payloads(
    database_path: Path,
    batch_id: str,
    case_id: str | None = None,
) -> list[dict[str, Any]]:
    """查询 Case 重试历史，供测试、审计与后续界面展示使用。"""
    if case_id:
        return _list_payloads(
            database_path,
            "case_retry_logs",
            "batch_id = ? AND case_id = ?",
            (batch_id, case_id),
        )
    return _list_payloads(database_path, "case_retry_logs", "batch_id = ?", (batch_id,))


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


def _calculate_persisted_decision_metrics(
    connection,
    batch_id: str,
    tenant_id: str,
) -> dict[str, float | int]:
    """在当前事务内从最新结论重算批次指标，避免结果和摘要短暂不一致。"""
    decision_rows = connection.execute(
        "SELECT payload_json FROM audit_decisions WHERE batch_id = ? AND tenant_id = ?",
        (batch_id, tenant_id),
    ).fetchall()
    decisions = [json.loads(row["payload_json"]) for row in decision_rows]
    review_task_count = connection.execute(
        "SELECT COUNT(*) AS count FROM review_tasks WHERE batch_id = ? AND tenant_id = ?",
        (batch_id, tenant_id),
    ).fetchone()["count"]
    total_count = len(decisions)
    review_count = sum(1 for decision in decisions if decision.get("needs_review"))
    auto_handled_count = total_count - review_count

    action_counts = {
        action: sum(1 for decision in decisions if decision.get("action") == action)
        for action in {
            "approved",
            "rejected",
            "needs_more_evidence",
            "needs_human_review",
        }
    }

    def rate(count: int) -> float:
        return count / total_count if total_count else 0.0

    return {
        "total_count": total_count,
        "decision_count": total_count,
        "review_task_count": int(review_task_count),
        "review_count": review_count,
        "auto_handled_count": auto_handled_count,
        "review_rate": rate(review_count),
        "auto_handled_rate": rate(auto_handled_count),
        "auto_approval_count": action_counts["approved"],
        "auto_approval_rate": rate(action_counts["approved"]),
        "auto_rejection_count": action_counts["rejected"],
        "auto_rejection_rate": rate(action_counts["rejected"]),
        "human_review_count": action_counts["needs_human_review"],
        "human_review_rate": rate(action_counts["needs_human_review"]),
        "insufficient_evidence_count": action_counts["needs_more_evidence"],
        "insufficient_evidence_rate": rate(action_counts["needs_more_evidence"]),
    }


def _is_retry_attempt_stale(started_at: str, timeout_seconds: int) -> bool:
    """判断运行中的重试是否已超过锁租约时间。"""
    try:
        started = datetime.fromisoformat(started_at)
    except (TypeError, ValueError):
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return datetime.now(UTC) - started >= timedelta(seconds=timeout_seconds)


def _mark_retry_attempt_timed_out(connection, attempt_row, completed_at: str) -> None:
    """把失去心跳的运行记录改为失败，从而释放数据库唯一锁。"""
    error_message = "重试执行超时，锁已自动释放。"
    payload = json.loads(attempt_row["payload_json"])
    payload.update(
        {
            "status": "failed",
            "error_code": "retry_lock_timeout",
            "error_message": error_message,
            "completed_at": completed_at,
        }
    )
    connection.execute(
        """
        UPDATE case_retry_attempts
        SET status = 'failed', error_code = ?, error_message = ?, completed_at = ?, payload_json = ?
        WHERE attempt_id = ? AND status = 'running'
        """,
        ("retry_lock_timeout", error_message, completed_at, _to_json(payload), attempt_row["attempt_id"]),
    )


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
