# 知源：可追溯的 RAG 知识问答

这是一个面向学习与本机使用的完整 RAG 项目：文档入库、版本管理、混合检索、引用问答、多轮会话与流式页面。

## 先看哪里

- `docs/学习手册.html`：从零开始的学习手册，包含流程图、文件说明、代码逐行解释和维护练习。
- `docs/项目学习手册.md`：Markdown 完整版，可直接在 GitHub 或编辑器中阅读。
- `app/`：Python 后端。
- `web/`：不需要前端构建工具的网页。
- `samples/员工手册.md`：可直接上传的虚构示例资料。
- `eval/dataset.jsonl`：15 道起步评测题，包含无答案和多轮追问。
- `tests/`：不调用付费 API 的自动测试。

## 本机快速运行

需要 Python 3.11 或更高版本。当前项目已创建 `.venv`，不要使用系统中的 Python 3.9 启动。

```powershell
# 安装到新电脑时执行；已有虚拟环境可以跳过
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1 -Python "C:/你的Python路径/python.exe"

# 先体验页面和业务流程；不需要 Docker，不调用 DeepSeek
powershell -ExecutionPolicy Bypass -File scripts/start.ps1 -Demo
```

浏览器打开 http://127.0.0.1:8000 ，创建知识库，上传示例手册，等待任务“已完成”，然后提问“正式员工每年有几天年假？”。终端按 Ctrl+C 停止。

**演示模式只使用字符特征和原文摘录，不是 BGE 或大模型的效果演示。** 演示与真实模式使用不同数据库，避免向量混用。

## 真实模式

本机已选择 D 盘布局：Docker 程序位于 `D:/RAGRuntime/Docker`，Docker WSL 虚拟磁盘指定到 `D:/RAGRuntime/docker-data`，容器业务数据通过 `.env` 中的 `RAG_VOLUME_DIR` 指向 `D:/RAGRuntime/volumes`。Windows 自身的 WSL 系统组件仍由系统管理，不保证 C 盘完全零占用。

安装过程日志在 `D:/RAGRuntime/logs/`。`scripts/install-runtime.ps1` 是管理员安装脚本；不要把它当作日常启动命令重复执行。若安装要求重启，先保存其他工作再手动重启。

首次安装如提示重启，应先重启 Windows。日常打开 Docker Desktop，等待引擎启动后执行下面命令启动数据库服务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-infra.ps1
```

1. 安装并启动 Docker Desktop（Windows 需要 WSL 2 支持）。
2. 在项目根目录执行 `docker compose up -d`，等待依赖健康。
3. 新电脑先将 `.env.example` 复制为 `.env`，填入自己的 DeepSeek 密钥，并按实际磁盘位置调整 `RAG_VOLUME_DIR`；不要把 `.env` 上传到 Git。
4. 执行 `powershell -ExecutionPolicy Bypass -File scripts/start.ps1`。
5. 重新创建真实知识库并上传文档；首次使用会下载 BGE 模型。

```powershell
# 只检查依赖，不调用模型
.venv/Scripts/python.exe scripts/probe_services.py --infra

# 使用少量 API 额度验证 DeepSeek
.venv/Scripts/python.exe scripts/probe_services.py --llm

# 下载并验证两个 BGE 模型，首次需要较长时间
.venv/Scripts/python.exe scripts/probe_services.py --models
```

`.env` 默认使用 CPU，便于通用环境运行。GPU 需要安装与本机显卡兼容的 CUDA 版 PyTorch，并确认 `torch.cuda.is_available()` 为 True，再改为 `MODEL_DEVICE=cuda`。有 NVIDIA 显卡不代表当前 Python 已能使用 GPU。

## 自动验证与评测

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check.ps1

# 先在真实模式上传 samples/员工手册.md，从 /docs 或页面接口取得知识库 ID
.venv/Scripts/python.exe scripts/evaluate.py --kb 知识库ID --generate

# 人工填写报告中的 answer_correct 和 citation_supported 后汇总
.venv/Scripts/python.exe scripts/evaluate.py --ratings reports/evaluation.json --output reports/reviewed.json
```

