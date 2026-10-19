# ----------------------------------------------------------------------
# 阅读入口：定义四张关系表，以及创建数据库连接和事务会话的方法。
# ORM 把 Python 对象映射成数据库行。Mapped 是字段类型，mapped_column 定义列。主键唯一标识一行；外键表达表之间的关系；索引加速过滤。提交 commit 后数据才持久保存。
# ----------------------------------------------------------------------
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def new_id():
    return uuid4().hex


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ----------------------------------------------------------------------
# 先分清“知识库”与“数据库”：知识库是一组文档的业务容器。
# SQLite 是保存这些业务记录的数据库；Milvus 是保存可检索向量的数据库。
# 例如 kb_A 放员工手册，kb_B 放产品资料。这里一行 KnowledgeBase 代表一个知识库。
# Document 保存文件状态和有效版本，Chunk 保存分块正文和向量副本，Job 保存处理进度。
# 类似用法：电商里店铺是业务对象，MySQL 是存储工具；店铺不等于 MySQL。
# 面试问：隔离知识库是不是必须一库一张表？答：不一定，本项目通过 kb_id 过滤隔离数据。
# 追问：这样是否完成权限控制？答：没有。过滤负责范围，登录鉴权负责谁能访问这个范围。
# ----------------------------------------------------------------------
class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ----------------------------------------------------------------------
# active_version 就像“当前正式发布的是第几版”的指针。
# 新版本先处理，处理好再把指针从 1 改到 2；查询只使用与指针相同版本的分块。
# 这不是 SQLite 自动懂业务，而是程序把规则写进字段和查询条件。
# 代码示例（仅供阅读）：document.active_version = 2; session.commit()
# 面试问：为什么不能上传就删旧版？答：新文件解析或模型调用可能失败，旧版应能继续服务。
# ----------------------------------------------------------------------
class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kb_id: Mapped[str] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    active_version: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kb_id: Mapped[str] = mapped_column(String(32), index=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    heading: Mapped[str] = mapped_column(Text)
    location: Mapped[str] = mapped_column(String(200))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    vector: Mapped[list] = mapped_column(JSON)
    embedding_model: Mapped[str] = mapped_column(String(200))


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="ingest")
    version: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(20), default="queued")
    stage: Mapped[str] = mapped_column(String(50), default="等待处理")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ----------------------------------------------------------------------
# 事务可以理解成“这一组数据库改动一起交账”。
# session.add 是登记待写对象；flush 把 SQL 发出去；commit 才正式提交事务。
# 代码示例：with database() as session: ...；本项目写入处显式 session.commit()。
# 只写 with 并不表示退出时自动提交；尚未提交的变更会随会话结束而回滚。
# check_same_thread=False 允许连接跨线程使用，不代表多线程写入无需协调。
# SQLite 适合本机、小规模部署；写并发增加时可考虑 PostgreSQL，但需要迁移和验证。
# 面试问：SQLite 提交能同时保证 Milvus 成功吗？答：不能，它们不在同一个本地事务里。
# create_all 负责创建缺失表，不是自动升级旧表结构的迁移系统。
# ----------------------------------------------------------------------
def make_database(settings):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    options = {"check_same_thread": False, "timeout": 30} if settings.database_url.startswith("sqlite") else {}
    engine = create_engine(settings.database_url, connect_args=options)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
