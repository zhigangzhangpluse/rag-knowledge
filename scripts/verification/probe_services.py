"""按需检查真实外部服务；只输出状态，不输出凭据。"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import Settings
from app.generation import DeepSeekLLM
from app.index import MilvusIndex
from app.models import BGEModels
from app.sessions import RedisSessions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true", help="真实调用 DeepSeek，消耗少量额度")
    parser.add_argument("--models", action="store_true", help="下载并运行 BGE 模型")
    parser.add_argument("--infra", action="store_true", help="检查 Milvus 与 Redis")
    args = parser.parse_args()
    settings = Settings()
    checks = []
    if args.infra:
        checks.extend([("milvus", lambda: MilvusIndex(settings).health()), ("redis", lambda: RedisSessions(settings).health())])
    if args.llm:
        checks.append(("deepseek", lambda: DeepSeekLLM(settings).model.invoke("只回复 OK")))
    if args.models:
        models = BGEModels(settings)
        checks.extend([("bge_embedding", lambda: models.encode(["年假每年五天"])),
                       ("bge_reranker", lambda: models.scores("年假几天", ["年假每年五天", "今天天气晴朗"]))])
    output = Path("reports/local-services.json")
    report = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    failed = False
    for name, operation in checks:
        try:
            operation()
            report[name] = {"status": "ok"}
        except Exception as exc:
            report[name] = {"status": "failed", "error_type": type(exc).__name__}
            failed = True
        report[name]["checked_at"] = datetime.now(timezone.utc).isoformat()
        print(json.dumps({name: report[name]}, ensure_ascii=False), flush=True)
    Path("reports").mkdir(exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
