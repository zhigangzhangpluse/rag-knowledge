# ----------------------------------------------------------------------
# 阅读入口：为每个测试提供临时数据库、测试客户端和知识库，并封装准备可检索文档的步骤。
# pytest fixture 是可复用的测试准备过程。tmp_path 隔离测试数据。monkeypatch 在单个测试中临时替换依赖，不会永久修改生产代码。
# pytest fixture 是给测试准备环境的工具，类似每道实验题共用一套干净器材。
# 临时目录与测试替身避免污染真实知识库；TestClient 用代码模拟 HTTP 请求。
# 代码示例：def test_x(client): ...，pytest 会按参数名注入 client。
# 面试问：为何不用真实模型跑全部单元测试？答：速度慢且依赖外部环境，真实链路另做集成验证。
# ----------------------------------------------------------------------
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
