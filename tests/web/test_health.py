from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rss_hub.web.app import DEFAULT_DATA_DIR, create_app


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(data_dir=tmp_path))


def test_healthz_is_ok_when_the_data_directory_is_writable(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["version"], str) and body["version"]


def test_healthz_reports_an_unwritable_data_directory(tmp_path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x")
    client = TestClient(create_app(data_dir=blocker / "data"))

    response = client.get("/healthz")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "reason": "data_dir_not_writable"}


def test_healthz_leaves_no_files_behind(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    client.get("/healthz")
    client.get("/healthz")
    assert list(tmp_path.iterdir()) == []


def test_healthz_does_not_expose_paths_or_other_details(client, tmp_path):
    body = client.get("/healthz").json()
    assert set(body) <= {"status", "version", "reason"}
    assert str(tmp_path) not in str(body)


@pytest.mark.security
@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_interactive_api_docs_are_not_exposed(client, path):
    # 인증 없이 인터넷에 열리는 서비스라서 API 문서 화면과 스키마를 내놓지 않는다
    assert client.get(path).status_code == 404


def test_unknown_paths_return_404(client):
    assert client.get("/nope").status_code == 404


def test_default_data_directory_is_the_container_volume():
    assert Path("/data") == DEFAULT_DATA_DIR
