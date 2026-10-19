# ----------------------------------------------------------------------
# 阅读入口：封装 Milvus 的建索引、写入、搜索和删除，另提供只用于演示的本地向量比较。
# 索引可以根据原始文档重新构建。Milvus 搜索先限制知识库、模型和有效版本，再做向量排序；返回结果还会核验 SQL 分块。upsert 是存在则更新、不存在则新增。
# ----------------------------------------------------------------------
import json
from functools import cached_property

import numpy as np


# ----------------------------------------------------------------------
# Milvus 做“拿问题向量找相近文档向量”；它不负责生成自然语言答案。
# 这里保存向量和 kb_id、doc_id、version 等过滤字段，正文与有效状态由 SQLite 管理。
# COSINE 衡量方向相似程度；不是回答正确率，相近也可能只是主题相近。
# 类似用法：FAISS 是常见向量索引库，Milvus 是数据库服务；持久化、过滤、部署方式需分别设计。
# 面试问：为什么 SQLite 也存向量？答：便于增量复用和恢复索引，代价是重复存储和更大的库文件。
# ----------------------------------------------------------------------
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

    # ----------------------------------------------------------------------
    # 先限定候选范围，再找向量近邻，避免其他知识库或旧版本抢占 Top-K。
    # 例如只允许 kb_A 的 doc_1:v2 和 doc_2:v1，就不能拿 doc_1:v1 来回答。
    # 过滤表达式的字符串值用 JSON 转义，不能直接把原始用户输入拼进表达式。
    # 类似用法：商品推荐也会先过滤下架商品，再按相关性排序。
    # 面试问：为什么向量库过滤之后还校验 ID？答：防御跨存储更新时的短暂不一致。
    # 当前按文档版本展开过滤条件；文档很多时表达式会变长，需要重新评估索引和版本设计。
    # ----------------------------------------------------------------------
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


# ----------------------------------------------------------------------
# 本地测试索引用 NumPy 对 SQLite 中已有向量做比较，不连接 Milvus。
# 单位长度向量的点积等于余弦相似度；未归一化时不能直接这样等同。
# 面试问：遍历计算和向量数据库一样快吗？答：不是，全量比较随数据量增长，适合小数据测试。
# ----------------------------------------------------------------------
class LocalIndex:

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
