# ----------------------------------------------------------------------
# 阅读入口：对相同测试题比较三种检索策略，生成待人工审阅的回答与引用报告，并汇总人工标注。
# Recall@K 在此按预先标注证据的覆盖率计算。回答正确性和引用语义支持须人工审核，缺少审核时保留 null。延迟包含问题改写和可选生成，不等于只测检索模型速度。
# 评测像分科考试：Recall@K 看资料有没有找对，回答正确率看最终结论，引用准确率看证据支撑。
# 不能用引用编号存在冒充引用准确，也不能用模型自己打分直接冒充独立人工标注。
# 本项目用期望证据文本匹配计算召回，结果依赖标注粒度；未评分字段保留空值，不当作零分。
# 代码示例：同一份数据分别跑 dense、hybrid、hybrid_rerank，比新增模块的收益与延迟。
# 面试问：如何调参？答：固定测试集和模型，逐项比较分块、召回数、精排数，另留验证集避免过拟合。
# ----------------------------------------------------------------------
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import Settings
from app.main import create_app
from app.retrieval import active_chunks


def percentile(values, fraction):
    values = sorted(values)
    return values[min(len(values) - 1, round((len(values) - 1) * fraction))] if values else None


def summarize(rows):
    answerable = [row for row in rows if row["answerable"]]
    rated = [row for row in rows if isinstance(row.get("answer_correct"), bool)]
    citations = [flag for row in rows for flag in row.get("citation_supported", []) if isinstance(flag, bool)]
    refusals = [row["refusal_correct"] for row in rows if isinstance(row.get("refusal_correct"), bool)]
    return {"questions": len(rows), "recall_at_k": statistics.mean(row["recall"] for row in answerable) if answerable else None,
            "answer_correct_rate": statistics.mean(row["answer_correct"] for row in rated) if rated else None,
            "answer_rated_count": len(rated), "citation_accuracy": statistics.mean(citations) if citations else None,
            "citation_rated_count": len(citations), "latency_p50_ms": percentile([row["latency_ms"] for row in rows], 0.5),
            "refusal_accuracy": statistics.mean(refusals) if refusals else None, "refusal_rated_count": len(refusals),
            "latency_p95_ms": percentile([row["latency_ms"] for row in rows], 0.95)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kb", help="已导入 samples/员工手册.md 的知识库 ID")
    parser.add_argument("--dataset", default="eval/dataset.jsonl")
    parser.add_argument("--generate", action="store_true", help="生成回答供人工评审，真实模式会消耗 API 额度")
    parser.add_argument("--ratings", help="汇总已人工填写 answer_correct 与 citation_supported 的报告")
    parser.add_argument("--output", default="reports/evaluation.json")
    args = parser.parse_args()
    if args.ratings:
        report = json.loads(Path(args.ratings).read_text(encoding="utf-8"))
        for group in report["strategies"].values():
            group["summary"] = summarize(group["rows"])
    else:
        if not args.kb:
            parser.error("必须指定 --kb，或使用 --ratings 汇总人工评审")
        settings = Settings()
        services = create_app(settings, start_worker=False).state.services
        dataset = [json.loads(line) for line in Path(args.dataset).read_text(encoding="utf-8").splitlines() if line.strip()]
        chunks = active_chunks(services.database, args.kb, services.models.name)
        if not chunks:
            raise ValueError("该知识库没有当前模型的有效分块，请先入库")
        report = {"mode": settings.app_mode, "model": services.models.name, "k": settings.context_k,
                  "note": "Recall@K 以固定业务证据条目的覆盖率计算；未人工标注的正确率和引用准确率为 null。延迟包含改写及可选生成。",
                  "strategies": {}}
        for strategy in ["dense", "hybrid", "hybrid_rerank"]:
            rows = []
            for case in dataset:
                if any(not any(evidence in chunk.text for chunk in chunks) for evidence in case["evidence"]):
                    raise ValueError(f"测试证据不在知识库中：{case['id']}，请检查样本文件与分块策略")
                started = time.perf_counter()
                query = services.chat.llm.rewrite(case["question"], case.get("history", []))
                hits = services.retriever.retrieve(args.kb, query, strategy=strategy)
                sources = services.chat.sources(hits)
                matched = sum(any(evidence in item["text"] for item in sources) for evidence in case["evidence"])
                recall = matched / len(case["evidence"]) if case["evidence"] else None
                answer = None
                if args.generate:
                    answer = "".join(services.chat.llm.stream(case["question"], query, sources)) if sources else "当前知识库证据不足，无法确定。"
                rows.append({**case, "rewritten_query": query, "recall": recall, "sources": sources,
                             "generated_answer": answer, "latency_ms": round((time.perf_counter() - started) * 1000),
                             "answer_correct": None, "citation_supported": [],
                             "refusal_correct": None, "review_note": "请人工核对每项结论与引用是否被原文支持"})
            report["strategies"][strategy] = {"summary": summarize(rows), "rows": rows}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({name: group["summary"] for name, group in report["strategies"].items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
