# ----------------------------------------------------------------------
# 阅读入口：组装各模块并暴露 HTTP 接口，同时提供静态操作页面。
# FastAPI 装饰器把 URL 和处理函数绑定。Pydantic 限制输入长度和会话 ID 格式。FileResponse 返回文件，StreamingResponse 返回迭代器产生的数据。默认本机使用；知识库 ID 不是登录凭证。
# ----------------------------------------------------------------------
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import Settings
from app.database import Chunk, Document, Job, KnowledgeBase, make_database
from app.generation import ChatService, DeepSeekLLM, DemoLLM
from app.index import LocalIndex, MilvusIndex
from app.ingestion import Ingestion
from app.models import BGEModels, DemoModels
from app.retrieval import Retriever
from app.sessions import MemorySessions, RedisSessions


class KBInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ChatInput(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    session_id: str = Field(default_factory=lambda: uuid4().hex, pattern=r"^[a-f0-9]{32}$")


# ----------------------------------------------------------------------
# 应用工厂把数据库、模型、索引、历史存储组装到一起，像把零件接成机器。
# 测试时换成替身，生产时接 BGE/Milvus/Redis，接口层不必复制两套业务。
# FastAPI 校验请求格式；业务服务处理入库和问答；页面负责交互，这是职责分工。
# async 适合等待 I/O，不会自动让 CPU 密集的模型推理变快，阻塞调用要考虑线程或任务队列。
# 本地 Origin 检查不等于用户认证：无 Origin 的客户端仍可能访问，公开部署要补充鉴权。
# 面试问：上传为什么返回 202？答：已经受理后台任务，不表示解析和向量化已经完成。
# 流式请求一旦发出响应头，后续失败通常靠 SSE error 事件说明，不能再改成普通 HTTP 错误。
# 127.0.0.1 表示运行服务那台电脑自身；公开源代码不会自动获得一个公网服务地址。
# ----------------------------------------------------------------------
def create_app(settings=None, start_worker=True):
    settings = settings or Settings()
    database = make_database(settings)
    real = settings.app_mode == "production"
    models = BGEModels(settings) if real else DemoModels()
    index = MilvusIndex(settings) if real else LocalIndex()
    sessions = RedisSessions(settings) if real else MemorySessions(settings)
    llm = DeepSeekLLM(settings) if real else DemoLLM()
    ingestion = Ingestion(settings, database, models, index)
    retriever = Retriever(settings, database, models, index)
    chat = ChatService(database, retriever, sessions, llm)

    @asynccontextmanager
    async def lifespan(application):
        if start_worker:
            ingestion.start()
        yield
        ingestion.close()

    application = FastAPI(title="知源 · RAG 知识问答", version="0.1.0", lifespan=lifespan)
    application.state.services = SimpleNamespace(settings=settings, database=database, models=models,
                                                 index=index, sessions=sessions, ingestion=ingestion,
                                                 retriever=retriever, chat=chat)

    @application.middleware("http")
    async def local_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "不允许跨站访问本机知识库"}, status_code=403)
        return await call_next(request)

    @application.exception_handler(LookupError)
    async def missing_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @application.exception_handler(ValueError)
    async def invalid_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    def require_kb(kb_id):
        with database() as session:
            if not session.get(KnowledgeBase, kb_id):
                raise LookupError("知识库不存在")

    def require_job(kb_id, job_id):
        with database() as session:
            job = session.get(Job, job_id)
            document = session.get(Document, job.doc_id) if job else None
            if not document or document.kb_id != kb_id:
                raise LookupError("任务不存在")
            return job

    @application.get("/api/health")
    def health():
        checks = {}
        for name, component in [("vector_store", index), ("sessions", sessions)]:
            try:
                component.health()
                checks[name] = "ok"
            except Exception as exc:
                checks[name] = type(exc).__name__
        return {"mode": settings.app_mode, "checks": checks, "llm_model": settings.llm_model,
                "embedding_model": models.name, "note": "演示模式不调用真实模型" if not real else "健康检查不消耗模型 API 额度"}

    @application.get("/api/knowledge-bases")
    def list_kbs():
        with database() as session:
            return [{"id": kb.id, "name": kb.name} for kb in session.scalars(select(KnowledgeBase).order_by(KnowledgeBase.created_at))]

    @application.post("/api/knowledge-bases", status_code=201)
    def create_kb(body: KBInput):
        if not body.name.strip():
            raise ValueError("知识库名称不能为空")
        with database() as session:
            kb = KnowledgeBase(name=body.name.strip())
            session.add(kb)
            session.commit()
            return {"id": kb.id, "name": kb.name}

    @application.get("/api/knowledge-bases/{kb_id}/documents")
    def list_documents(kb_id: str):
        require_kb(kb_id)
        with database() as session:
            documents = session.scalars(select(Document).where(Document.kb_id == kb_id, Document.status != "deleted"))
            return [{"id": doc.id, "name": doc.name, "version": doc.active_version, "status": doc.status} for doc in documents]

    async def read_upload(file):
        content = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
        await file.close()
        if len(content) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(413, "文件超过上传大小限制")
        if not content:
            raise ValueError("不能上传空文件")
        return content

    @application.post("/api/knowledge-bases/{kb_id}/documents", status_code=202)
    async def upload(kb_id: str, file: UploadFile = File(...)):
        require_kb(kb_id)
        return ingestion.submit(kb_id, file.filename or "document", await read_upload(file))

    @application.put("/api/knowledge-bases/{kb_id}/documents/{doc_id}", status_code=202)
    async def update_document(kb_id: str, doc_id: str, file: UploadFile = File(...)):
        return ingestion.submit(kb_id, file.filename or "document", await read_upload(file), doc_id)

    @application.delete("/api/knowledge-bases/{kb_id}/documents/{doc_id}", status_code=202)
    def delete_document(kb_id: str, doc_id: str):
        return ingestion.delete_document(kb_id, doc_id)

    @application.get("/api/knowledge-bases/{kb_id}/jobs")
    def list_jobs(kb_id: str):
        require_kb(kb_id)
        with database() as session:
            jobs = session.scalars(select(Job).join(Document).where(Document.kb_id == kb_id).order_by(Job.created_at.desc()).limit(30))
            return [{"id": job.id, "doc_id": job.doc_id, "kind": job.kind, "status": job.status,
                     "stage": job.stage, "error": job.error} for job in jobs]

    @application.post("/api/knowledge-bases/{kb_id}/jobs/{job_id}/retry")
    def retry_job(kb_id: str, job_id: str):
        require_job(kb_id, job_id)
        ingestion.retry(job_id)
        return {"status": "queued"}

    @application.get("/api/knowledge-bases/{kb_id}/chunks/{chunk_id}")
    def get_chunk(kb_id: str, chunk_id: str):
        with database() as session:
            chunk = session.get(Chunk, chunk_id)
            document = session.get(Document, chunk.doc_id) if chunk else None
            if not chunk or chunk.kb_id != kb_id or document.status == "deleted" or document.active_version != chunk.version:
                raise LookupError("原文片段不存在或版本已失效")
            return {"id": chunk.id, "text": chunk.text, "heading": chunk.heading,
                    "location": chunk.location, "version": chunk.version, "name": document.name}

    @application.get("/api/knowledge-bases/{kb_id}/documents/{doc_id}/download")
    def download(kb_id: str, doc_id: str):
        with database() as session:
            document = session.get(Document, doc_id)
            if not document or document.kb_id != kb_id or document.status == "deleted":
                raise LookupError("文档不存在")
            job = session.scalar(select(Job).where(Job.doc_id == doc_id, Job.version == document.active_version, Job.kind == "ingest"))
            if not job or not Path(job.path).is_file():
                raise LookupError("原始文件尚未准备好")
            download_name = str(Path(document.name).with_suffix(Path(job.path).suffix))
            return FileResponse(job.path, filename=download_name, media_type="application/octet-stream")

    @application.post("/api/knowledge-bases/{kb_id}/chat")
    def ask(kb_id: str, body: ChatInput):
        require_kb(kb_id)
        if not body.question.strip():
            raise ValueError("问题不能为空")
        return StreamingResponse(chat.stream(kb_id, body.session_id, body.question.strip()), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @application.delete("/api/knowledge-bases/{kb_id}/sessions/{session_id}")
    def clear_session(kb_id: str, session_id: str):
        require_kb(kb_id)
        sessions.clear(kb_id, session_id)
        return {"cleared": True}

    root = Path(__file__).resolve().parent.parent
    application.mount("/static", StaticFiles(directory=root / "web"), name="static")

    @application.get("/", include_in_schema=False)
    def home():
        return FileResponse(root / "web" / "index.html")

    @application.get("/learn", include_in_schema=False)
    def learning_guide():
        return FileResponse(root / "docs" / "学习手册.html")

    return application
