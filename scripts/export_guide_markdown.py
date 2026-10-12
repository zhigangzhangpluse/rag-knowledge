"""将教学章节和当前源代码导出为可离线阅读的 Markdown 手册。"""
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import build_guide as guide


class Node:
    def __init__(self, tag='', attrs=None):
        self.tag, self.attrs, self.children = tag, dict(attrs or []), []

    def text(self):
        return ''.join(child if isinstance(child, str) else child.text() for child in self.children)


class ChapterParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {'br', 'hr', 'img', 'meta', 'link', 'input'}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def cell(text):
    return text.replace('|', '&#124;').replace('\n', '<br>')


def render(node):
    if isinstance(node, str):
        return node
    body = ''.join(render(child) for child in node.children)
    tag = node.tag
    if tag in {'h1', 'h2', 'h3', 'h4'}:
        return '\n\n' + '#' * int(tag[1]) + ' ' + body.strip() + '\n\n'
    if tag == 'code':
        fence = '`' * (max([len(match) for match in re.findall(r'`+', body)] or [0]) + 1)
        return fence + ' ' + body + ' ' + fence
    if tag in {'strong', 'b'}:
        return '**' + body + '**'
    if tag == 'a':
        return '[' + body + '](' + node.attrs.get('href', '') + ')'
    if tag == 'br':
        return '  \n'
    if tag in {'ol', 'ul'}:
        items = [child for child in node.children if isinstance(child, Node) and child.tag == 'li']
        return '\n\n' + '\n'.join((str(i) + '. ' if tag == 'ol' else '- ') + render(item).strip() for i, item in enumerate(items, 1)) + '\n\n'
    if tag == 'table':
        rows = []
        def collect(current):
            if not isinstance(current, Node):
                return
            if current.tag == 'tr':
                rows.append([cell(render(item).strip()) for item in current.children if isinstance(item, Node) and item.tag in {'td', 'th'}])
            else:
                for child in current.children:
                    collect(child)
        collect(node)
        if not rows:
            return ''
        lines = ['| ' + ' | '.join(row) + ' |' for row in rows]
        lines.insert(1, '| ' + ' | '.join(['---'] * len(rows[0])) + ' |')
        return '\n\n' + '\n'.join(lines) + '\n\n'
    if tag == 'div' and node.attrs.get('class') == 'flow':
        return '\n\n' + ' → '.join(child.text() for child in node.children if isinstance(child, Node) and child.tag == 'span') + '\n\n'
    if tag in {'p', 'div', 'section'}:
        return '\n\n' + body.strip() + '\n\n'
    return body


def main():
    parser = ChapterParser()
    parser.feed((guide.ROOT / 'docs/chapters.html').read_text(encoding='utf-8'))
    output = ['# RAG 项目学习手册 · Markdown 完整版',
              '本手册包含系统原理、运行与维护方法、各文件用途、完整源码及逐行解释。代码行号对应导出时的源码。真实 .env 密钥不收录。',
              '## 建议学习顺序',
              '1. 先读日常启动与备份，亲自启动项目并问一道题。\n2. 阅读系统流程、编程词典和三个数据库的职责。\n3. 按 config → database → parsing → models → index → retrieval → generation → main → web 的顺序阅读。\n4. 每次只读一个函数：写下输入、处理步骤、输出，然后跟踪一条数据。\n5. 完成维护练习，对照测试结果确认修改是否正确。',
              '## 文件目录']
    filenames = list(guide.NOTES)
    for index, filename in enumerate(filenames, 1):
        output.append(f'- [{filename}](#source-{index})：{guide.NOTES[filename]["purpose"]}')
    output.append(re.sub(r'\n{3,}', '\n\n', render(parser.root)))
    output.append('## 运行产生的文件\n\n.env 保存本机密钥与配置；data 保存原文与 SQLite；models 保存模型权重；D:/RAGRuntime/volumes 保存实际容器数据；reports 保存验收和评测结果。第三方环境 .venv 和缓存不属于手写源码。docs/coverage.json 保存 HTML 手册的源文件哈希。')
    manifest = []
    languages = {'.py': 'python', '.js': 'javascript', '.css': 'css', '.html': 'html', '.ps1': 'powershell', '.yaml': 'yaml', '.json': 'json', '.md': 'markdown'}
    for index, filename in enumerate(filenames, 1):
        path = guide.ROOT / filename
        content = path.read_text(encoding='utf-8-sig')
        notes = guide.NOTES[filename]
        rows = guide.describe_python(content, notes) if path.suffix == '.py' else guide.describe_other(path, content)
        output.extend([f'<a id="source-{index}"></a>', f'## 文件 {index}：{filename}',
                       '### 文件用途\n\n' + notes['purpose'], '### 知识点与扩展\n\n' + notes['knowledge']])
        for name, meaning in notes.get('functions', {}).items():
            output.append(f'- `{name}`：{meaning}')
        fence = '`' * max(3, max([len(match) for match in re.findall(r'`+', content)] or [0]) + 1)
        output.extend(['### 完整源码', fence + languages.get(path.suffix, 'text') + '\n' + content.rstrip('\n') + '\n' + fence,
                       '### 逐行解释\n\n将上面的代码行号与下表对照。多行语句的续行会说明它属于哪条语句。',
                       '| 源码行号 | 解释 |\n| --- | --- |'])
        output.extend(f'| {number} | {cell(explanation)} |' for number, _, explanation in rows)
        manifest.append({'file': filename, 'lines': len(rows), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    result = '\n\n'.join(output) + '\n'
    (guide.ROOT / 'docs/项目学习手册.md').write_text(result, encoding='utf-8')
    (guide.ROOT / 'docs/markdown-coverage.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Exported {len(manifest)} files, {sum(row["lines"] for row in manifest)} source lines.')


if __name__ == '__main__':
    main()
