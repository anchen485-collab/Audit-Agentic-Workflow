from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.agents.llm_classification_provider import MockClassificationProvider
from app.api.app import create_app
from app.api.dependencies import get_app_settings, get_classification_provider, get_evidence_provider
from app.domain.models import EvidencePackage, EvidenceSnippet
from app.infrastructure.settings import Settings


class FakeEvidenceProvider:
    """端到端测试用证据 provider，避免依赖真实官网网络。"""

    def fetch(self, case_id: str, company_name: str, website_url: str = "") -> EvidencePackage:
        return EvidencePackage(
            case_id=case_id,
            company_name=company_name,
            sources=["fake_website"],
            business_scope="公司提供软件开发、系统集成和信息技术服务。",
            snippets=[
                EvidenceSnippet(
                    source="fake_website",
                    text="官网显示公司提供软件开发和信息技术服务。",
                    url=website_url,
                )
            ],
            quality_score=95,
            errors=[],
        )


def test_upload_query_download_and_review_flow(tmp_path):
    """覆盖上传、批次查询、trace 查询、下载和人工复核提交的完整链路。"""
    app = create_app()

    def override_settings() -> Settings:
        return Settings(AUDIT_STORAGE_DIR=tmp_path)

    app.dependency_overrides[get_app_settings] = override_settings
    app.dependency_overrides[get_evidence_provider] = lambda: FakeEvidenceProvider()
    app.dependency_overrides[get_classification_provider] = lambda: MockClassificationProvider()

    client = TestClient(app)
    excel_path = tmp_path / "audit_cases.xlsx"
    _create_e2e_excel(excel_path)

    with excel_path.open("rb") as file:
        upload_response = client.post(
            "/api/audit/upload",
            files={
                "file": (
                    "audit_cases.xlsx",
                    file,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )

    assert upload_response.status_code == 200
    upload_data = upload_response.json()
    batch_id = upload_data["batch_id"]
    assert upload_data["decision_count"] == 2
    assert upload_data["download_url"] == f"/api/audit/batches/{batch_id}/result"

    batch_response = client.get(f"/api/audit/batches/{batch_id}")
    cases_response = client.get(f"/api/audit/batches/{batch_id}/cases")
    decisions_response = client.get(f"/api/audit/batches/{batch_id}/decisions")
    assessments_response = client.get(f"/api/audit/batches/{batch_id}/assessments")
    download_response = client.get(upload_data["download_url"])

    assert batch_response.status_code == 200
    assert cases_response.json()["total"] == 2
    assert decisions_response.json()["total"] == 2
    assert "classification_agent_status" in decisions_response.json()["items"][0]
    assert assessments_response.json()["total"] >= 1
    assert download_response.status_code == 200
    assert download_response.content

    task_id = upload_data["review_tasks"][0]["task_id"]
    review_response = client.post(
        f"/api/review/tasks/{task_id}/decision",
        json={"reviewer": "audit_user", "final_action": "approved"},
    )

    assert review_response.status_code == 200
    assert review_response.json()["status"] == "completed"
    assert review_response.json()["reviewed_at"]

    reviewed_decisions_response = client.get(f"/api/audit/batches/{batch_id}/decisions")
    reviewed_decisions = reviewed_decisions_response.json()["items"]
    assert any(decision.get("manual_final_action") == "approved" for decision in reviewed_decisions)

    app.dependency_overrides.clear()


def _create_e2e_excel(path):
    """创建一条自动审批和一条人工复核记录，覆盖关键业务分支。"""
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["日期", "姓名", "一级分类", "细分", "企业名称&官网"])
    sheet.append(
        [
            "2026-07-25",
            "张三",
            "信软技术服务",
            "软件开发",
            "杭州云启软件有限公司 https://yunqi.example.com",
        ]
    )
    sheet.append(
        [
            "2026-07-25",
            "李四",
            "不存在的一级分类",
            "不存在的细分",
            "杭州云启软件有限公司 https://yunqi.example.com",
        ]
    )
    workbook.save(path)
