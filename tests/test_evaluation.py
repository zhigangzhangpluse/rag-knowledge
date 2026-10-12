"""评测统计不能把未标注值当作正确结果，也不能把 false 当作缺失。"""
from scripts.evaluation.evaluate import summarize


def test_unrated_metrics_are_unknown():
    rows = [{"answerable": True, "recall": 0.5, "latency_ms": 100,
             "answer_correct": None, "citation_supported": [], "refusal_correct": None}]
    result = summarize(rows)
    assert result["recall_at_k"] == 0.5
    assert result["answer_correct_rate"] is None
    assert result["citation_accuracy"] is None
    assert result["refusal_accuracy"] is None


def test_human_false_ratings_count_as_failures():
    rows = [{"answerable": True, "recall": 1, "latency_ms": 100,
             "answer_correct": False, "citation_supported": [True, False], "refusal_correct": False}]
    result = summarize(rows)
    assert result["answer_correct_rate"] == 0
    assert result["citation_accuracy"] == 0.5
    assert result["refusal_accuracy"] == 0
