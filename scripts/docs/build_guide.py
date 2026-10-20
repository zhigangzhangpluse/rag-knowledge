# ----------------------------------------------------------------------
# 阅读入口：从真实源文件生成带行号的中文手册，结合人工编写的模块说明和语法树解释，不读取真实密钥。
# AST 是代码的结构化表示，可以区分赋值、循环、条件和函数调用。生成器用 HTML 转义防止示例代码变成可执行标签。代码改变后应重新生成并检查手册。
# 学习手册从源码生成，避免代码改了而文档仍介绍旧实现。
# AST 用来理解语法结构，HTML 转义防止源码里的尖括号被浏览器当成标签。
# 覆盖哈希可帮助发现源码变动，不代表解释内容已被自动证明正确。
# 面试问：为什么不用正则解析全部 Python？答：嵌套、字符串和作用域容易让正则误判。
# ----------------------------------------------------------------------
import ast
import hashlib
import html
import json
import re
from pathlib import Path

from markdown_it import MarkdownIt


ROOT = Path(__file__).resolve().parents[2]
NOTES = json.loads((ROOT / "docs/file_notes.json").read_text(encoding="utf-8"))
WORDS = {
    "settings": "本次运行的配置", "database": "数据库会话工厂", "session": "当前数据库事务会话",
    "sessions": "聊天历史存储服务", "kb_id": "知识库 ID", "doc_id": "文档 ID", "chunk_id": "分块 ID",
    "session_id": "聊天会话 ID", "job_id": "任务 ID", "document": "文档记录", "job": "处理任务",
    "record": "重新读取的任务记录", "chunk": "一个文档分块", "chunks": "文档分块列表",
    "content": "文件或正文内容", "digest": "文件内容的 SHA-256 指纹", "version": "文档版本号",
    "pieces": "解析后待入库的分块数据", "cached": "旧分块哈希到向量的复用表", "missing": "需要新计算向量的文本",
    "vector": "一条数字向量", "vectors": "多条数字向量", "models": "向量化与重排序模型适配器",
    "index": "索引服务或当前遍历位置（由当前函数决定）", "query": "检索问题或 SQL 查询（由当前函数决定）",
    "question": "用户原问题", "history": "之前完成的聊天消息", "rewritten": "补全后的独立问题",
    "sources": "已编号的原文证据", "answer": "累计生成的回答", "hits": "检索命中对象列表",
    "scores": "候选评分", "rankings": "多路候选 ID 排名", "merged": "RRF 融合排名",
    "dense": "向量召回的分块 ID", "lexical": "关键词召回的分块 ID", "tokens": "词项或 Markdown 语法单元",
    "blocks": "带标题和位置的文本块", "headings": "当前标题层级路径", "start": "窗口起点",
    "end": "窗口终点", "overlap": "相邻窗口重叠字符数", "result": "准备返回的计算结果",
    "response": "接口响应", "client": "服务客户端", "application": "FastAPI 应用对象",
    "path": "文件路径或接口路径", "rows": "本次处理的数据行", "report": "评测或服务检查报告",
    "args": "命令行参数", "body": "经过校验的请求体", "real": "是否使用真实服务的开关",
}
METHODS = {
    "commit": "提交事务，让本次数据库修改持久生效", "flush": "把待新增数据发送到数据库以获得主键，但尚不提交事务",
    "add": "把一个对象放入当前数据库会话，准备写入", "add_all": "批量把对象放入数据库会话",
    "scalars": "执行 SQL 并按单个对象序列读取结果", "scalar": "执行 SQL 并读取首个标量或对象",
    "where": "为查询添加必须满足的过滤条件", "join": "按关系连接两张数据表",
    "order_by": "指定查询结果的排列顺序", "limit": "限制结果条数", "execute": "执行 SQL 或 Redis 已排队操作",
    "write_text": "用指定编码把文本写入文件", "read_text": "把文本文件读取为字符串",
    "write_bytes": "把原始二进制内容写入文件", "mkdir": "创建目录", "unlink": "删除一个已经确认路径的文件",
    "resolve": "得到规范化绝对路径", "is_relative_to": "检查路径是否位于允许目录内",
    "encode": "将文本转为字节或调用模型生成向量，具体由调用对象决定", "hexdigest": "把哈希结果转成十六进制字符串",
    "strip": "去掉两端空白", "splitlines": "按行拆分文本", "replace": "替换文本中的指定内容",
    "append": "把一项添加到列表末尾，或调用会话服务保存完整轮次", "extend": "把多项追加到列表",
    "update": "把新键值对合并进已有字典", "sort": "对列表原地排序", "tolist": "把数值数组转换为普通 Python 列表",
    "reshape": "改变数组形状，使输出统一为一维分数列表", "predict": "让重排序模型计算问题与文本的相关性",
    "invoke": "执行一次 LangChain 链并等待完整结果", "stream": "执行流式调用，每次产出一部分结果",
    "upsert": "将分块写入索引，已有 ID 则更新", "search": "执行向量检索",
    "get_scores": "计算问题词项对所有分块的 BM25 分数", "lcut": "将中文文本切成词语列表",
    "lrange": "读取 Redis 列表中的指定范围", "rpush": "向 Redis 列表尾部追加消息",
    "ltrim": "仅保留 Redis 列表中的指定范围", "expire": "设置 Redis 键的过期时间",
    "ping": "发送轻量请求检查 Redis 是否可用", "clear": "清空数据或会话", "acquire": "获取锁以保护并发访问",
    "release": "释放已经持有的锁", "is_set": "检查线程退出信号是否已经设置", "set": "设置线程退出信号",
    "wait": "等待信号或超时", "start": "启动后台线程或服务", "close": "关闭资源或服务",
    "model_validator": "注册配置整体校验规则", "fixture": "声明可被测试函数使用的准备过程",
    "raises": "验证代码确实抛出预期异常", "setattr": "临时替换对象方法，以便模拟失败等场景",
    "add_argument": "声明一个命令行开关及用途", "parse_args": "读取用户传入的命令行参数",
}
CALLS = {
    "SettingsConfigDict": "指定从 .env 读取配置，并忽略没有在 Settings 中声明的额外字段",
    "SecretStr": "创建默认隐藏显示的敏感字符串，避免配置对象被打印时泄露密钥",
    "Settings": "读取环境变量和 .env，解析类型并执行配置校验",
    "ForeignKey": "声明该列引用另一张表的主键，表达业务对象之间的关系",
    "ChatPromptTemplate.from_messages": "按消息角色构造提示词模板，花括号参数在运行时填入",
    "len": "计算数量或长度", "str": "转为字符串", "int": "转为整数", "float": "转为浮点数",
    "list": "收集为列表", "set": "去除重复值形成集合", "dict": "构造键值映射", "tuple": "构造不可变序列",
    "max": "取最大值", "min": "取最小值", "sum": "累计求和", "round": "按指定位数取近似值",
    "range": "生成用于循环的整数序列", "enumerate": "同时得到元素序号和元素内容", "zip": "按位置配对多组数据",
    "sorted": "生成排序后的新列表", "any": "判断是否至少有一项成立", "all": "判断是否所有项都成立",
    "print": "将非敏感结果写到终端", "select": "构造 SQL 查询", "delete": "构造 SQL 删除语句",
    "Path": "构造跨平台路径对象", "Field": "声明默认值和输入约束", "mapped_column": "声明数据库列与约束",
    "create_engine": "创建数据库连接引擎", "sessionmaker": "创建数据库事务会话工厂",
    "event": "序列化一条 SSE 事件", "active_chunks": "查询当前知识库有效版本分块",
    "rrf": "融合多路候选排名", "clean": "清洗正文空白和控制字符", "parse": "按文件类型解析文档",
    "split_blocks": "按标题和重叠窗口生成分块", "new_id": "生成唯一业务 ID",
    "require_kb": "检查知识库存在", "require_job": "检查任务属于指定知识库",
    "upload_ready": "为测试准备一个已完成入库的文档", "events": "将 SSE 响应转换为便于断言的事件列表",
}
CONFIG_NOTES = {
    "RAG_VOLUME_DIR": "Docker Compose 的容器持久化目录；本机设为 D:/RAGRuntime/volumes。它不是 Python 上传文件目录，也不是 Docker 虚拟磁盘路径",
    "DEEPSEEK_API_KEY": "DeepSeek 身份凭据。真实值只放 .env，不可提交或公开；为空时真实生成不可用",
    "LLM_BASE_URL": "模型服务入口；当前指向 DeepSeek 官方 API，不能把密钥发给不信任的地址",
    "LLM_MODEL": "向 DeepSeek 请求的模型名称；必须是账号可用且服务支持的名称",
    "LLM_TEMPERATURE": "输出随机性，越低通常越稳定；知识库问答默认 0.1",
    "LLM_MAX_TOKENS": "单次最大输出长度；调高可容纳更长答案，也可能增加费用和延迟",
    "LLM_TIMEOUT": "模型请求超时秒数；网络慢可适当增加，不应无限等待",
    "APP_MODE": "production 使用真实服务；demo/test 使用确定性替身，不能代表真实模型效果",
    "DATABASE_URL": "关系数据库位置；sqlite:/// 表示本地文件数据库，不是 Milvus 地址",
    "DATA_DIR": "上传文件和任务锁所在的本地数据目录",
    "MILVUS_URI": "Milvus 服务连接地址，19530 是当前映射到宿主机的接口端口",
    "MILVUS_COLLECTION": "向量集合名称；更换 Embedding 维度或模型时使用新集合并重新入库",
    "REDIS_URL": "Redis 会话存储地址，末尾 /0 表示使用编号 0 的逻辑数据库",
    "EMBEDDING_MODEL": "文档和问题使用的同一个向量模型；修改后旧文档需要重新生成向量",
    "RERANKER_MODEL": "给问题与候选片段重新评分的模型，不是回答生成模型",
    "MODEL_DEVICE": "模型运行设备；cpu 普遍可用，cuda 需要兼容的 NVIDIA 驱动与 CUDA 版 PyTorch",
    "CHUNK_SIZE": "单个正文窗口的字符上限，不是 token 数；变更后必须重新切块入库才影响旧文档",
    "CHUNK_OVERLAP": "长文本相邻窗口重叠字符数，必须小于 CHUNK_SIZE",
    "RECALL_K": "每一路召回的候选数量；增大可提高覆盖，也会增加搜索成本",
    "RERANK_K": "RRF 融合后送入重排序的候选上限；增大会增加模型推理时延",
    "CONTEXT_K": "最终最多交给生成模型的证据条数；多并不一定更好，重复证据会浪费上下文",
    "MIN_RERANK_SCORE": "相关性筛选阈值；需用测试集校准，不能把分数直接当作正确概率",
    "SESSION_TTL": "会话过期秒数，86400 等于 24 小时；完成新一轮问答后刷新有效期",
    "MAX_UPLOAD_MB": "允许上传的最大文件体积，单位 MB；限制资源消耗，但不等于防御所有恶意压缩文件",
}


