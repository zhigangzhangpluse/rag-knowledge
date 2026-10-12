"""测试使用临时目录与确定性模型，不触碰真实密钥和业务数据。"""
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    settings = Settings(_env_file=None, app_mode="test", data_dir=tmp_path,
                        database_url=f"sqlite:///{tmp_path / 'test.db'}", min_rerank_score=0.05)
    application = create_app(settings, start_worker=False)
    with TestClient(application) as browser:
        yield browser


@pytest.fixture
def kb(client):
    return client.post("/api/knowledge-bases", json={"name": "测试制度库"}).json()["id"]


def upload_ready(client, kb_id, text, name="制度.md"):
    response = client.post(f"/api/knowledge-bases/{kb_id}/documents", files={"file": (name, text.encode(), "text/markdown")})
    assert response.status_code == 202
    services = client.app.state.services
    assert services.ingestion.process_one()
    jobs = client.get(f"/api/knowledge-bases/{kb_id}/jobs").json()
    assert jobs[0]["status"] == "completed", jobs
    return response.json()["doc_id"]
