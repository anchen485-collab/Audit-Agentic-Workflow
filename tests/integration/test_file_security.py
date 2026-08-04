from fastapi.testclient import TestClient

from app.api.app import create_app


def test_download_result_rejects_path_traversal_batch_id():
    client = TestClient(create_app())

    response = client.get("/api/audit/batches/..secret/result")

    assert response.status_code == 400


def test_upload_rejects_empty_file():
    client = TestClient(create_app())

    response = client.post(
        "/api/audit/upload",
        files={
            "file": (
                "empty.xlsx",
                b"",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 400