def label(name):
    return f"{name}（{WORDS[name]}）" if name in WORDS else name


def source(node):
    return ast.unparse(node)


def expression(node):
    if isinstance(node, ast.Await):
        return "等待异步操作完成：" + expression(node.value)
    if isinstance(node, ast.Name):
        return label(node.id)
    if isinstance(node, ast.Constant):
        return repr(node.value)
    if isinstance(node, ast.Call):
        name = source(node.func)
        short = name.rsplit(".", 1)[-1]
        meaning = METHODS.get(short) if isinstance(node.func, ast.Attribute) else CALLS.get(short)
        return f"调用 {name}，{meaning}" if meaning else f"调用 {name}，按括号中的位置参数和关键字参数取得结果"
    if isinstance(node, ast.Compare):
        names = {ast.Eq: "等于", ast.NotEq: "不等于", ast.Lt: "小于", ast.Gt: "大于", ast.LtE: "小于等于",
                 ast.GtE: "大于等于", ast.In: "属于", ast.NotIn: "不属于", ast.Is: "是同一个对象", ast.IsNot: "不是同一个对象"}
        result = expression(node.left)
        for operator, right in zip(node.ops, node.comparators):
            result += " " + names[type(operator)] + " " + source(right)
        return result
    if isinstance(node, ast.BoolOp):
        word = "，并且 " if isinstance(node.op, ast.And) else "，或者 "
        return word.join(source(item) for item in node.values)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return "取反：" + source(node.operand) + " 不成立或为空"
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        return "使用推导式遍历 " + "、".join(source(item.iter) for item in node.generators) + "，按 for 后的变量和 if 条件生成新结果"
    if isinstance(node, ast.IfExp):
        return f"条件 {source(node.test)} 成立时取 {source(node.body)}，否则取 {source(node.orelse)}"
    if isinstance(node, ast.Subscript):
        return f"从 {source(node.value)} 读取键、下标或切片 {source(node.slice)} 对应的内容"
    if isinstance(node, ast.Attribute):
        return f"读取 {source(node.value)} 的 {node.attr} 属性"
    if isinstance(node, ast.Dict):
        return "构造字典，左侧为字段名，冒号右侧为对应数据；字段逐项写在本行或后续行"
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return "按代码中的顺序组织多个值" if not isinstance(node, ast.Set) else "创建集合，自动去掉重复值"
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.BitOr):
            return "用 | 连接 LangChain 流程组件，前一步的输出成为后一步输入"
        return "计算表达式 " + source(node) + "；运算顺序由括号和运算符优先级决定"
    if isinstance(node, ast.JoinedStr):
        return "构造 f-string，把花括号中的运行时值嵌入文本"
    return "求值 " + source(node)


