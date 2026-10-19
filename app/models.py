# ----------------------------------------------------------------------
# 阅读入口：统一 Embedding 和 Reranker 的调用接口，隔离真实 BGE 与演示替身。
# cached_property 表示第一次调用才创建模型，后续复用，避免每次请求重新加载权重。BGE 编码器把一条文本转成向量；CrossEncoder 同时读问题和文本并评分。演示模型只有字符匹配能力。
# ----------------------------------------------------------------------
import hashlib
import re
from functools import cached_property

import numpy as np


# ----------------------------------------------------------------------
# 模型关系先记住：BGE 是模型系列，Embedding 和 Reranker 是两种工作。
# Embedding 把文本单独变成数字数组，适合提前计算、建索引和快速寻找近邻。
# Reranker 把“问题 + 候选原文”一起阅读，判断这两段是否相关，适合少量候选精排。
# 类比：Embedding 先在图书馆找几十本可能相关的书，Reranker 再逐本看内容排顺序。
# 本项目 BGE-M3 使用 dense（稠密）向量；模型虽支持其他表示，这里并没有全部启用。
# BM25 是 retrieval.py 中另外实现的一路关键词召回，不是这里的 BGE 稀疏表示。
# 代码示例（仅供阅读）：vectors = models.encode(['员工年假五天', '年假有几天？'])
# 返回两个等长数组；数组本身不是答案，也不能按某一维直接解释成某个汉字。
# 面试问：每轮聊天都重新向量化文档吗？答：不。文档入库时算，查询时只算问题向量。
# 本项目没有问题向量缓存，因此同一个问题重复问，也会再次编码这个问题。
# ----------------------------------------------------------------------
class BGEModels:
    def __init__(self, settings):
        self.settings = settings
        self.name = settings.embedding_model

    # ----------------------------------------------------------------------
    # 本地模型与不同厂商接口怎么选？不是比较“谁名字大”，而是比较任务效果和成本。
    # 1. BAAI BGE-M3：这里本地运行，dense 输出 1024 维；需要下载权重和承担 CPU/GPU 内存成本。
    # 2. OpenAI Embeddings：远程 API，可选择模型及支持的输出维度；要处理密钥、网络和调用费用。
    # 3. 阿里云百炼 Embedding：也可使用远程 API；模型、区域地址、维度选项要按具体版本核对。
    # 4. Cohere Embed：部分版本要求区分 search_document 与 search_query，不能随便省略输入类型。
    # 效果要用自己的中文业务集测：召回率、时延、成本、隐私要求，没有通用的“第一名”。
    # 适配器伪代码（remote_embed 是你自己实现的接口，不是某家 SDK 的固定函数）：
    #     def encode(texts):
    #         response = remote_embed(texts, model=chosen_model)
    #         return extract_vectors_in_input_order(response)
    # 还需要保证文档与问题使用同一模型及正确的任务参数；厂商返回格式要在适配器内统一。
    # 换模型时即使维度相同，也不能把不同向量空间混着搜索；应建立新集合并重建文档向量。
    # 面试问：改一个模型名称就能切任意厂商吗？答：不能，还需适配协议、输入类型、输出和异常。
    # cached_property 缓存的是模型对象，避免重复加载权重；不是缓存每段文本的计算结果。
    # 官方资料（核对日期 2026-10-17；版本支持以文档为准）：
    # https://huggingface.co/BAAI/bge-m3
    # https://developers.openai.com/api/docs/guides/embeddings
    # https://www.alibabacloud.com/help/en/model-studio/text-embedding-synchronous-api
    # https://docs.cohere.com/v2/reference/embed
    # ----------------------------------------------------------------------
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

    # ----------------------------------------------------------------------
    # 交叉编码器精排：每个问题和候选文本配成一对，重新做一次相关性判断。
    # 例如 [('年假几天？', '年假五天'), ('年假几天？', '机房周末维护')]，期望第一对分数更高。
    # 这一步读原文，不是再比一次已存的向量距离；候选越多，耗时通常越长。
    # Sigmoid 把输出压到 0~1，但 0.8 不等于“答案有 80% 概率正确”。阈值需要业务集校准。
    # max_length 会限制输入长度，超过后截断，重要信息在尾部时可能影响排序。
    # 面试问：为什么不全库都用 Reranker？答：逐对阅读太贵，先召回缩小范围再精排。
    # ----------------------------------------------------------------------
    def scores(self, query, texts):
        import torch
        values = self.reranker.predict([(query, text) for text in texts], batch_size=4,
                                      activation_fn=torch.nn.Sigmoid(), show_progress_bar=False)
        return np.asarray(values).reshape(-1).tolist()


# ----------------------------------------------------------------------
# 测试替身：用字符特征造一个稳定向量，让自动化测试无需下载模型。
# 同样提供 encode / scores 方法，所以检索业务可以用相同调用方式运行。
# 类似用法：支付测试用假支付网关，邮件测试用假发信器，这叫依赖替换。
# 面试问：这些测试通过能证明真实 BGE 召回好吗？答：不能，只能证明相关业务流程符合预期。
# 这里字符散列碰撞很常见，也没有真正的语义理解，不能拿它的效果当生产模型效果。
# ----------------------------------------------------------------------
class DemoModels:

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
