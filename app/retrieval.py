# ----------------------------------------------------------------------
# 阅读入口：实现从业务有效分块到向量/BM25/RRF/重排序/去重的完整检索链。
# 不要把两种不同量纲的检索分数直接相加。RRF 使用名次融合。BM25 每次只看本知识库当前有效分块，避免删除和更新后关键词结果滞后。性能优化应保留这些过滤约束。
# ----------------------------------------------------------------------
from dataclasses import dataclass

import jieba
import numpy as np
from rank_bm25 import BM25Okapi
from sqlalchemy import select

from app.database import Chunk, Document


@dataclass
class Hit:
    chunk: Chunk
    score: float
    rrf_score: float


# ----------------------------------------------------------------------
# 问答开始先查“哪些片段现在允许用”，不是把知识库重新向量化。
# 条件同时包含知识库、文档状态、有效版本、模型名称，少任何一个都可能混入错误数据。
# 例子：文档 active_version=2，则 version=1 的分块即使还没清理，也不会进入本次候选。
# 面试问：SQLite 负责什么？答：用结构化条件确定有效数据；语义相似度交给向量检索。
# 这是读取时的状态检查，不是覆盖整轮回答的数据库快照；并发更新仍需考虑一致性边界。
# ----------------------------------------------------------------------
def active_chunks(database, kb_id, model_name):
    with database() as session:
        query = select(Chunk).join(Document, Chunk.doc_id == Document.id).where(
            Chunk.kb_id == kb_id, Document.kb_id == kb_id, Document.status != "deleted",
            Chunk.version == Document.active_version, Chunk.embedding_model == model_name,
        ).order_by(Chunk.doc_id, Chunk.ordinal)
        return list(session.scalars(query))


def tokens(text):
    return [word.lower() for word in jieba.lcut(text) if word.strip() and any(c.isalnum() for c in word)]


# ----------------------------------------------------------------------
# RRF 是排名融合公式，不是模型，也不需要训练。
# 两路分数单位不同：余弦相似度与 BM25 分数不能想当然直接相加，所以改用名次计分。
# 公式：每一路贡献 1 / (60 + 名次)，名次从 1 开始，同一候选的贡献相加。
# 例子：A 在两路都第 2，分数 2/62；B 只在一路第 1，分数 1/61，A 会更靠前。
# 代码示例：rrf([['A', 'B'], ['B', 'C']])，B 因为两路都出现而获得两份贡献。
# 60 是平滑常数，不是 Top-K，也不是经验上永远最优的参数。
# 面试问：RRF 和 Reranker 区别？答：RRF 看名次合并名单，Reranker 读问题与原文重打分。
# ----------------------------------------------------------------------
def rrf(rankings, constant=60):
    scores = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(dict.fromkeys(ranking), 1):
            scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (constant + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


class Retriever:
    def __init__(self, settings, database, models, index):
        self.settings, self.database, self.models, self.index = settings, database, models, index

    # ----------------------------------------------------------------------
    # 一轮检索：查有效块 → 编码问题 → 向量召回 + BM25 → RRF → 精排 → 去重取证据。
    # 向量擅长找近义表达；BM25 擅长关键词，如错误码 E102、产品型号、专有名词。
    # BM25 会考虑词频、词的稀有程度和文档长度；中文先用 jieba 分词，分错词也会影响效果。
    # 本实现只保留 BM25 正分候选；小语料或高频词可能无候选，不能理解成关键词一定没出现。
    # recall_k 是每路召回数量，rerank_k 是送去精排的候选数量，context_k 是最终证据数量。
    # 例子：每路取 30 → 融合取 20 去精排 → 最多留 6 个给生成模型；不是直接把 60 段塞进提示词。
    # 类似方案：只有向量可当基线，加入 BM25 看专有名词召回，再加精排比较收益和时延。
    # 面试问：加了 Reranker 能补回没召回的资料吗？答：不能，它只能在已有候选里排序。
    # 当前每次请求重建 BM25，并加载全部有效块，适合小规模；大规模应维护持久索引和增量更新。
    # 无精排策略使用占位分数 1.0，不是真实置信度；不要拿它和精排分数比较“模型准确率”。
    # ----------------------------------------------------------------------
    def retrieve(self, kb_id, query, strategy="hybrid_rerank"):
        chunks = active_chunks(self.database, kb_id, self.models.name)
        if not chunks:
            return []
        by_id = {chunk.id: chunk for chunk in chunks}
        texts = {chunk.id: chunk.heading + "\n" + chunk.text for chunk in chunks}
        dense = self.index.search(self.models.encode([query])[0], chunks, self.settings.recall_k)
        dense = [chunk_id for chunk_id in dense if chunk_id in by_id]
        rankings = [dense]
        if strategy != "dense":
            corpus = [tokens(texts[chunk.id]) or ["空白"] for chunk in chunks]
            bm25 = BM25Okapi(corpus)
            lexical_scores = bm25.get_scores(tokens(query))
            order = np.argsort(-lexical_scores, kind="stable")
            lexical = [chunks[i].id for i in order if lexical_scores[i] > 0][:self.settings.recall_k]
            rankings.append(lexical)
        merged = rrf(rankings)[:self.settings.rerank_k]
        if not merged:
            return []
        scores = self.models.scores(query, [texts[chunk_id] for chunk_id, _ in merged]) if strategy == "hybrid_rerank" else [1.0] * len(merged)
        hits = [Hit(by_id[chunk_id], score, fused) for (chunk_id, fused), score in zip(merged, scores)]
        hits.sort(key=lambda hit: (hit.score, hit.rrf_score), reverse=True)
        selected, fingerprints = [], set()
        for hit in hits:
            if hit.score < self.settings.min_rerank_score or hit.chunk.content_hash in fingerprints:
                continue
            fingerprints.add(hit.chunk.content_hash)
            selected.append(hit)
            if len(selected) == self.settings.context_k:
                break
        return selected
