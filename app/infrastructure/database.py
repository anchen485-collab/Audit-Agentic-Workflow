import sqlite3
from pathlib import Path


def connect_database(database_path: Path) -> sqlite3.Connection:
    """连接 SQLite 数据库。"""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


def init_database(database_path: Path) -> None:
    """初始化数据库表结构。"""
    with connect_database(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_batches (
                batch_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                trace_id TEXT NOT NULL,
                input_file TEXT NOT NULL,
                result_file TEXT NOT NULL,
                case_count INTEGER NOT NULL,
                decision_count INTEGER NOT NULL,
                review_task_count INTEGER NOT NULL,
                auto_handled_count INTEGER NOT NULL,
                review_count INTEGER NOT NULL,
                auto_handled_rate REAL NOT NULL,
                review_rate REAL NOT NULL,
                total_duration_ms REAL NOT NULL,
                created_at TEXT NOT NULL,
                result_dirty INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        _ensure_column(
            connection=connection,
            table_name="audit_batches",
            column_name="tenant_id",
            column_sql="tenant_id TEXT NOT NULL DEFAULT 'default'",
        )
        _ensure_column(
            connection=connection,
            table_name="audit_batches",
            column_name="result_dirty",
            column_sql="result_dirty INTEGER NOT NULL DEFAULT 0",
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_cases (
                case_id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                payload_json TEXT NOT NULL
            )
            """
        )
        _ensure_column(connection, "audit_cases", "tenant_id", "tenant_id TEXT NOT NULL DEFAULT 'default'")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_decisions (
                case_id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                payload_json TEXT NOT NULL
            )
            """
        )
        _ensure_column(connection, "audit_decisions", "tenant_id", "tenant_id TEXT NOT NULL DEFAULT 'default'")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS review_tasks (
                task_id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                status TEXT NOT NULL,
                reviewer TEXT,
                final_action TEXT,
                payload_json TEXT NOT NULL
            )
            """
        )
        _ensure_column(connection, "review_tasks", "tenant_id", "tenant_id TEXT NOT NULL DEFAULT 'default'")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS evidence_packages (
                case_id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                payload_json TEXT NOT NULL
            )
            """
        )
        _ensure_column(connection, "evidence_packages", "tenant_id", "tenant_id TEXT NOT NULL DEFAULT 'default'")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                agent_name TEXT NOT NULL,
                status TEXT NOT NULL,
                duration_ms REAL NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        _ensure_column(connection, "agent_assessments", "tenant_id", "tenant_id TEXT NOT NULL DEFAULT 'default'")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS review_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                old_action TEXT NOT NULL,
                new_action TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                reviewed_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        _ensure_column(connection, "review_audit_logs", "tenant_id", "tenant_id TEXT NOT NULL DEFAULT 'default'")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS file_access_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                batch_id TEXT NOT NULL,
                action TEXT NOT NULL,
                client_ip TEXT NOT NULL,
                user_agent TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        connection.commit()


def _ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_sql: str,
) -> None:
    """给旧库补充新增列，避免已有本地数据库启动时报错。"""
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    existing_columns = {row["name"] for row in rows}

    if column_name not in existing_columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")
