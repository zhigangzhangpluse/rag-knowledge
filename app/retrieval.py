"""向量召回与中文 BM25 → RRF → BGE 重排序 → 去重。"""
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


def active_chunks(database, kb_id, model_name):
    with database() as session:
        query = select(Chunk).join(Document, Chunk.doc_id == Document.id).where(
            Chunk.kb_id == kb_id, Document.kb_id == kb_id, Document.status != "deleted",
            Chunk.version == Document.active_version, Chunk.embedding_model == model_name,
        ).order_by(Chunk.doc_id, Chunk.ordinal)
        return list(session.scalars(query))


def tokens(text):
    return [word.lower() for word in jieba.lcut(text) if word.strip() and any(c.isalnum() for c in word)]


def rrf(rankings, constant=60):
    scores = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(dict.fromkeys(ranking), 1):
            scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (constant + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


class Retriever:
    def __init__(self, settings, database, models, index):
        self.settings, self.database, self.models, self.index = settings, database, models, index

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
