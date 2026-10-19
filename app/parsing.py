# ----------------------------------------------------------------------
# 阅读入口：读取 Markdown、Word、PDF，统一成 Block，再切成可检索 Chunk 的数据字典。
# 解析解决文件格式，清洗解决文本噪声，分块解决检索粒度。它们是三个独立问题。本实现按字符计数；标题参与内容哈希和向量化，位置信息用于引用。
# ----------------------------------------------------------------------
import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Block:
    text: str
    heading: str
    location: str


def clean(text):
    text = text.replace("\x00", "").replace("\r\n", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ----------------------------------------------------------------------
# 解析 Markdown 不是把所有 # 直接删掉，而是保留标题结构。
# 例如“人事 / 休假 / 年假”会成为标题路径，短正文也能带上所属章节的语境。
# 代码示例：Block(text='每年五天', heading='人事 / 年假', location='行号范围')。
# 类似用法：网页 h1/h2/h3、Word 标题样式，都可以转成同一种 Block 后统一分块。
# 面试问：为什么标题也参与向量化？答：正文“每年五天”太模糊，标题补充它讲的是年假。
# ----------------------------------------------------------------------
def parse_markdown(path):
    from markdown_it import MarkdownIt
    source = path.read_text(encoding="utf-8-sig")
    tokens = MarkdownIt("commonmark").enable("table").parse(source)
    lines = source.splitlines()
    headings = []
    blocks = []
    in_table = False
    for i, token in enumerate(tokens):
        if token.type == "table_open":
            start, end = token.map
            blocks.append(Block("\n".join(lines[start:end]), " > ".join(t for _, t in headings), f"第 {start + 1}～{end} 行（表格）"))
            in_table = True
        if token.type == "table_close":
            in_table = False
        if in_table:
            continue
        if token.type == "heading_open":
            level = int(token.tag[1:])
            headings = [(depth, title) for depth, title in headings if depth < level]
            headings.append((level, tokens[i + 1].content))
        if token.type in {"inline", "fence", "code_block"}:
            if i and tokens[i - 1].type == "heading_open":
                continue
            line = (token.map or [0])[0] + 1
            blocks.append(Block(token.content, " > ".join(t for _, t in headings), f"第 {line} 行附近"))
    return blocks


# ----------------------------------------------------------------------
# Word 段落和表格按文档顺序读取，避免先取全部段落再取表格导致上下文错位。
# 表格行加上列名后，像“天数: 5；类型: 年假”，比孤立数字 5 更适合检索。
# 类似用法：数据库导出的 CSV，也可把列名和行值组合成有意义的文本。
# 面试问：Word 的标题怎么认？答：这里用标题样式名称；只调大字号但没设标题样式可能认不出。
# ----------------------------------------------------------------------
def parse_docx(path):
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    document = Document(path)
    headings = []
    blocks = []
    for index, item in enumerate(document.iter_inner_content(), 1):
        if isinstance(item, Paragraph):
            match = re.search(r"(?:Heading|标题)\s*(\d+)", item.style.name or "")
            if match:
                level = int(match.group(1))
                headings = [(d, t) for d, t in headings if d < level]
                headings.append((level, item.text))
            else:
                blocks.append(Block(item.text, " > ".join(t for _, t in headings), f"第 {index} 个内容块"))
        elif isinstance(item, Table):
            rows = [" | ".join(cell.text for cell in row.cells) for row in item.rows]
            if rows:
                for row in rows[1:] or rows:
                    blocks.append(Block(rows[0] + "\n" + row, " > ".join(t for _, t in headings), f"第 {index} 个内容块（表格）"))
    return blocks


def pdf_heading_level(text):
    text = text.strip()
    if len(text) > 80 or text.endswith(("。", "；", ";", "!", "！", "?", "？")):
        return None
    if re.match(r"^第[一二三四五六七八九十百\d]+章\s*\S+", text):
        return 1
    if re.match(r"^第[一二三四五六七八九十百\d]+节\s*\S+", text):
        return 2
    match = re.match(r"^(\d+(?:\.\d+)+)\s+\S+", text)
    if match:
        return min(match.group(1).count(".") + 1, 6)
    if re.match(r"^(?:\d+\.\s+|[一二三四五六七八九十]+、)\S+", text):
        return 1
    return None


# ----------------------------------------------------------------------
# PDF 更像“纸上的文字摆放结果”，不一定自带可靠的章节结构。
# 这里抽取文本、过滤多页重复边缘文字，再用规则猜标题；页码保留下来供引用定位。
# 扫描版 PDF 可能只有图片，需要 OCR；当前解析器不会自动完成 OCR。
# 类似用法：复杂双栏论文、跨页表格需要更强版面解析，不能只靠清洗字符串解决。
# 面试问：解析失败和模型不聪明怎么区分？答：先检查抽出的正文是否正确，再看召回和生成。
# 标题识别和页眉过滤都是启发式，可能误判，应通过样例文档人工抽查。
# ----------------------------------------------------------------------
def parse_pdf(path):
    from pypdf import PdfReader
    reader = PdfReader(path)
    pages = [(page.extract_text() or "").splitlines() for page in reader.pages]
    edges = Counter(line.strip() for lines in pages for line in set(lines[:2] + lines[-2:]) if line.strip())
    blocks = []
    headings = []
    for page_number, lines in enumerate(pages, 1):
        kept = [line for i, line in enumerate(lines) if not (
            len(pages) >= 3 and (i < 2 or i >= len(lines) - 2)
            and edges[line.strip()] >= max(3, len(pages) * 0.7)
        )]
        paragraph = []
        for line in kept:
            level = pdf_heading_level(line)
            if level:
                if paragraph:
                    blocks.append(Block("\n".join(paragraph), " > ".join(t for _, t in headings), f"第 {page_number} 页"))
                    paragraph = []
                headings = [(depth, title) for depth, title in headings if depth < level]
                headings.append((level, line.strip()))
            else:
                paragraph.append(line)
        if paragraph:
            blocks.append(Block("\n".join(paragraph), " > ".join(t for _, t in headings), f"第 {page_number} 页"))
    if not any(clean(block.text) for block in blocks):
        raise ValueError("PDF 没有可提取文本，可能是扫描件；请先进行 OCR")
    return blocks


def parse(path):
    path = Path(path)
    parsers = {".md": parse_markdown, ".markdown": parse_markdown, ".docx": parse_docx, ".pdf": parse_pdf}
    if path.suffix.lower() not in parsers:
        raise ValueError("仅支持 PDF、DOCX、Markdown；旧版 DOC 请先另存为 DOCX")
    return parsers[path.suffix.lower()](path)


# ----------------------------------------------------------------------
# 分块就是把长资料剪成适合检索的小段，同时保留一点前后文。
# 例如 size=100、overlap=20：第一段约 0~100，下一段约从 80 开始，交界处不会一下断掉。
# 本实现还会尝试在后半段句末切开；实际边界不一定正好是 100，所以这是示意。
# 块太大：无关内容变多、上下文费用增加；块太小：条件和结论可能被拆散。
# 相似方案：固定窗口简单；按章节更有结构；语义分块更灵活但需要额外计算与评测。
# 哈希相当于“内容指纹”：同样输入算出同样值，用集合快速识别重复，不是加密。
# 这里输入是 heading + 换行 + text：正文一样但标题不同，不会被当成同一内容。
# 代码示例：seen = set(); digest = sha256((heading + '\n' + text).encode()).hexdigest()
# 这只能发现标准化后完全相同的内容，不能把“年假五天”和“可休五天年假”自动合并。
# 面试问：哈希去重与向量去重有什么区别？答：前者匹配精确内容，后者按相似度近似匹配。
# 追问：哈希绝不碰撞吗？答：不是数学上的绝不；SHA-256 在这里的工程碰撞风险极低。
# overlap 必须小于 size，否则窗口可能不向前走；位置字段用于追溯，不参与内容哈希。
# ----------------------------------------------------------------------
def split_blocks(blocks, size, overlap):
    if overlap >= size or overlap < 0:
        raise ValueError("重叠长度必须大于等于 0 且小于分块长度")
    groups = []
    for block in blocks:
        text = clean(block.text)
        if not text:
            continue
        if groups and groups[-1].heading == block.heading and groups[-1].location == block.location:
            groups[-1].text += "\n\n" + text
        else:
            groups.append(Block(text, block.heading, block.location))
    result = []
    for block in groups:
        start = 0
        while start < len(block.text):
            end = min(start + size, len(block.text))
            if end < len(block.text):
                candidates = [block.text.rfind(mark, start + size // 2, end) for mark in ["\n", "。", "！", "？", ";", ". "]]
                boundary = max(candidates)
                if boundary >= start + max(size // 2, overlap):
                    end = boundary + 1
            text = block.text[start:end].strip()
            if text:
                content = block.heading + "\n" + text
                result.append({"text": text, "heading": block.heading, "location": block.location,
                               "content_hash": hashlib.sha256(content.encode()).hexdigest()})
            if end == len(block.text):
                break
            start = end - overlap
    if not result:
        raise ValueError("文档清洗后没有有效正文")
    return result
