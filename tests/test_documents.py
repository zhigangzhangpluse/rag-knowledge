# ----------------------------------------------------------------------
# 阅读入口：验证文档生命周期：入库、隔离、幂等更新、替换失败、重试、删除与敏感文件隔离。
# 测试故意让向量写入失败，检验旧版本仍可用。正确的测试不仅检查 happy path，也检查失败时系统状态是否符合约束。
# 文档生命周期测试关注用户可见结果：更新后只看到新版，删除后搜不到，失败后能恢复。
# monkeypatch 可故意让外部步骤失败，验证业务在失败时是否仍保护旧版本。
# 面试问：只测成功路径够吗？答：不够，跨 SQLite/Milvus 的中间失败更容易暴露一致性问题。
# ----------------------------------------------------------------------
from sqlalchemy import select

from app.database import Chunk, Document, Job
from app.retrieval import active_chunks
from tests.conftest import upload_ready


def test_ingest_update_delete_and_isolation(client, kb):
    services = client.app.state.services
    doc_id = upload_ready(client, kb, "# 年假制度\n员工每年可以申请五天年假。")
    other = client.post("/api/knowledge-bases", json={"name": "独立知识库"}).json()["id"]
    assert not services.retriever.retrieve(other, "年假")
    assert services.retriever.retrieve(kb, "年假")
    chunk = active_chunks(services.database, kb, services.models.name)[0]
    assert client.get(f"/api/knowledge-bases/{other}/chunks/{chunk.id}").status_code == 404
    assert client.delete(f"/api/knowledge-bases/{other}/documents/{doc_id}").status_code == 404
    same = client.put(f"/api/knowledge-bases/{kb}/documents/{doc_id}", files={"file": ("制度.md", "# 年假制度\n员工每年可以申请五天年假。".encode())})
    assert same.json()["unchanged"]
    changed = client.put(f"/api/knowledge-bases/{kb}/documents/{doc_id}", files={"file": ("制度.md", "# 年假制度\n员工每年可以申请十天年假。".encode())})
    assert changed.status_code == 202
    assert "五天" in active_chunks(services.database, kb, services.models.name)[0].text
    assert services.ingestion.process_one()
    chunks = active_chunks(services.database, kb, services.models.name)
    assert len(chunks) == 1 and "十天" in chunks[0].text and chunks[0].version == 2
    assert client.get(f"/api/knowledge-bases/{kb}/chunks/{chunk.id}").status_code == 404
    response = client.delete(f"/api/knowledge-bases/{kb}/documents/{doc_id}")
    assert response.status_code == 202
    assert not services.retriever.retrieve(kb, "年假")
    assert services.ingestion.process_one()
    with services.database() as session:
        assert not list(session.scalars(select(Chunk).where(Chunk.doc_id == doc_id)))
    assert client.get(f"/api/knowledge-bases/{kb}/documents/{doc_id}/download").status_code == 404


def test_failed_update_keeps_old_version_and_retry(client, kb, monkeypatch):
    services = client.app.state.services
    doc_id = upload_ready(client, kb, "# 报销\n报销需要提供发票。")
    response = client.put(f"/api/knowledge-bases/{kb}/documents/{doc_id}", files={"file": ("制度.md", "# 报销\n报销不再需要提供发票。".encode())})
    job_id = response.json()["job_id"]
    original = services.index.upsert

    def fail(chunks):
        raise ConnectionError("模拟向量库故障")

    monkeypatch.setattr(services.index, "upsert", fail)
    services.ingestion.process_one()
    with services.database() as session:
        assert session.get(Document, doc_id).active_version == 1
        assert session.get(Job, job_id).status == "failed"
    assert "不再" not in active_chunks(services.database, kb, services.models.name)[0].text
    monkeypatch.setattr(services.index, "upsert", original)
    assert client.post(f"/api/knowledge-bases/{kb}/jobs/{job_id}/retry").status_code == 200
    services.ingestion.process_one()
    assert "不再" in active_chunks(services.database, kb, services.models.name)[0].text


def test_delete_queued_document_cancels_ingestion(client, kb):
    services = client.app.state.services
    response = client.post(f"/api/knowledge-bases/{kb}/documents", files={"file": ("a.md", b"content")})
    doc_id = response.json()["doc_id"]
    client.delete(f"/api/knowledge-bases/{kb}/documents/{doc_id}")
    services.ingestion.process_one()
    assert not active_chunks(services.database, kb, services.models.name)
    with services.database() as session:
        assert session.get(Job, response.json()["job_id"]).status == "cancelled"


def test_wrong_file_and_empty_upload(client, kb):
    path = f"/api/knowledge-bases/{kb}/documents"
    assert client.post(path, files={"file": ("a.exe", b"not-document")}).status_code == 400
    assert client.post(path, files={"file": ("a.md", b"")}).status_code == 400


def test_no_secret_or_cross_site_exposure(client):
    health = client.get("/api/health")
    assert health.status_code == 200 and "api_key" not in health.text
    assert client.get("/.env").status_code == 404
    assert client.get("/api/knowledge-bases", headers={"Origin": "https://untrusted.example"}).status_code == 403


def test_incremental_update_reuses_unchanged_vectors(client, kb, monkeypatch):
    services = client.app.state.services
    doc_id = upload_ready(client, kb, "# 年假\n五天年假。\n# 设备\n一台电脑。")
    encoded = []
    original = services.models.encode

    def recording(texts):
        encoded.extend(texts)
        return original(texts)

    monkeypatch.setattr(services.models, "encode", recording)
    client.put(f"/api/knowledge-bases/{kb}/documents/{doc_id}", files={"file": ("制度.md", "# 年假\n五天年假。\n# 设备\n两台电脑。".encode())})
    services.ingestion.process_one()
    assert len(encoded) == 1 and "两台电脑" in encoded[0]


def test_failed_cleanup_can_retry_without_duplicate_ids(client, kb, monkeypatch):
    services = client.app.state.services
    doc_id = upload_ready(client, kb, "# 年假\n五天年假。")
    response = client.put(f"/api/knowledge-bases/{kb}/documents/{doc_id}", files={"file": ("制度.md", "# 年假\n十天年假。".encode())})
    original = services.index.delete_old_versions

    def fail(*args):
        raise ConnectionError("模拟清理失败")

    monkeypatch.setattr(services.index, "delete_old_versions", fail)
    services.ingestion.process_one()
    before = active_chunks(services.database, kb, services.models.name)
    assert len(before) == 1 and "十天" in before[0].text
    monkeypatch.setattr(services.index, "delete_old_versions", original)
    services.ingestion.retry(response.json()["job_id"])
    services.ingestion.process_one()
    after = active_chunks(services.database, kb, services.models.name)
    assert [chunk.id for chunk in before] == [chunk.id for chunk in after]


def test_failed_delete_remains_unsearchable_until_retry(client, kb, monkeypatch):
    services = client.app.state.services
    doc_id = upload_ready(client, kb, "# 年假\n五天年假。")
    original = services.index.delete_document

    def fail(*args):
        raise ConnectionError("模拟删除索引失败")

    monkeypatch.setattr(services.index, "delete_document", fail)
    response = client.delete(f"/api/knowledge-bases/{kb}/documents/{doc_id}")
    services.ingestion.process_one()
    assert not services.retriever.retrieve(kb, "年假")
    monkeypatch.setattr(services.index, "delete_document", original)
    services.ingestion.retry(response.json()["job_id"])
    services.ingestion.process_one()
    with services.database() as session:
        assert session.get(Job, response.json()["job_id"]).status == "completed"
