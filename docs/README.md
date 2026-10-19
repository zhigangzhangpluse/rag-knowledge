# 文档索引

| 文档 | 内容 |
| --- | --- |
| [architecture.md](architecture.md) | 数据职责、模块、版本一致性与问答流程 |
| [deployment.md](deployment.md) | 环境、配置、启动、备份和排错 |
| [evaluation.md](evaluation.md) | 自动测试、真实验收与人工评测 |
| [verification.md](verification.md) | 已验证范围与实验结果 |
| [项目学习手册.md](项目学习手册.md) | 系统教学、完整源码、逐行解析与扩展 |
| [学习手册.html](学习手册.html) | 可离线使用的搜索和折叠式学习手册 |

## 更新学习手册

源码中的学习注释按“白话解释 → 对照用法或例子 → 常见误区 → 面试问答”组织，放在相关类和函数旁边。Python 使用 `# -----` 分隔，前端使用对应语言的合法注释语法。示例代码写在注释内，仅供阅读，不会执行。

建议按以下顺序阅读：

1. `app/database.py`：先分清知识库、数据库、文档和有效版本。
2. `app/parsing.py`、`app/ingestion.py`：看资料怎样分块、去重、增量入库。
3. `app/models.py`：理解 Embedding、Reranker，以及本地 BGE 与不同厂商接口的区别。
4. `app/retrieval.py`：把向量召回、BM25、RRF、精排接成完整检索过程。
5. `app/sessions.py`、`app/generation.py`：理解多轮改写、证据引用、拒答和 SSE。
6. `app/main.py`、`web/app.js`、`tests/`：把接口、页面和验证方法对应起来。

面试问答需要结合代码理解；注释中明确指出的限制，不应介绍为已经实现的生产能力。

修改源码后，在项目根目录执行：

```powershell
.venv/Scripts/python.exe scripts/docs/build_guide.py
.venv/Scripts/python.exe scripts/docs/export_guide_markdown.py
```

chapters.html 保存教学章节，file_notes.json 保存文件与函数的业务解释；coverage.json 和 markdown-coverage.json 用于核对手册对应的源码版本。新增源码文件时同步更新 file_notes.json。
