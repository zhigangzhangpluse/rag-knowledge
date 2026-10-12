"""验证真实 BGE 与 DeepSeek 的协作；本脚本不代表 Milvus/Redis 已通过验收。"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import Settings
from app.database import KnowledgeBase, make_database
from app.generation import ChatService, DeepSeekLLM
from app.index import LocalIndex
from app.ingestion import Ingestion
from app.models import BGEModels
from app.retrieval import Retriever
from app.sessions import MemorySessions


def main():
    folder = Path("data/model-check")
    folder.mkdir(parents=True, exist_ok=True)
    settings = Settings(data_dir=folder, database_url="sqlite:///./data/model-check/app.db")
    database = make_database(settings)
    models, index = BGEModels(settings), LocalIndex()
    ingestion = Ingestion(settings, database, models, index)
    with database() as session:
        kb = KnowledgeBase(name="真实模型验证用示例库")
        session.add(kb)
        session.commit()
        kb_id = kb.id
    ingestion.submit(kb_id, "员工手册.md", Path("samples/员工手册.md").read_bytes())
    ingestion.process_one()
    retriever = Retriever(settings, database, models, index)
    chat = ChatService(database, retriever, MemorySessions(settings), DeepSeekLLM(settings))
    rows = []
    for question in ["正式员工每年有几天年假？", "试用期也可以吗？", "公司今年涨薪比例是多少？"]:
        events = []
        started = time.perf_counter()
        for frame in chat.stream(kb_id, "c" * 32, question):
            lines = frame.strip().splitlines()
            events.append({"event": lines[0][7:], "data": json.loads(lines[1][6:])})
        answer = "".join(item["data"]["text"] for item in events if item["event"] == "delta")
        rows.append({"question": question, "answer": answer, "events": events,
                     "elapsed_ms": round((time.perf_counter() - started) * 1000)})
        print(json.dumps({"question": question, "answer": answer, "finished": events[-1]["event"]}, ensure_ascii=False), flush=True)
    report = {"scope": "真实 BGE + DeepSeek；索引为本地适配器，会话为内存，未验证 Milvus/Redis", "rows": rows}
    Path("reports").mkdir(exist_ok=True)
    Path("reports/local-model-pipeline.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return int(any(row["events"][-1]["event"] != "done" for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
