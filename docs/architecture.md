# 架构与模块职责

## 数据职责

| 组件 | 数据与职责 |
| --- | --- |
| SQLite | 知识库、文档、分块正文、任务和有效版本；决定候选资料范围 |
| Milvus | 文档块向量及知识库、文档、版本、模型标识；执行带过滤的向量检索 |
| Redis | 按知识库和会话 ID 保存最近 12 条消息，默认 TTL 为一天 |
| 文件目录 | 保存上传原文与可下载来源，提供重新解析的基础 |

## 业务模块

| 模块 | 职责 |
| --- | --- |
| app/config.py | 环境配置与参数校验 |
| app/database.py | SQLAlchemy 数据模型及事务会话 |
| app/parsing.py | 文档解析、清洗、标题识别与字符窗口分块 |
| app/models.py | BGE Embedding 与 Reranker 适配器 |
| app/index.py | Milvus 写入、检索过滤与索引删除 |
| app/ingestion.py | 持久任务、增量入库、版本切换、失败重试 |
| app/retrieval.py | 有效分块查询、BM25、RRF、重排序与去重 |
| app/generation.py | 问题改写、证据提示词、SSE 与引用编号检查 |
| app/sessions.py | Redis 会话读写和隔离 |
| app/main.py | API、应用生命周期与网页入口 |

## 上传与版本一致性

上传先登记任务，再解析并生成分块。内容哈希相同且模型一致的分块复用已有向量；改变的内容重新计算。SQLite 保存分块后写入 Milvus，成功后切换 active_version，再清理旧版本。失败更新保留旧有效版本，任务支持重试。

SQLite 事务只保护其内部修改，不构成跨 Milvus 的分布式事务。系统用明确的操作顺序、稳定分块 ID 和失败重试维持可恢复性。删除先让文档退出有效范围，再清理向量和文件。

## 检索与回答

会话历史用于补全当前问题。SQLite 选出有效分块；BGE 只重新向量化问题，Milvus 限定知识库、模型及有效版本进行检索。BM25 在同一有效范围运行，RRF 融合排名，Reranker 读取问题与候选内容并评分，过滤低分和重复哈希。选中的片段编号后交给 DeepSeek，生成完成后保存 Redis 历史。

## API 入口

| 路径 | 用途 |
| --- | --- |
| /api/knowledge-bases | 知识库列表与创建 |
| /api/knowledge-bases/{kb_id}/documents | 文档上传与列表 |
| /api/knowledge-bases/{kb_id}/chat | POST 问答，响应 text/event-stream |
| /api/health | Milvus、Redis 健康状态 |
| /docs | 完整 FastAPI 接口说明 |

SSE 事件包含 status、sources、delta、done 和 error。客户端按事件边界缓冲和解码，避免把网络分片当作完整消息。
