# 部署与维护

## 环境准备

Python 3.11+、Docker 和 Compose 为真实运行所需环境。首次模型加载需要下载 BGE-M3 和 BGE Reranker；本项目实测模型缓存约 6.4 GiB，此外需为 Python 依赖和容器镜像预留空间。

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1 -Python python
# 修改 .env，填写密钥；Docker Desktop 引擎须已启动
powershell -ExecutionPolicy Bypass -File scripts/start-infra.ps1
powershell -ExecutionPolicy Bypass -File scripts/start.ps1
```

若 Docker 未加入 PATH，使用完整路径：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-infra.ps1 -DockerPath 'D:/RAGRuntime/Docker/resources/bin/docker.exe'
```

`deploy/windows/install-runtime.ps1` 仅为已有 D 盘安装包提供管理员安装辅助，不属于常规启动步骤。

### Linux / macOS

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
cp .env.example .env
# 编辑 .env，填写密钥与存储配置
docker compose up -d --wait
HF_HOME="$PWD/models/huggingface" .venv/bin/python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

依赖锁定文件来自 Python 3.12 的已验证环境；不同平台需验证 PyTorch 等二进制依赖兼容性。跨平台命令为部署参考，本项目实际验收环境为 Windows。

## 配置

.env.example 是通用模板；真实 .env 保留在本机。RAG_VOLUME_DIR 默认为 ./volumes，可以改为其他磁盘绝对路径。当前电脑的实际 .env 使用 D:/RAGRuntime/volumes，不会因模板调整而迁移数据。

常用参数：CHUNK_SIZE=500、CHUNK_OVERLAP=80（字符）；RECALL_K=30、RERANK_K=20、CONTEXT_K=6；MIN_RERANK_SCORE=0.2；MODEL_DEVICE=cpu。更换 Embedding 模型时使用新 MILVUS_COLLECTION 并重新入库，避免维度或语义空间混用。

.env 修改后需重启后端。/api/health 检查数据库，模型与 API 分别使用以下命令：

```powershell
.venv/Scripts/python.exe scripts/verification/probe_services.py --infra
.venv/Scripts/python.exe scripts/verification/probe_services.py --models
.venv/Scripts/python.exe scripts/verification/probe_services.py --llm
```

--llm 会调用真实 API 并消耗额度。

## 停止与备份

后端窗口按 Ctrl+C，随后执行 docker compose stop。备份时先停止写入，再复制 data/、实际 RAG_VOLUME_DIR、.env、源码与依赖锁定文件。SQLite 与 Milvus 应使用同一批次备份恢复。模型缓存可重新下载。不要直接删除 volumes 修复问题。

## 排错

| 现象 | 检查 |
| --- | --- |
| 页面打不开 | 后端进程、8000 端口和启动输出 |
| 入库失败 | 页面任务状态、数据库健康、文件是否支持 |
| 问答失败 | 模型缓存、Milvus/Redis、DeepSeek 配置和额度 |
| 答案不符合原文 | 引用与召回范围，再检查提示词与重排序阈值 |

扫描 PDF 需先 OCR；.doc 需转 .docx。演示模式通过 start.ps1 -Demo 使用独立数据库，不能用于验证真实模型效果。
