"""持久化任务队列：先构建新版本，再切换可见版本，最后清理旧索引。"""
import hashlib
import threading
from pathlib import Path

from filelock import FileLock
from sqlalchemy import delete, func, select

from app.database import Chunk, Document, Job, KnowledgeBase
from app.parsing import parse, split_blocks


class Ingestion:
    def __init__(self, settings, database, models, index):
        self.settings, self.database, self.models, self.index = settings, database, models, index
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.thread = None
        self.worker_lock = FileLock(settings.data_dir / "worker.lock", timeout=0)

    def submit(self, kb_id, name, content, doc_id=None):
        suffix = Path(name).suffix.lower()
        if suffix not in {".md", ".markdown", ".pdf", ".docx"}:
            raise ValueError("文件类型不支持：请上传 PDF、DOCX 或 Markdown")
        digest = hashlib.sha256(content).hexdigest()
        with self.lock, self.database() as session:
            if not session.get(KnowledgeBase, kb_id):
                raise LookupError("知识库不存在")
            document = session.get(Document, doc_id) if doc_id else None
            if doc_id and (not document or document.kb_id != kb_id or document.status == "deleted"):
                raise LookupError("文档不存在")
            if document:
                pending = session.scalar(select(Job).where(Job.doc_id == document.id, Job.status.in_(["queued", "running"])))
                if pending:
                    raise ValueError("文档还有未完成任务，请完成或重试后再更新")
                if document.content_hash == digest and document.active_version:
                    return {"doc_id": document.id, "unchanged": True, "job_id": None}
            else:
                document = Document(kb_id=kb_id, name=Path(name).name)
                session.add(document)
                session.flush()
            previous = session.scalar(select(func.max(Job.version)).where(Job.doc_id == document.id)) or 0
            version = previous + 1
            folder = self.settings.data_dir / "uploads" / document.id
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{version}{suffix}"
            path.write_bytes(content)
            job = Job(doc_id=document.id, version=version, path=str(path), content_hash=digest)
            session.add(job)
            session.commit()
            return {"doc_id": document.id, "job_id": job.id, "unchanged": False}

    def delete_document(self, kb_id, doc_id):
        with self.lock, self.database() as session:
            document = session.get(Document, doc_id)
            if not document or document.kb_id != kb_id:
                raise LookupError("文档不存在")
            if document.status == "deleted":
                job = session.scalar(select(Job).where(Job.doc_id == doc_id, Job.kind == "delete").order_by(Job.created_at.desc()))
                return {"job_id": job.id if job else None}
            document.status = "deleted"
            for job in session.scalars(select(Job).where(Job.doc_id == doc_id, Job.status.in_(["queued", "running"]))):
                job.status = "cancelled"
            job = Job(doc_id=doc_id, kind="delete", version=document.active_version)
            session.add(job)
            session.commit()
            return {"job_id": job.id}

    def retry(self, job_id):
        with self.lock, self.database() as session:
            job = session.get(Job, job_id)
            if not job:
                raise LookupError("任务不存在")
            if job.status != "failed":
                raise ValueError("只有失败任务可以重试")
            document = session.get(Document, job.doc_id)
            if job.kind == "ingest" and (document.status == "deleted" or document.active_version > job.version):
                raise ValueError("文档已删除或已有更新的版本，不能重试旧任务")
            pending = session.scalar(select(Job).where(Job.doc_id == job.doc_id, Job.status.in_(["queued", "running"])))
            if pending:
                raise ValueError("请等待当前任务完成")
            job.status, job.error, job.stage = "queued", "", "等待重试"
            session.commit()

    def stage(self, job_id, name):
        with self.database() as session:
            job = session.get(Job, job_id)
            if job.status == "cancelled":
                return False
            job.stage = name
            session.commit()
            return True

    def process_one(self):
        with self.lock, self.database() as session:
            job = session.scalar(select(Job).where(Job.status == "queued").order_by(Job.created_at))
            if not job:
                return False
            job.status = "running"
            session.commit()
            job_id = job.id
        try:
            if job.kind == "delete":
                self.remove(job)
            else:
                self.ingest(job)
            with self.database() as session:
                record = session.get(Job, job_id)
                if record.status != "cancelled":
                    record.status, record.stage = "completed", "处理完成"
                session.commit()
        except Exception as exc:
            with self.database() as session:
                record = session.get(Job, job_id)
                if record.status != "cancelled":
                    record.status = "failed"
                    record.error = f"{type(exc).__name__}：处理失败，请检查依赖服务、文件格式和配置后重试"
                    if record.stage == "解析与分块" and isinstance(exc, ValueError):
                        record.error = str(exc)[:300]
                session.commit()
        return True

    def ingest(self, job):
        if not self.stage(job.id, "解析与分块"):
            return
        pieces = split_blocks(parse(job.path), self.settings.chunk_size, self.settings.chunk_overlap)
        with self.database() as session:
            document = session.get(Document, job.doc_id)
            kb_id = document.kb_id
            cached = {chunk.content_hash: chunk.vector for chunk in session.scalars(
                select(Chunk).where(Chunk.doc_id == job.doc_id, Chunk.embedding_model == self.models.name))}
        if not self.stage(job.id, "生成向量（首次运行可能下载模型）"):
            return
        missing = {piece["content_hash"]: piece["heading"] + "\n" + piece["text"] for piece in pieces if piece["content_hash"] not in cached}
        if missing:
            cached.update(zip(missing.keys(), self.models.encode(list(missing.values()))))
        with self.lock, self.database() as session:
            record = session.get(Job, job.id)
            document = session.get(Document, job.doc_id)
            if record.status == "cancelled" or document.status == "deleted":
                return
            session.execute(delete(Chunk).where(Chunk.doc_id == job.doc_id, Chunk.version == job.version))
            chunks = [Chunk(id=hashlib.sha256(f"{job.doc_id}:{job.version}:{i}".encode()).hexdigest()[:32], kb_id=kb_id, doc_id=job.doc_id, version=job.version,
                            ordinal=i, vector=cached[piece["content_hash"]], embedding_model=self.models.name,
                            **piece) for i, piece in enumerate(pieces)]
            session.add_all(chunks)
            session.commit()
        if not self.stage(job.id, "写入向量索引"):
            return
        self.index.upsert(chunks)
        with self.lock, self.database() as session:
            document = session.get(Document, job.doc_id)
            record = session.get(Job, job.id)
            if document.status == "deleted" or record.status == "cancelled":
                return
            document.active_version = job.version
            document.content_hash = job.content_hash
            document.status = "ready"
            session.commit()
        self.stage(job.id, "清理旧版本索引")
        self.index.delete_old_versions(job.doc_id, job.version)
        with self.database() as session:
            session.execute(delete(Chunk).where(Chunk.doc_id == job.doc_id, Chunk.version < job.version))
            session.commit()

    def remove(self, job):
        self.stage(job.id, "清理索引与原文")
        self.index.delete_document(job.doc_id)
        with self.database() as session:
            paths = list(session.scalars(select(Job.path).where(Job.doc_id == job.doc_id, Job.path != "")))
            for path in paths:
                resolved = Path(path).resolve()
                if not resolved.is_relative_to(self.settings.data_dir.resolve()):
                    raise ValueError("拒绝清理数据目录以外的路径")
                resolved.unlink(missing_ok=True)
            session.execute(delete(Chunk).where(Chunk.doc_id == job.doc_id))
            session.commit()

    def start(self):
        self.worker_lock.acquire()
        with self.database() as session:
            for job in session.scalars(select(Job).where(Job.status == "running")):
                job.status, job.stage = "queued", "恢复中断任务"
            session.commit()
        self.thread = threading.Thread(target=self.run, daemon=True, name="ingestion-worker")
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            if not self.process_one():
                self.stop.wait(1)

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=10)
            if not self.thread.is_alive():
                self.worker_lock.release()
