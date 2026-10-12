"""关系数据库保存业务状态；向量索引不是文档状态的唯一依据。"""
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


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


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


def make_database(settings):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    options = {"check_same_thread": False, "timeout": 30} if settings.database_url.startswith("sqlite") else {}
    engine = create_engine(settings.database_url, connect_args=options)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