评测会对比纯向量、混合检索、混合检索加重排序。未人工审核的回答正确率、引用准确率显示 `null`，不会把“带了引用编号”误算为“引用准确”。起步测试集很小，不能代表企业真实效果；应继续补充业务资料与独立测试题。

## 设计边界

- 元数据采用 SQLite + SQLAlchemy，方便本机学习；Milvus 保存 BGE 向量，Redis 保存会话。
- BM25 使用 jieba + rank-bm25，在当前知识库有效分块上计算；适合小型知识库，规模变大后可替换为服务端全文索引。
- 分块长度当前单位是**字符**，不是 token。Markdown/Word 保留标题；PDF 保留页码并识别简单编号标题，复杂排版的标题识别需要继续增强。
- PDF 支持可提取文本的文件；扫描件会给出 OCR 提示。Word 支持 `.docx`，旧 `.doc` 需先转换。
- 后台任务保存到数据库并支持失败重试。当前为单进程单 Worker 架构，使用文件锁阻止同数据目录启动多个 Worker。
- 默认仅绑定 `127.0.0.1`，没有用户登录系统。知识库逻辑隔离不等于多用户权限隔离；公网部署前需要增加身份认证和授权。
- 提示词、证据筛选与引用编号核验降低幻觉风险，不保证所有生成结论都正确；请核验关键原文。

## 配置与数据

| 位置 | 用途 |
|---|---|
| `.env` | 真实密钥与本机配置，已被 `.gitignore` 排除 |
| `.env.example` | 可分享的配置示例 |
| `requirements.lock.txt` | 本机实际安装依赖的精确版本 |
| `data/` | 数据库、上传文件、临时文件；不应提交 |
| `models/` | 下载的模型缓存；不应提交 |
| `volumes/` | Docker 持久化数据；不要直接删除 |
| `reports/` | 评测与验证报告 |

停止服务后备份 `data/`、`volumes/` 和配置。保留原文件后可重建向量索引。不要随意修改已有数据对应的 Embedding 模型；更换时使用新 Milvus collection 并重新入库。

## 官方参考

- DeepSeek API：https://api-docs.deepseek.com/en/
- BGE-M3：https://bge-model.com/bge/bge_m3.html
- BGE Reranker：https://huggingface.co/BAAI/bge-reranker-v2-m3
- Milvus Windows 安装：https://milvus.io/docs/install_standalone-windows.md
- LangChain：https://docs.langchain.com/oss/python/langchain/overview

本项目的 Compose 拓扑参考 Milvus 官方 standalone 配置，固定镜像版本，未追随最新版自动升级。


## 本机 D 盘部署（已实际启动）

Docker Desktop 位于 `D:\RAGRuntime\Docker`，镜像数据位于 `D:\RAGRuntime\docker-data`，容器持久数据由 `.env` 的 `RAG_VOLUME_DIR=D:/RAGRuntime/volumes` 指定。项目模型和 Python 环境仍在 C 盘。

先打开 Docker Desktop，再执行 `powershell -ExecutionPolicy Bypass -File scripts/start-infra.ps1`，随后执行 `powershell -ExecutionPolicy Bypass -File scripts/start.ps1`，访问 http://127.0.0.1:8000 。

默认 `compose.yaml` 使用 Milvus 官方支持的单机内嵌 etcd 与本地存储模式，并连接真实 Redis。原四容器拓扑保留在 `compose.distributed.yaml`；其 MinIO 镜像当前无法从官方仓库拉取，仅供参考，不是已验证启动方案。备份时使用实际的 `D:/RAGRuntime/volumes`，而非项目下不存在的默认 volumes 路径。

真实集成验证命令：`.venv/Scripts/python.exe scripts/verify_real_stack.py`。它使用独立数据目录和集合，调用真实 DeepSeek 并消耗少量额度，成功报告保存在 `reports/real-stack.json`。
