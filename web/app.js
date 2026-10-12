// 页面只负责交互；所有检索、密钥与文件处理都在后端。
const $ = (id) => document.getElementById(id);
let sessionId = crypto.randomUUID().replaceAll('-', '');
let activeRequest = null;
let replacingDocument = null;
const labels = { queued: '等待中', running: '处理中', completed: '已完成', failed: '失败', cancelled: '已取消', ready: '可问答', pending: '待入库' };

function notify(message) {
  $('toast').textContent = message;
  $('toast').hidden = false;
  setTimeout(() => { $('toast').hidden = true; }, 6000);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : `请求失败：${response.status}`);
  }
  return response.json();
}

function kbPath(kb = $('kb').value) {
  if (!kb) throw new Error('请先创建或选择一个知识库');
  return `/api/knowledge-bases/${kb}`;
}

function button(text, action) {
  const element = document.createElement('button');
  element.textContent = text;
  element.className = 'secondary';
  element.onclick = () => Promise.resolve().then(action).catch((error) => notify(error.message));
  return element;
}

async function loadKBs(selected) {
  const items = await api('/api/knowledge-bases');
  $('kb').replaceChildren();
  for (const item of items) $('kb').add(new Option(item.name, item.id));
  if (selected) $('kb').value = selected;
  await refresh();
}

async function refresh() {
  const kb = $('kb').value;
  if (!kb) return;
  const path = kbPath(kb);
  const [documents, jobs] = await Promise.all([api(`${path}/documents`), api(`${path}/jobs`)]);
  if ($('kb').value !== kb) return;
  $('documents').replaceChildren();
  for (const doc of documents) {
    const row = document.createElement('div');
    row.className = 'document';
    const name = document.createElement('div');
    name.textContent = `${doc.name} · v${doc.version} · ${labels[doc.status] || doc.status}`;
    row.append(name, button('更新', () => { replacingDocument = { kb, id: doc.id }; $('replacement').click(); }),
      button('删除', async () => { if (confirm(`删除「${doc.name}」并清理索引？`)) { await api(`${path}/documents/${doc.id}`, { method: 'DELETE' }); await refresh(); } }));
    $('documents').append(row);
  }
  $('jobs').replaceChildren();
  for (const job of jobs.slice(0, 5)) {
    const row = document.createElement('div');
    row.className = 'job';
    row.textContent = `${labels[job.status]} · ${job.stage}${job.error ? ' · ' + job.error : ''}`;
    if (job.status === 'failed') row.append(button('重试', async () => { await api(`${path}/jobs/${job.id}/retry`, { method: 'POST' }); await refresh(); }));
    $('jobs').append(row);
  }
}

$('kb-form').onsubmit = async (event) => {
  event.preventDefault();
  try {
    const kb = await api('/api/knowledge-bases', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: $('kb-name').value }) });
    $('kb-name').value = '';
    resetChat();
    await loadKBs(kb.id);
  } catch (error) { notify(error.message); }
};

$('upload-form').onsubmit = async (event) => {
  event.preventDefault();
  $('upload-button').disabled = true;
  try {
    const form = new FormData();
    form.append('file', $('file').files[0]);
    await api(`${kbPath()}/documents`, { method: 'POST', body: form });
    $('file').value = '';
    await refresh();
  } catch (error) { notify(error.message); }
  finally { $('upload-button').disabled = false; }
};

$('replacement').onchange = async () => {
  if (!$('replacement').files[0] || !replacingDocument) return;
  try {
    const form = new FormData();
    form.append('file', $('replacement').files[0]);
    const result = await api(`${kbPath(replacingDocument.kb)}/documents/${replacingDocument.id}`, { method: 'PUT', body: form });
    if (result.unchanged) notify('文件内容没有变化，无需重新入库');
    await refresh();
  } catch (error) { notify(error.message); }
  finally { $('replacement').value = ''; replacingDocument = null; }
};

function resetChat() {
  if (activeRequest) activeRequest.abort();
  sessionId = crypto.randomUUID().replaceAll('-', '');
  $('messages').replaceChildren();
  $('status').textContent = '新对话已就绪';
}

$('new-chat').onclick = resetChat;
$('kb').onchange = () => { resetChat(); refresh().catch((error) => notify(error.message)); };

function message(role, text) {
  $('messages').querySelector('.welcome')?.remove();
  const row = document.createElement('div');
  row.className = `message ${role}`;
  const title = document.createElement('div');
  title.className = 'role';
  title.textContent = role === 'user' ? '你' : '知源 · 基于文档回答';
  const body = document.createElement('div');
  body.className = 'body';
  body.textContent = text;
  row.append(title, body);
  $('messages').append(row);
  return { row, body };
}

function showSources(row, sources, kb) {
  for (const source of sources) {
    const details = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = `[${source.id}] ${source.name} · ${source.location} · v${source.version}`;
    const content = document.createElement('p');
    content.textContent = `${source.heading}\n${source.text}`;
    const link = document.createElement('a');
    link.href = `${kbPath(kb)}/documents/${source.doc_id}/download`;
    link.textContent = '下载当前版本原文';
    details.append(summary, content, link);
    row.append(details);
  }
}

$('chat-form').onsubmit = async (event) => {
  event.preventDefault();
  if (activeRequest) return;
  const question = $('question').value.trim();
  if (!question) return;
  const kb = $('kb').value;
  if (!kb) return notify('请先选择知识库');
  message('user', question);
  const answer = message('assistant', '');
  $('question').value = '';
  $('send').disabled = true;
  activeRequest = new AbortController();
  try {
    const response = await fetch(`${kbPath(kb)}/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: activeRequest.signal, body: JSON.stringify({ question, session_id: sessionId }) });
    if (!response.ok) throw new Error(`问答请求失败：${response.status}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let finished = false;
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const type = frame.split('\n').find((line) => line.startsWith('event:'))?.slice(6).trim();
        const raw = frame.split('\n').filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trim()).join('\n');
        if (!raw) continue;
        const data = JSON.parse(raw);
        if (type === 'status') $('status').textContent = data.stage;
        if (type === 'delta') answer.body.textContent += data.text;
        if (type === 'sources') showSources(answer.row, data.items, kb);
        if (type === 'error') throw new Error(data.message);
        if (type === 'done') { finished = true; $('status').textContent = `完成 · ${(data.timing.total_ms / 1000).toFixed(1)} 秒${data.warnings.length ? ' · ' + data.warnings.join('；') : ''}`; }
        $('messages').scrollTop = $('messages').scrollHeight;
      }
      if (done) break;
    }
    if (!finished) throw new Error('连接提前结束，回答可能不完整，请重试');
  } catch (error) {
    if (error.name !== 'AbortError') { answer.body.textContent += '\n[本次回答未完成]'; notify(error.message); $('status').textContent = '问答失败'; }
  } finally { activeRequest = null; $('send').disabled = false; }
};

async function init() {
  const health = await api('/api/health');
  $('mode').textContent = health.mode === 'production' ? '真实服务模式 · DeepSeek + BGE' : '演示模式 · 不调用真实模型';
  if (Object.values(health.checks).some((value) => value !== 'ok')) notify('部分依赖服务未启动，请检查 Milvus 和 Redis');
  await loadKBs();
  setInterval(() => refresh().catch(() => {}), 3000);
}

init().catch((error) => notify(error.message));
