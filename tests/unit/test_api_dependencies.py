import pytest
from fastapi.testclient import TestClient

from app.api import dependencies
from app.api.app import create_app
from app.infrastructure.batch_repository import (
    AuditBatchRecord,
    new_created_at,
    save_batch_details,
    save_batch_record,
)
from app.infrastructure.evidence_provider import MockCompanyEvidenceProvider
from app.infrastructure.settings import Settings
from app.infrastructure.website_provider import WebsiteCompanyProvider


def test_get_evidence_provider_returns_mock_provider(monkeypatch):
    """mock 模式应该返回本地 mock 证据 provider。"""
    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: Settings(COMPANY_PROVIDER="mock"),
    )

    provider = dependencies.get_evidence_provider()

    assert isinstance(provider, MockCompanyEvidenceProvider)


def test_get_evidence_provider_returns_website_provider(monkeypatch):
    """website 模式应该返回官网爬虫 provider。"""
    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: Settings(COMPANY_PROVIDER="website"),
    )

    provider = dependencies.get_evidence_provider()

    assert isinstance(provider, WebsiteCompanyProvider)


def test_get_evidence_provider_rejects_unknown_provider(monkeypatch):
    """未知 provider 配置应该抛出清晰错误。"""
    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: Settings(COMPANY_PROVIDER="unknown"),
    )

    with pytest.raises(ValueError, match="不支持的企业证据 provider"):
        dependencies.get_evidence_provider()


def test_protected_api_requires_token_when_auth_enabled(tmp_path):
    """启用认证后，未携带 token 的请求应该被拒绝。"""
    client = _build_auth_client(tmp_path)

    response = client.get("/api/audit/batches")

    assert response.status_code == 401


def test_protected_api_rejects_invalid_token(tmp_path):
    """启用认证后，无效 token 应该返回 401。"""
    client = _build_auth_client(tmp_path)

    response = client.get(
        "/api/audit/batches",
        headers={"Authorization": "Bearer bad-token"},
    )

    assert response.status_code == 401


def test_protected_api_accepts_valid_token(tmp_path):
    """启用认证后，有效 token 应该能访问授权接口。"""
    client = _build_auth_client(tmp_path)

    response = client.get(
        "/api/audit/batches",
        headers={"Authorization": "Bearer auditor-token"},
    )

    assert response.status_code == 200


def test_role_dependency_rejects_wrong_role(tmp_path):
    """普通上传人员不能访问人工复核任务接口。"""
    client = _build_auth_client(tmp_path)

    response = client.get(
        "/api/review/tasks",
        headers={"Authorization": "Bearer uploader-token"},
    )

    assert response.status_code == 403


def test_review_decision_uses_authenticated_user_not_request_reviewer(tmp_path):
    """复核提交时，审核员身份必须来自认证用户，而不是前端请求体。"""
    database_path = tmp_path / "audit_agent.db"
    save_batch_record(database_path, _build_record("batch_001", tenant_id="tenant_a"))
    save_batch_details(
        database_path=database_path,
        batch_id="batch_001",
        tenant_id="tenant_a",
        cases=[{"case_id": "case_001", "company_name": "Acme"}],
        decisions=[{"case_id": "case_001", "action": "needs_human_review"}],
        review_tasks=[{"task_id": "review_case_001", "case_id": "case_001", "status": "pending"}],
        assessments={},
    )
    client = _build_auth_client(tmp_path)

    response = client.post(
        "/api/review/tasks/review_case_001/decision",
        headers={"Authorization": "Bearer reviewer-token"},
        json={
            "reviewer": "admin",
            "final_action": "approved",
        },
    )

    assert response.status_code == 200
    assert response.json()["reviewer"] == "reviewer_001"


def _build_auth_client(tmp_path) -> TestClient:
    """创建开启认证的测试客户端。"""
    app = create_app()

    def override_settings() -> Settings:
        return Settings(
            AUDIT_STORAGE_DIR=tmp_path,
            AUTH_ENABLED=True,
            AUTH_TOKENS=(
                "uploader-token:uploader_001:tenant_a:uploader;"
                "reviewer-token:reviewer_001:tenant_a:reviewer;"
                "auditor-token:auditor_001:tenant_a:auditor"
            ),
            _env_file=None,
        )

    app.dependency_overrides[dependencies.get_app_settings] = override_settings
    return TestClient(app)


def _build_record(batch_id: str, tenant_id: str) -> AuditBatchRecord:
    """构造测试批次记录。"""
    return AuditBatchRecord(
        batch_id=batch_id,
        tenant_id=tenant_id,
        trace_id="trace_001",
        input_file="storage/uploads/input.xlsx",
        result_file="storage/outputs/result.xlsx",
        case_count=1,
        decision_count=1,
        review_task_count=1,
        auto_handled_count=0,
        review_count=1,
        auto_handled_rate=0.0,
        review_rate=1.0,
        total_duration_ms=10.0,
        created_at=new_created_at(),
    )
