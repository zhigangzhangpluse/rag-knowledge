# ----------------------------------------------------------------------
# 阅读入口：管理上传与文档版本、持久化任务、后台处理、失败重试、删除同步。
# RLock 保护同一进程内的关键修改；FileLock 保证同数据目录只有一个 Worker。新版本先准备完成才切换 active_version。删除先标记业务不可见再清理索引。多个数据库之间没有自动分布式事务，正确顺序十分关键。
# ----------------------------------------------------------------------
import hashlib
import threading
from pathlib import Path

from filelock import FileLock
from sqlalchemy import delete, func, select

from app.database import Chunk, Document, Job, KnowledgeBase
from app.parsing import parse, split_blocks


# ----------------------------------------------------------------------
# 文档入库和聊天是两条流程。这里负责慢的准备工作，retrieval.py 负责使用成果。
# 总流程：存文件与任务 → 解析清洗分块 → 复用/生成向量 → 写索引 → 切换有效版本 → 清理旧版。
# SQLite 与 Milvus 无共同事务，因此用“先准备、后发布、失败可重试”的方式控制可见性。
# 面试问：这是分布式事务吗？答：不是，是应用层状态机与补偿式重试，需要容忍中间状态。
# RLock 协调进程内共享状态；FileLock 限制后台 worker 的进程竞争，二者保护范围不同。
# 这套实现不是分布式任务队列；多实例扩展时需要任务认领、租约和更完整的并发设计。
# ----------------------------------------------------------------------
class Ingestion:
    def __init__(self, settings, database, models, index):
        self.settings, self.database, self.models, self.index = settings, database, models, index
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.thread = None
        self.worker_lock = FileLock(settings.data_dir / "worker.lock", timeout=0)

    # ----------------------------------------------------------------------
    # 上传时先比较整个文件的哈希，未变更则不用再跑解析和模型。
    # 若文件变了，创建递增版本任务；不是马上覆盖当前可用版本。
    # 例如只改了一个标点：文件哈希会变化，但之后仍可复用其他未变分块的向量。
    # 面试问：文件哈希与分块哈希为什么都要？答：前者快速跳过整个文件，后者复用局部成果。
    # 文件写盘和 SQL 提交也不是同一事务，极端失败可能留下未被任务引用的文件，需要运维清理。
    # ----------------------------------------------------------------------
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

    # ----------------------------------------------------------------------
    # 增量向量化不是“随便找到一条旧向量就用”。复用条件包含同文档、同模型、相同内容哈希。
    # 例子：旧版有 A、B、C 三块，新版 A、B、D；A/B 复用，D 才调用 encode。
    # 插入的新版本分块有确定 ID，upsert 可以覆盖同 ID，减少重试时重复写入。
    # 只有新向量写入成功，才提交 active_version 指向新版；然后再清掉旧版索引和分块。
    # 面试问：切版后清理失败怎么办？答：旧数据可能残留，但有效版本过滤阻止它参与新查询；再重试清理。
    # 幂等是“重复执行仍得到预期最终状态”，不是“保证只运行一次”。
    # ----------------------------------------------------------------------
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

    # ----------------------------------------------------------------------
    # 删除分两步：先逻辑标记让资料退出检索，再后台删除索引、文件和分块。
    # 类似用法：下架商品先不让用户看到，再处理缓存、图片等资源清理。
    # 路径先 resolve 再检查是否在 data_dir 内，避免错误记录让清理任务删除项目外文件。
    # 面试问：用户点删除后立即磁盘清空吗？答：不是，接口提交后台任务，清理可能重试。
    # 删除与已开始的回答可能并发；不能把逻辑删除说成撤回已经发送给用户的文本。
    # ----------------------------------------------------------------------
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

    # ----------------------------------------------------------------------
    # 后台线程负责消费已持久化任务，进程重启后把未完成的 running 任务重新排队。
    # Event 用来唤醒或停止等待，避免后台线程一直空转占用 CPU。
    # 类似用法：更大规模系统会用 Celery 等队列，但迁移时仍要保留幂等与失败恢复设计。
    # 面试问：为什么不只用一个内存列表？答：程序崩溃后内存任务丢失，SQLite 任务记录能帮助恢复。
    # ----------------------------------------------------------------------
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
