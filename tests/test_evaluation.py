# ----------------------------------------------------------------------
# 阅读入口：检查评测汇总口径，保证未评审显示未知、人工判错计入失败。
# None 表示未知，False 表示已判断为错误；统计时不能用简单的真假判断混淆两者。
# 评测代码本身也会算错，需要用已知答案验证统计口径。
# None 代表没有标注，False 代表标了但错误，二者不能混成同一种分母。
# 面试问：为什么区分这两个值？答：把缺失标注当错误或成功，都会让准确率失真。
# ----------------------------------------------------------------------
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
