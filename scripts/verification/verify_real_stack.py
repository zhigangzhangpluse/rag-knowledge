"""使用真实 BGE、Milvus、Redis、DeepSeek 验证 API 业务链路，消耗少量 API 额度。"""
import json
import sys
import time
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.retrieval import active_chunks
from app.sessions import RedisSessions
from tests.conftest import upload_ready
from tests.test_chat import events


def main():
    run_id = uuid4().hex
    folder = Path('data/real-check') / run_id
    folder.mkdir(parents=True)
    settings = Settings(app_mode='production', data_dir=folder,
                        database_url=f'sqlite:///{folder / "app.db"}',
                        milvus_collection='verify_' + run_id)
    app = create_app(settings, start_worker=False)
    services = app.state.services
    report = {'run_id': run_id, 'scope': '真实 BGE + Milvus + Redis + DeepSeek，FastAPI TestClient', 'checks': [], 'answers': []}

    def passed(name):
        report['checks'].append(name)
        print(name, flush=True)

    with TestClient(app) as client:
        health = client.get('/api/health').json()
        assert all(value == 'ok' for value in health['checks'].values()), health
        passed('Milvus / Redis health')
        kb = client.post('/api/knowledge-bases', json={'name': '真实集成验收'}).json()['id']
        other = client.post('/api/knowledge-bases', json={'name': '隔离验收'}).json()['id']
        text = '# 年假制度\n正式员工每年可以申请五天年假。试用期员工不能申请年假。'
        doc = upload_ready(client, kb, text)
        passed('document upload and real vector insertion')
        assert not services.retriever.retrieve(other, '年假')
        sid = uuid4().hex
        for question in ['正式员工每年有几天年假？', '试用期也可以吗？']:
            started = time.perf_counter()
            response = client.post(f'/api/knowledge-bases/{kb}/chat', json={'question': question, 'session_id': sid})
            frames = events(response)
            assert frames[-1][0] == 'done' and not frames[-1][1]['refused'], frames
            answer = ''.join(data['text'] for event, data in frames if event == 'delta')
            assert next(data['items'] for event, data in frames if event == 'sources')
            assert '[1]' in answer, answer
            report['answers'].append({'question': question, 'answer': answer, 'events': frames,
                                      'elapsed_ms': round((time.perf_counter() - started) * 1000)})
            passed('SSE response: ' + question)
        assert len(RedisSessions(settings).get(kb, sid)) == 4
        assert not services.sessions.get(other, sid)
        passed('Redis persisted history and knowledge-base isolation')
        refused = dict(events(client.post(f'/api/knowledge-bases/{other}/chat', json={'question': '工资是多少？'})))
        assert refused['done']['refused'] and not refused['sources']['items']
        passed('empty evidence refusal')
        response = client.put(f'/api/knowledge-bases/{kb}/documents/{doc}',
                              files={'file': ('制度.md', text.replace('五天', '十天').encode())})
        assert response.status_code == 202
        assert services.ingestion.process_one()
        chunks = active_chunks(services.database, kb, services.models.name)
        assert chunks and all(chunk.version == 2 for chunk in chunks)
        rows = services.index.client.query(collection_name=settings.milvus_collection,
                                          filter=f'doc_id == "{doc}"', output_fields=['version'])
        assert rows and all(row['version'] == 2 for row in rows), rows
        assert any('十天' in hit.chunk.text for hit in services.retriever.retrieve(kb, '年假几天'))
        passed('update activates new version and removes old Milvus vectors')
        assert client.delete(f'/api/knowledge-bases/{kb}/documents/{doc}').status_code == 202
        assert services.ingestion.process_one()
        assert not services.retriever.retrieve(kb, '年假')
        assert not services.index.client.query(collection_name=settings.milvus_collection,
                                              filter=f'doc_id == "{doc}"', output_fields=['id'])
        passed('document deletion synchronizes Milvus')
        services.sessions.clear(kb, sid)
        services.index.client.drop_collection(settings.milvus_collection)
        report['status'] = 'passed'
    Path('reports/real-stack.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
