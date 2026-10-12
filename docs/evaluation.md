# 评测与验收

## 自动业务测试

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
```

测试覆盖解析、分块、知识库隔离、版本切换、失败恢复、增量向量复用、删除、SSE、会话和指标计算。自动测试使用确定性替身，不调用付费 API。

## 真实服务验收

```powershell
.venv/Scripts/python.exe scripts/verification/verify_real_stack.py
```

使用独立 SQLite 数据目录和 Milvus 集合，验证真实 BGE、Milvus、Redis、DeepSeek、引用和更新删除。会消耗少量模型 API 额度，报告输出到本地 reports/real-stack.json。

浏览器验收需额外安装 requirements-browser.txt、已有 Edge、运行中的服务和 reports/sample-kb.json 所记录的示例知识库：

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-browser.txt
.venv/Scripts/python.exe scripts/verification/verify_browser.py
```

浏览器脚本是针对已准备样本的验收工具，不会自动创建样本库。模型链的单独排错工具 verify_model_pipeline.py 使用本地索引和内存会话，不能代替完整服务验收。

## 检索对照实验

先上传 samples/员工手册.md，取得知识库 ID，再执行：

```powershell
.venv/Scripts/python.exe scripts/evaluation/evaluate.py --kb YOUR_KB_ID --generate --output reports/evaluation.json
```

策略包括 dense、hybrid、hybrid_rerank。Recall@K 以测试集指定证据是否出现在最终上下文中计算；耗时包含改写、检索及启用时的生成，模型首次加载会影响测量。预热后的多次独立测量更适合性能比较。

人工检查每条回答，把 answer_correct 填为 true/false，并逐项填写 citation_supported。未标注保持 null；拒答另填写 refusal_correct。汇总命令：

```powershell
.venv/Scripts/python.exe scripts/evaluation/evaluate.py --ratings reports/evaluation.json --output reports/reviewed.json
```

现有 15 题为虚构制度样本，适合流程验证。实际优化需加入真实业务、易混淆条款和独立测试题，再比较分块大小、重叠、召回数量及阈值。引用存在不代表引用正确，模型自评不能冒充人工标注。