def python_explanation(node, line, notes):
    text = line.strip()
    if not text:
        return "空行：分隔逻辑段落，不执行操作。"
    if text.startswith("#"):
        return "注释：" + text.lstrip("# ") + "。供阅读，不执行。"
    if text.startswith("@"):
        return "装饰器：把下一函数注册成路由、校验器、测试 fixture 或缓存属性；参数规定其具体用途。"
    if text.startswith("else:"):
        return "前面条件不成立时执行下面缩进的分支。"
    if text.startswith("elif "):
        return "前面分支都未成立时，继续检查本行条件。"
    if text.startswith("except "):
        return "捕获指定异常，执行下面的失败处理，避免异常直接暴露给用户。"
    if text.startswith("finally:"):
        return "无论前面成功还是失败都执行此处的资源清理。"
    if text in {")", "]", "}", ").order_by(Chunk.doc_id, Chunk.ordinal)"}:
        return "结束跨行参数或容器；这一行与前面的表达式一起构成一条语句。"
    if node is None:
        return "延续上一条语句的参数或括号结构，结合相邻行阅读。"
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        name = node.name
        purpose = notes.get("functions", {}).get(name, "把下面缩进的步骤封装为可复用函数；调用时才执行函数体。")
        return f"定义函数 {name}。{purpose}"
    if isinstance(node, ast.ClassDef):
        return f"定义 {node.name} 类；括号内是继承的父类，下面缩进内容描述字段和方法。"
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return "导入 " + "、".join(item.name + (f" 并简写为 {item.asname}" if item.asname else "") for item in node.names) + (f"，来源模块是 {node.module}" if isinstance(node, ast.ImportFrom) else "") + "。后续可通过导入名称使用其功能。"
    if isinstance(node, ast.Assign):
        return "赋值给 " + "、".join(label(source(target)) for target in node.targets) + "：" + expression(node.value) + "。"
    if isinstance(node, ast.AnnAssign):
        if source(node.target).upper() in CONFIG_NOTES:
            constraint = "Field 额外校验 ge（下限）和 le（上限）等限制。" if isinstance(node.value, ast.Call) and source(node.value.func) == "Field" else ""
            return f"配置字段 {source(node.target)}：{CONFIG_NOTES[source(node.target).upper()]}。冒号后是类型，等号后是默认值。{constraint}"
        return f"声明 {label(source(node.target))}，类型为 {source(node.annotation)}" + ("；" + expression(node.value) if node.value else "") + "。"
    if isinstance(node, ast.AugAssign):
        return "在 " + source(node.target) + " 原值上累计更新：" + source(node) + "。"
    if isinstance(node, ast.Return):
        return "结束当前函数" + ("，返回：" + expression(node.value) if node.value else "，不返回具体业务结果") + "。"
    if isinstance(node, ast.If):
        return "检查条件：" + expression(node.test) + "。满足时执行下方缩进代码。"
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return f"逐项遍历 {source(node.iter)}，每次把当前内容放入 {source(node.target)}，再执行下方缩进代码。"
    if isinstance(node, ast.While):
        return "只要条件 " + source(node.test) + " 成立，就继续循环；注意内部必须能前进或退出。"
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return "进入受管理的资源范围：" + "；".join(source(item.context_expr) + ("，命名为 " + source(item.optional_vars) if item.optional_vars else "") for item in node.items) + "。离开时自动清理或释放。"
    if isinstance(node, ast.Try):
        return "开始一段可能失败的操作；出错后转到 except 分支。"
    if isinstance(node, ast.Raise):
        return "中止当前正常流程并报告异常：" + (source(node.exc) if node.exc else "继续抛出刚捕获的异常") + "。"
    if isinstance(node, ast.Assert):
        return "测试断言：要求 " + expression(node.test) + " 成立，否则测试失败。"
    if isinstance(node, ast.Break):
        return "立刻退出当前循环，避免继续处理不需要的内容。"
    if isinstance(node, ast.Continue):
        return "跳过本轮剩余操作，直接处理下一个元素。"
    if isinstance(node, ast.Pass):
        return "占位空操作；该适配器或基类在这里不需要额外执行动作。"
    if isinstance(node, ast.Expr):
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return "文档字符串：说明模块、类或函数用途，供读者和文档工具查看。"
        if isinstance(value, (ast.Yield, ast.YieldFrom)):
            return "生成器向调用者产出 " + (expression(value.value) if value.value else "控制权") + "；后续迭代时再继续执行。"
        if isinstance(value, ast.Await):
            return "等待异步操作 " + source(value.value) + " 完成；等待期间事件循环可处理其他任务。"
        return expression(value) + "。"
    return "执行这条 " + type(node).__name__ + " 语句，具体参数与相邻行共同组成当前操作。"


