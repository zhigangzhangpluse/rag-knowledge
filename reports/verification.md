# 当前验证记录（2026-10-08）

## 已验证

- 项目 Python 3.12 环境、依赖锁定及 20 项自动业务测试已通过；原演示模式浏览器链路已验证。
- Docker Desktop 已安装到 D:/RAGRuntime/Docker，重启和首次许可步骤已完成。Docker 引擎 29.8.2 正常运行。
- Milvus 2.5.16、Redis 7.4.2 均处于 healthy 状态，Python 客户端真实连接成功，证据见 local-services.json。
- 默认 compose.yaml 采用 Milvus 官方支持的内嵌 etcd 与本地存储模式。原因：原 MinIO 镜像在 Docker Hub 返回 access denied，在 Quay 返回 401；原四容器配置仅保留为 compose.distributed.yaml 参考。
- scripts/verify_real_stack.py 已实际通过：真实 BGE 入库、Milvus 检索、DeepSeek 带引用回答、追问、Redis 跨客户端读取历史、知识库隔离、空证据拒答、版本更新与旧向量清理、删除同步。证据见 real-stack.json。
- 正在运行的 FastAPI 真实模式已通过 HTTP 上传样本并完成后台入库；首页、JavaScript 资源 HTTP 200，真实 HTTP SSE 输出 done。证据见 sample-kb.json 与 http-sse.txt。
- 示例知识库名称为“员工手册 · 真实服务示例”，可用于页面体验。
- 学习手册同步包含新增真实联调脚本和内嵌 etcd 配置，覆盖以 docs/coverage.json 为准。

## 当前可访问

- 网页：http://127.0.0.1:8000
- 学习手册：http://127.0.0.1:8000/learn
- API 文档：http://127.0.0.1:8000/docs

## 验证边界

- 内置浏览器工具发生沙箱启动错误后，已改用 Playwright + 本机 Edge 独立无界面实例完成真实页面验收：真实模式标识、样本文档状态、问答完成、引用原文展开、手册章节导航、文件搜索和逐行表格均通过；无 JavaScript 页面异常。截图 real-browser.png、guide-daily.png、guide-compose.png 已人工目视检查，报告见 browser-verification.json。
- 真实评测结果以 real-evaluation.json 为准；固定虚构员工手册只有 15 题，不能代表企业业务泛化效果。人工正确率与引用准确率在未由人标注前保持 null。
- 本机单用户部署不包含身份认证、多人权限和高可用；原始 .env 密钥未纳入手册。

## 存储安排

Docker 程序与镜像目录在 D:/RAGRuntime；容器持久数据在 D:/RAGRuntime/volumes。模型与 Python 环境仍在 C 盘项目目录，约 7.6 GiB。安装阶段约 4.2 GiB 的 D 盘占用不包含后续镜像与持久数据；当前占用会随运行增长。WSL 系统组件及部分用户配置仍会使用 C 盘。

## 后续

本机项目及学习手册的交付验收已经完成。后续使用真实业务文档时，继续由业务评审者标注回答和引用，并扩充测试集；现有报告不冒充正式业务准确率。

## 真实检索评测结果

15 道题、三种策略均已完成真实模型生成。Recall@6 在三个策略上均为 1.0；纯向量 P50/P95 为 1130/1936 ms，混合为 1313/1853 ms，混合加重排序为 1909/2947 ms。这里的耗时包含问题改写、检索与回答生成，首次模型加载也可能影响统计。报告见 real-evaluation.json。

已由助手抽查混合加重排序策略的 15 条回答：有答案题与给定证据相符，2 道无答案题拒答，多轮远程办公追问成功消解。此为助手审阅，不冒充人工业务标注，人工正确率和引用准确率继续保留 null。小数据集出现召回饱和，不能据此宣称重排序优于纯向量，也没有为追求数字调整默认参数。
