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

修改源码后，在项目根目录执行：

```powershell
.venv/Scripts/python.exe scripts/docs/build_guide.py
.venv/Scripts/python.exe scripts/docs/export_guide_markdown.py
```

chapters.html 保存教学章节，file_notes.json 保存文件与函数的业务解释；coverage.json 和 markdown-coverage.json 用于核对手册对应的源码版本。新增源码文件时同步更新 file_notes.json。
