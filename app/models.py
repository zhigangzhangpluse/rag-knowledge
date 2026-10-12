"""模型适配器：生产使用 BGE；测试替身只用于验证程序逻辑。"""
import hashlib
import re
from functools import cached_property

import numpy as np


class BGEModels:
    def __init__(self, settings):
        self.settings = settings
        self.name = settings.embedding_model

    @cached_property
    def embedder(self):
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(self.name, device=self.settings.model_device, cache_folder="models")

    @cached_property
    def reranker(self):
        from sentence_transformers import CrossEncoder
        return CrossEncoder(self.settings.reranker_model, device=self.settings.model_device, max_length=2048,
                            cache_folder="models/huggingface/hub")

    def encode(self, texts):
        return self.embedder.encode(texts, batch_size=8, normalize_embeddings=True, show_progress_bar=False).tolist()

    def scores(self, query, texts):
        import torch
        values = self.reranker.predict([(query, text) for text in texts], batch_size=4,
                                      activation_fn=torch.nn.Sigmoid(), show_progress_bar=False)
        return np.asarray(values).reshape(-1).tolist()


class DemoModels:
    """确定性的字符特征，不具有 BGE 的语义理解能力。"""
    name = "demo-character-hash-v1"

    def encode(self, texts):
        vectors = []
        for text in texts:
            vector = np.zeros(256, dtype=float)
            for token in re.findall(r"[\u4e00-\u9fff]|[a-z0-9]+", text.lower()):
                index = int(hashlib.sha256(token.encode()).hexdigest()[:8], 16) % 256
                vector[index] += 1
            norm = np.linalg.norm(vector)
            vectors.append((vector / max(norm, 1e-12)).tolist())
        return vectors

    def scores(self, query, texts):
        question = set(re.findall(r"[\u4e00-\u9fff]|[a-z0-9]+", query.lower()))
        return [len(question & set(re.findall(r"[\u4e00-\u9fff]|[a-z0-9]+", text.lower()))) / max(len(question), 1) for text in texts]