def describe_python(content, notes):
    tree = ast.parse(content)
    statements = [node for node in ast.walk(tree) if isinstance(node, ast.stmt)]
    rows = []
    for number, line in enumerate(content.splitlines(), 1):
        candidates = [node for node in statements if node.lineno <= number <= node.end_lineno]
        node = min(candidates, key=lambda item: item.end_lineno - item.lineno) if candidates else None
        explanation = python_explanation(node, line, notes)
        if node and number > node.lineno and line.strip() and not line.strip().startswith(("#", "else:", "elif ", "except ", "finally:")):
            explanation = f"第 {node.lineno} 行开始的语句在这里继续。" + explanation
        rows.append((number, line, explanation))
    return rows


def describe_other(path, content):
    rows = []
    for number, line in enumerate(content.splitlines(), 1):
        text = line.strip()
        if not text:
            explanation = "空行，用于分隔内容。"
        elif text.startswith(("#", "//")):
            explanation = "注释或 Markdown 标题，用来说明接下来一段的用途，不是业务执行语句。"
        elif path.suffix == ".js":
            rules = [
                ("textContent", "把值作为纯文本显示到元素，避免把回答中的标签当作 HTML 执行。"),
                ("fetch(", "发起 HTTP 请求；路径决定后端接口，options 指定方法、请求头和请求体。"),
                ("JSON.stringify", "将 JavaScript 对象编码为 JSON 请求数据。"),
                ("JSON.parse", "把 SSE 的 JSON 文本转换成可按属性读取的对象。"),
                ("new FormData", "创建文件上传表单容器，后续 append 加入文件。"),
                ("new AbortController", "创建可取消请求的控制器，会话切换时用它停止旧请求。"),
                (".abort()", "取消仍在运行的旧问答请求。"),
                ("TextDecoder", "创建 UTF-8 解码器，将网络字节转成文字。"),
                ("decoder.decode", "流式解码网络数据，保留跨网络分片的中文字符。"),
                ("getReader", "获取响应流读取器，准备按数据块消费 SSE。"),
                ("reader.read", "等待读取下一个网络数据块，同时取得是否结束的标志。"),
                ("buffer.indexOf", "寻找 SSE 事件的空行边界；一个网络包不一定等于一个完整事件。"),
                ("buffer.slice", "从缓冲文本中切出一个完整事件，或保留尚未处理的余下文本。"),
                ("replaceChildren", "清空或替换旧页面节点，避免旧知识库内容残留。"),
                ("createElement", "创建一个 HTML 节点，随后设置内容并插入页面。"),
                (".append(", "把节点加入页面，或把文件加入 FormData；由调用对象决定。"),
                ("preventDefault", "阻止表单默认跳转刷新，改由 JavaScript 异步处理。"),
                ("setInterval", "按固定间隔刷新后台任务状态。"),
                ("setTimeout", "安排延迟执行，例如几秒后隐藏提示。"),
                (".disabled", "更新按钮可用状态，避免重复提交。"),
                ("randomUUID", "创建随机会话 ID 并移除连字符，使其匹配后端的 32 位格式。"),
                ("throw new Error", "报告本次失败，把控制流交给 catch 统一提示。"),
                ("catch", "捕获异步失败并更新提示，避免错误静默丢失。"),
                ("finally", "无论成功还是失败都恢复按钮或清理请求状态。"),
                (".onsubmit", "注册表单提交时的异步处理函数。"),
                (".onchange", "注册选择项或文件发生变化时的处理函数。"),
                (".onclick", "注册按钮被点击时执行的回调。"),
                ("Promise.all", "同时等待两个互不依赖的接口结果。"),
                ("scrollTop", "把消息容器滚动到最新内容。"),
                ("response.ok", "检查 HTTP 状态是否表示成功。"),
            ]
            explanation = next((meaning for token, meaning in rules if token in text), "")
            if not explanation:
                if text.startswith(("function ", "async function ")):
                    explanation = "定义可复用的页面操作函数；括号内是参数，花括号内是执行步骤。"
                elif text.startswith(("const ", "let ")):
                    explanation = "声明并初始化本行等号左侧的变量；const 不能重新赋值，let 可以在后续更新。"
                elif text.startswith("if "):
                    explanation = "只有括号中的条件成立才执行后续操作；=== 表示严格比较，! 表示取反。"
                elif text.startswith(("for ", "while ")):
                    explanation = "循环遍历数据或读取响应，循环体在花括号内，结束条件写在括号中。"
                elif text.startswith("return "):
                    explanation = "把本行结果返回给调用者，并结束当前函数。"
                elif text in {"}", "};", ");"}:
                    explanation = "结束当前代码块、回调或函数调用。"
                else:
                    explanation = "执行本行函数调用或更新当前状态；参数按括号顺序传入，await 表示等待异步结果。"
        elif path.suffix == ".css":
            selector = text.split("{", 1)[0]
            properties = re.findall(r"([a-z-]+)\s*:\s*([^;{}]+)", text)
            meanings = {"display":"布局方式", "grid-template-columns":"网格列宽", "padding":"内容内边距", "margin":"外边距", "color":"文字颜色", "background":"背景", "font-size":"字号", "border":"边框", "border-radius":"圆角", "gap":"子元素间距", "height":"高度", "width":"宽度", "overflow-y":"纵向溢出行为", "white-space":"换行与空格显示", "position":"定位方式", "flex":"弹性空间分配", "line-height":"行距", "cursor":"鼠标指针", "opacity":"不透明度"}
            explanation = f"选择器 {selector} 的样式：" + "；".join(f"{meanings.get(key, key)} = {value.strip()}" for key, value in properties) + "。"
        elif path.suffix == ".html":
            tags = re.findall(r"<([a-z][a-z0-9]*)\b", text)
            meanings = {"section":"文档章节", "h1":"一级标题", "h2":"二级标题", "h3":"三级标题", "p":"说明段落", "div":"布局容器", "span":"行内文本", "form":"交互表单", "input":"输入控件", "button":"操作按钮", "select":"下拉选择", "label":"输入标签", "script":"加载交互脚本", "link":"加载样式", "meta":"字符编码或视口设置", "table":"信息对照表", "tr":"表格行", "td":"数据单元格", "th":"列标题", "ol":"有序步骤", "li":"列表项", "a":"跳转链接", "textarea":"多行问题输入", "header":"页头", "aside":"侧栏", "main":"主要内容", "details":"可折叠内容", "code":"行内代码"}
            explanation = "创建或组织 " + "、".join(meanings.get(tag, tag) for tag in dict.fromkeys(tags)) + "；标签嵌套决定页面结构，id 和 class 供脚本或样式定位。" if tags else "关闭 HTML 标签或声明文档类型，与前面的开始标签对应。"
        elif path.suffix == ".ps1":
            if text.startswith("param"):
                explanation = "声明 PowerShell 脚本参数及默认值；调用脚本时可用 -参数名 覆盖。"
            elif "Set-Location" in text:
                explanation = "切换到项目根目录，保证相对文件路径指向本项目。"
            elif "New-Item" in text:
                explanation = "创建需要的目录；-Force 允许目录已经存在，Out-Null 隐藏无关输出。"
            elif "LASTEXITCODE" in text:
                explanation = "检查刚执行的外部程序退出码；非零表示失败，立即停止后续流程。"
            elif "& " in text:
                explanation = "使用调用运算符 & 执行指定 Python 或命令，后面的内容是命令行参数。"
            elif text.startswith("$env:"):
                explanation = "设置当前进程及其子进程可读取的环境变量，配置临时目录或运行模式。"
            elif "Remove-Item Env:" in text:
                explanation = "仅清除当前 PowerShell 进程的指定环境变量，不删除磁盘文件。"
            elif text.startswith("$"):
                explanation = "给脚本变量赋值；Join-Path 用于安全组合路径，不依赖手写分隔符。"
            elif "if (" in text or "else" in text:
                explanation = "按条件选择分支，例如目录是否存在、是否要求演示模式。"
            else:
                explanation = "执行脚本控制语句或结束代码块，和相邻的安装、启动、验证步骤一起阅读。"
        elif path.name.startswith("requirements"):
            explanation = "Python 依赖声明：" + text + "。== 固定精确版本；>= 和 < 定义允许区间；安装时 pip 会处理其传递依赖。"
        elif path.name == ".env.example":
            key = text.split("=", 1)[0]
            explanation = f"配置 {key}：{CONFIG_NOTES.get(key, '由 Settings 按名称读取')}。等号右侧是默认值或占位符；修改后重启服务。"
        elif path.name == ".gitignore":
            explanation = f"Git 忽略模式 {text}，防止把本机秘密、缓存或运行数据作为源码提交。"
        elif path.suffix in {".yaml", ".yml"}:
            key = text.split(":", 1)[0]
            yaml_notes = {
                "name": "Compose 项目名称，用来给容器和网络统一加前缀，方便识别本项目。",
                "services": "下面每个缩进名称代表一个容器服务。",
                "milvus": "声明向量数据库服务，保存文档向量并接受语义检索请求。",
                "redis": "声明聊天历史存储服务；服务名称也能在容器网络内作为主机名使用。",
                "etcd": "声明独立元数据服务；默认单机配置将该功能内嵌到 Milvus。",
                "minio": "声明对象存储服务；仅参考拓扑使用，默认单机配置改用本地存储。",
                "image": "指定容器镜像及固定版本；第一次启动会下载，之后复用本地镜像。",
                "command": "容器启动时执行的命令；Milvus 启动 standalone，Redis 的 appendonly yes 开启追加日志持久化。",
                "security_opt": "容器安全选项列表；下一行定义具体选项。",
                "environment": "传给容器进程的环境变量；缩进中的名称由服务程序读取。",
                "ETCD_USE_EMBED": "true 表示由 Milvus 内部启动 etcd，不再依赖单独的 etcd 容器。",
                "ETCD_DATA_DIR": "内嵌 etcd 的元数据保存目录；位于持久化挂载目录内，重建容器后仍可读取。",
                "ETCD_CONFIG_PATH": "告诉 Milvus 去哪里读取内嵌 etcd 配置；这是容器内路径。",
                "COMMON_STORAGETYPE": "local 表示 Milvus 数据使用容器内本地文件存储，由宿主机挂载目录持久保存。",
                "volumes": "声明宿主机到容器的目录或文件映射；冒号左边是宿主机路径，右边是容器路径。",
                "ports": "声明宿主机端口映射；127.0.0.1 限制为本机访问。",
                "healthcheck": "定义服务是否已可用的探测规则；进程启动不等于数据库已经准备好。",
                "test": "实际探测命令；curl 检查 HTTP 健康端点，redis-cli ping 检查 Redis 是否应答。",
                "interval": "两次健康探测的间隔，例如 15s 表示每 15 秒检查一次。",
                "timeout": "单次探测允许等待的最长时间，超时算本次探测失败。",
                "start_period": "启动宽限期，在此期间的失败不会累计为不健康，供数据库初始化使用。",
                "retries": "连续探测失败达到此次数后才标记为不健康。",
                "depends_on": "声明依赖服务；下面的 condition 决定等待条件。",
                "condition": "service_healthy 表示等待依赖通过健康检查再启动当前服务。",
                "listen-client-urls": "etcd 在容器内部监听客户端请求的地址；0.0.0.0 表示监听所有容器网卡。",
                "advertise-client-urls": "etcd 向客户端通告的访问地址，供内嵌服务连接。",
                "quota-backend-bytes": "etcd 后端空间配额，4294967296 字节等于 4 GiB，不表示启动时立即占满。",
                "auto-compaction-mode": "revision 表示按数据修改版本数压缩历史，避免旧版本持续增长。",
                "auto-compaction-retention": "保留的历史修订数量；1000 表示压缩更早的历史版本。",
            }
            if text.startswith("- ${RAG_VOLUME_DIR"):
                explanation = "将实际配置的持久目录挂载给容器。${RAG_VOLUME_DIR:-./volumes} 表示优先使用环境变量，未设置时才用项目下 volumes；本机配置指向 D 盘。"
            elif text.startswith("- ./deploy/"):
                explanation = "将项目配置文件挂载到容器中的指定位置；末尾 :ro 表示容器只能读取，不能改写宿主文件。"
            elif text.startswith("- 127.0.0.1:"):
                explanation = "仅向本机开放端口；三个部分依次为绑定地址、宿主端口、容器端口。Python 通过宿主端口连接服务。"
            elif text == "- seccomp:unconfined":
                explanation = "按 Milvus 官方单机示例放宽容器系统调用过滤；它不是业务数据库配置，不应随意照搬到其他服务。"
            else:
                explanation = yaml_notes.get(key, "服务配置 " + text + "；按当前缩进归属上方服务，环境变量会在容器启动时交给服务程序。")
        elif path.suffix == ".jsonl":
            item = json.loads(text)
            explanation = f"测试题 {item['id']}：问题是“{item['question']}”；answer 是参考答案，evidence 是应该召回的原文依据，answerable 表示文档是否足以回答。"
        elif path.suffix == ".json":
            explanation = "人工说明数据：键对应文件名、用途 purpose、知识点 knowledge 或函数名 functions；生成器读取它来补充业务解释。"
        elif path.suffix == ".md":
            explanation = "Markdown 文本资料或操作说明；# 是标题，- 是列表，反引号用于显示代码，正文不直接执行。"
        else:
            explanation = "配置行：定义工具应使用的选项，按文件所属工具的格式读取。"
        rows.append((number, line, explanation))
    return rows


