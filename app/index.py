"""Milvus 仅保存可重建索引；SQLite 中的状态决定哪些分块可以被检索。"""
import json
from functools import cached_property

import numpy as np


class MilvusIndex:
    def __init__(self, settings):
        self.settings = settings
        self.collection = settings.milvus_collection

    @cached_property
    def client(self):
        from pymilvus import MilvusClient
        return MilvusClient(uri=self.settings.milvus_uri, timeout=20)

    def ensure(self, dimension):
        if not self.client.has_collection(self.collection):
            self.client.create_collection(collection_name=self.collection, dimension=dimension,
                                          primary_field_name="id", id_type="string", max_length=32,
                                          vector_field_name="vector", metric_type="COSINE", consistency_level="Strong")
        description = self.client.describe_collection(self.collection)
        vector_field = next(field for field in description["fields"] if field["name"] == "vector")
        if int(vector_field["params"]["dim"]) != dimension:
            raise ValueError("Milvus 向量维度与模型不一致，请使用新的 MILVUS_COLLECTION 并重新入库")

    def upsert(self, chunks):
        if not chunks:
            return
        self.ensure(len(chunks[0].vector))
        for start in range(0, len(chunks), 100):
            rows = [{"id": chunk.id, "vector": chunk.vector, "kb_id": chunk.kb_id,
                     "doc_id": chunk.doc_id, "version": chunk.version,
                     "embedding_model": chunk.embedding_model} for chunk in chunks[start:start + 100]]
            self.client.upsert(collection_name=self.collection, data=rows)

    def search(self, vector, chunks, limit):
        if not chunks:
            return []
        versions = sorted({(chunk.doc_id, chunk.version) for chunk in chunks})
        clauses = [f'(doc_id == {json.dumps(doc_id)} and version == {version})' for doc_id, version in versions]
        expression = f'kb_id == {json.dumps(chunks[0].kb_id)} and embedding_model == {json.dumps(chunks[0].embedding_model)} and (' + " or ".join(clauses) + ")"
        rows = self.client.search(collection_name=self.collection, data=[vector], filter=expression,
                                  limit=limit, output_fields=["id"], search_params={"metric_type": "COSINE"})
        return [row["id"] for row in rows[0]]

    def delete_document(self, doc_id):
        if self.client.has_collection(self.collection):
            self.client.delete(collection_name=self.collection, filter=f"doc_id == {json.dumps(doc_id)}")

    def delete_old_versions(self, doc_id, version):
        if self.client.has_collection(self.collection):
            self.client.delete(collection_name=self.collection,
                               filter=f"doc_id == {json.dumps(doc_id)} and version < {version}")

    def health(self):
        self.client.list_collections()


class LocalIndex:
    """演示/测试时直接比较数据库向量；不是 Milvus 的生产替代品。"""
    def upsert(self, chunks):
        pass

    def search(self, vector, chunks, limit):
        ranked = sorted(chunks, key=lambda chunk: float(np.dot(vector, chunk.vector)), reverse=True)
        return [chunk.id for chunk in ranked[:limit]]

    def delete_document(self, doc_id):
        pass

    def delete_old_versions(self, doc_id, version):
        pass

    def health(self):
        return None