def build():
    sections, links, manifest = [], [], []
    for filename, notes in NOTES.items():
        path = ROOT / filename
        if not path.is_file():
            raise FileNotFoundError(filename)
        content = path.read_text(encoding="utf-8-sig")
        anchor = "file-" + hashlib.sha256(filename.encode()).hexdigest()[:12]
        links.append(f'<a href="#{anchor}">{html.escape(filename)}</a>')
        rows = describe_python(content, notes) if path.suffix == ".py" else describe_other(path, content)
        functions = "".join(f'<li><code>{html.escape(name)}</code>：{html.escape(meaning)}</li>' for name, meaning in notes.get("functions", {}).items())
        table = "".join(f'<tr id="{anchor}-L{number}"><td class="line">{number}</td><td class="code"><pre>{html.escape(code) or " "}</pre></td><td>{html.escape(explanation)}</td></tr>' for number, code, explanation in rows)
        sections.append(f'<section id="{anchor}" class="file-section"><h2>{html.escape(filename)}</h2><p class="purpose">{html.escape(notes["purpose"])}</p><div class="callout">知识点与扩展：{html.escape(notes["knowledge"])}</div><ul>{functions}</ul><details><summary>展开逐行阅读 · {len(rows)} 行</summary><div class="table-scroll"><table class="source"><thead><tr><th>行</th><th>原代码 / 配置</th><th>这一行做什么</th></tr></thead><tbody>{table}</tbody></table></div></details></section>')
        manifest.append({"file": filename, "lines": len(rows), "explained_lines": len(rows), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    chapters = (ROOT / "docs/chapters.html").read_text(encoding="utf-8")
    extra = '<section id="generated"><h2>运行产生的文件与目录</h2><p><code>.env</code>：本机实际配置，与 .env.example 字段相同，密钥刻意不收录。<code>.venv/</code>：第三方 Python 环境，不属于本项目手写源码，不需要逐个维护其中的文件。</p><p><code>data/</code>：上传原文、SQLite 数据库和测试临时数据；<code>models/</code>：模型权重；<code>volumes/</code>：容器持久数据；<code>__pycache__/</code> 与 <code>.pytest_cache/</code>：可重建的工具缓存。</p><p><code>reports/</code>：验证和评测结果。<code>docs/学习手册.html</code> 是本生成器的输出，<code>docs/coverage.json</code> 记录各源文件行数和哈希，帮助检查解释是否对应当前代码。修改说明应编辑 chapters.html 或 file_notes.json，再执行生成器，不要直接改生成文件。</p><p>安全原则：不分享 .env；备份业务数据时妥善保存；网页静态目录只挂载 web，不会开放整个项目。</p></section>'
    style = '''body{margin:0;background:#f7f6f1;color:#253e35;font:16px/1.9 "Microsoft YaHei",sans-serif}nav{position:fixed;left:0;top:0;bottom:0;width:270px;background:#233f35;color:white;padding:28px 20px;overflow:auto;box-sizing:border-box}nav a{display:block;color:#d8e8db;text-decoration:none;padding:5px 0;font-size:12px;overflow-wrap:anywhere}nav h2{font-size:20px}main{margin-left:270px;padding:36px 52px;max-width:1420px}section{margin:0 0 40px;background:white;padding:32px;border-radius:14px;border:1px solid #e2e5db;scroll-margin-top:20px}h1{font-size:34px;line-height:1.4}h2{font-size:23px;line-height:1.5}h3{font-size:18px}p{max-width:980px}.lead{font-size:19px;color:#637365}.eyebrow{letter-spacing:2px;font-size:12px;color:#75856e}.callout{background:#edf3e7;border-left:4px solid #71976a;padding:16px 20px;margin:20px 0}.flow{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:24px 0}.flow span{padding:14px 18px;background:#e9efdf;border:1px solid #d9e2cc;border-radius:8px}.flow b{color:#829575}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid #dce2d5;padding:12px;text-align:left;vertical-align:top}th{background:#eef3e9}code{font-family:Consolas,monospace;background:#edf1e8;padding:2px 5px;border-radius:4px;overflow-wrap:anywhere}pre{margin:0;font:12px/1.8 Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere}.source{table-layout:fixed}.source th:first-child{width:48px}.source th:nth-child(2){width:48%}.line{color:#8a9a83;font-size:11px}.code{background:#fafbf8}details>summary{cursor:pointer;background:#f0f4ea;padding:12px 16px;border-radius:8px;font-weight:bold;margin:20px 0}.source td:last-child{font-size:13px}.purpose{font-size:17px}button{background:#dce8d4;color:#233f35;border:0;padding:10px;cursor:pointer;border-radius:6px}input{padding:9px;width:100%;box-sizing:border-box;margin:10px 0;border-radius:5px;border:1px solid #abc19f}.hidden{display:none}@media(max-width:900px){nav{position:static;width:auto;max-height:300px}main{margin:0;padding:16px}section{padding:20px}.source{min-width:780px}.table-scroll{overflow:auto}h1{font-size:28px}}@media print{nav{display:none}main{margin:0;padding:0}section{break-inside:auto;border:0}.source{font-size:10px}details{display:block}}'''
    script = '''const search=document.getElementById('search');search.addEventListener('input',()=>{const query=search.value.toLowerCase();document.querySelectorAll('nav .files a').forEach(link=>{link.hidden=!link.textContent.toLowerCase().includes(query);});});document.getElementById('expand').addEventListener('click',()=>{document.querySelectorAll('details').forEach(item=>item.open=true);});'''
    # 面试问答只在 Markdown 主手册中维护，HTML 参考手册从同一段内容生成导航与展示。
    manual = (ROOT / "docs/项目学习手册.md").read_text(encoding="utf-8")
    interview = manual.split("## 面试常问八股文：直接按本项目回答\n", 1)[1].split("## 面试介绍这项目时怎么说\n", 1)[0]
    interview_html = '<section id="interview"><h2>面试常问八股文与答案</h2>' + MarkdownIt().render(interview) + '</section>'
    navigation = '<a href="#welcome">从这里开始</a><a href="#daily-operation">日常启动与备份</a><a href="#mental-model">系统流程</a><a href="#basics">编程基础词典</a><a href="#storage">存储与版本</a><a href="#documents">文档与分块</a><a href="#retrieval">混合检索原理</a><a href="#chat">多轮与流式</a><a href="#maintenance">维护练习</a><a href="#evaluation">效果评测</a><a href="#boundaries">边界与扩展</a><a href="#interview">面试问答</a><a href="#generated">运行生成的文件</a>'
    output = f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>知源 · 项目逐行学习手册</title><style>{style}</style></head><body><nav><h2>知源 · 学习手册</h2>{navigation}<h3>文件逐行阅读</h3><input id="search" aria-label="查找文件" placeholder="输入文件名筛选"><button id="expand">展开所有代码</button><div class="files">{"".join(links)}</div></nav><main>{chapters}{interview_html}{extra}{"".join(sections)}</main><script>{script}</script></body></html>'
    (ROOT / "docs/学习手册.html").write_text(output, encoding="utf-8")
    (ROOT / "docs/coverage.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Generated guide: {len(manifest)} files, {sum(item['lines'] for item in manifest)} explained lines")


if __name__ == "__main__":
    build()
