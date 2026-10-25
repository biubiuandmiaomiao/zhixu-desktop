import { markdownOutline } from './markdown';

type Row = Record<string, any>;
const e = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
const btn = (action: string, label: string, attrs = '', cls = 'button text-button') => `<button type="button" class="${cls}" data-action="${action}" ${attrs}>${label}</button>`;
export const timestamp = (value: number) => `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, '0')}`;
export const notebook = (doc: Row) => doc.notebook || {tags: doc.tags || [], bookmarked: doc.bookmarked || false};
export const tagChips = (tags: string[]) => tags.map(tag => btn('filter-tag', '#' + e(tag), `data-tag="${e(tag)}"`, 'tag-chip')).join('');

export function libraryTools(data: Row, tag = '', bookmarked = false) {
  const tags = [...new Set<string>(data.documents.flatMap((doc: Row) => notebook(doc).tags || []))].sort();
  return `<div class="notebook-tools"><div class="toolbar">${btn('create-note', '＋ 新建笔记')}${btn('import-vault', '导入 Markdown 文件夹')}${btn('export-vault', '导出笔记库')}${btn('nav', '引用图谱 ↗', 'data-view="graph"')}</div><div class="library-filters"><label><input type="checkbox" id="bookmark-filter" ${bookmarked ? 'checked' : ''}/> 仅笔记书签</label><label for="tag-filter">标签</label><select id="tag-filter"><option value="">全部标签</option>${tags.map(t => `<option value="${e(t)}" ${tag === t ? 'selected' : ''}>#${e(t)}</option>`).join('')}</select>${tag || bookmarked ? btn('clear-filters', '清除筛选') : ''}</div></div>`;
}

export function notebookAside(detail: Row) {
  const meta = detail.notebook || {};
  const outline = markdownOutline(detail.document.content);
  return `<div class="context-box notebook-metadata"><h3>笔记信息</h3><p class="note-path">${e(meta.path || detail.document.title)}</p><div class="tag-list">${tagChips(meta.tags || []) || '<span class="muted">暂无标签 · 正文中使用 #标签</span>'}</div></div>
  ${outline.length ? `<div class="context-box note-toc"><h3>目录</h3><nav aria-label="笔记目录">${outline.map(h => btn('heading', e(h.text), `data-heading="${e(h.id)}" style="padding-left:${Math.min(h.depth - 1, 3) * 10}px"`)).join('')}</nav></div>` : ''}
  <div class="context-box" data-testid="backlinks"><h3>反向链接 <span class="pill">${(meta.backlinks || []).length}</span></h3>${(meta.backlinks || []).map((link: Row) => `<div class="backlink-entry">${btn('document', e(link.title) + ' ↗', `data-id="${e(link.document_id)}"`)}<small>${link.kind === 'wiki' ? '双链引用' : 'Markdown 引用'} · ${e(link.target)}</small></div>`).join('') || '<p>还没有其他笔记引用这里。</p>'}</div>
  ${(meta.outgoing || []).length ? `<div class="context-box"><h3>笔记链接</h3>${meta.outgoing.map((link: Row) => `<div class="outgoing-link">${btn('note-link', e(link.label), `data-doc="${e(detail.document.id)}" data-target="${e(link.target)}"`)}${link.unresolved ? `<small class="source-warning">${link.reason === 'ambiguous' ? '有多个同名笔记' : '目标尚未解析'}</small>` : ''}</div>`).join('')}</div>` : ''}`;
}

export function screenshotGallery(assets: Row[]) {
  const images = assets.filter(a => /^data:image\/(?:jpeg|png|webp);base64,[A-Za-z0-9+/=]+$/.test(a.data_url || ''));
  return images.length ? `<section class="screenshot-section"><h3>视频截图 <span class="pill">${images.length}</span></h3><div class="screenshot-gallery">${images.map(a => `<figure><img src="${a.data_url}" alt="${e(a.caption || '视频截图')}" loading="lazy"/><figcaption>${timestamp(Number(a.time ?? a.start ?? a.timestamp ?? 0))} · ${e(a.caption || '视频画面')}${a.url ? btn('source-video', '跳转视频 ↗', `data-url="${e(a.url)}" data-time="${Number(a.time ?? a.start ?? 0)}"`) : ''}</figcaption></figure>`).join('')}</div></section>` : '';
}

export function mediaJobs(jobs: Row[]) {
  if (!jobs.length) return '';
  const names: Row = {queued:'等待中',running:'处理中',completed:'已完成',failed:'失败',cancelled:'已取消'};
  const stages: Row = {queued:'等待处理',copying:'保存媒体文件',probing:'检查音视频',subtitles:'查找可用字幕',downloading:'下载公开视频',loading_model:'加载本地转写模型',transcribing:'本地转写',screenshots:'提取时间点截图',saving:'保存资料与来源',completed:'导入完成',failed:'导入失败',cancelled:'任务已取消',interrupted:'上次任务被中断',deleted:'资料已删除'};
  return `<section class="media-jobs" aria-label="媒体导入任务"><div class="section-title"><h2>媒体导入任务</h2><span class="muted">字幕优先 · 无字幕时本地转写</span></div>${jobs.slice(0, 12).map(job => `<div class="media-job" data-job-id="${e(job.id)}"><div class="job-heading"><strong>${e(job.title || job.source_name || job.source_url || '媒体导入')}</strong><span class="pill ${job.status === 'failed' ? 'amber' : ''}">${names[job.status] || e(job.status)}</span></div><p>${e(stages[job.stage] || job.stage || '')} · ${Math.max(0, Math.min(100, Number(job.progress || 0)))}%</p><progress value="${Math.max(0, Math.min(100, Number(job.progress || 0)))}" max="100" aria-label="导入进度"></progress>${job.error ? `<p class="source-warning" role="status">${e(job.error)}</p>` : ''}<div class="toolbar">${job.status === 'completed' && job.document_id ? btn('document', '打开资料 ↗', `data-id="${e(job.document_id)}"`) : ''}${['failed','cancelled'].includes(job.status) && job.retryable ? btn('retry-media-job', '重试', `data-id="${e(job.id)}"`) : ''}${['queued','running'].includes(job.status) ? btn('cancel-media-job', '取消任务', `data-id="${e(job.id)}"`) : ''}</div></div>`).join('')}</section>`;
}

export function graphView(graph: Row | null) {
  if (!graph) return '<div class="empty"><h3>正在读取引用图谱…</h3></div>';
  const nodes: Row[] = graph.nodes || [], edges: Row[] = graph.edges || [];
  const size = Math.max(780, 600 + Math.ceil(nodes.length / 16) * 210), center = size / 2;
  const positions = new Map<string, {x:number;y:number}>();
  nodes.forEach((n, i) => {
    const ring = Math.floor(i / 16), count = Math.min(16, nodes.length - ring * 16), angle = (i % 16) / count * 2 * Math.PI;
    positions.set(n.id, {x:center + Math.cos(angle) * (ring ? 240 + ring * 105 : Math.min(240, 40 + nodes.length * 15)), y:center + Math.sin(angle) * (ring ? 240 + ring * 105 : Math.min(240, 40 + nodes.length * 15))});
  });
  return `<div class="page-heading"><div class="eyebrow">FOLLOW THE REFERENCES</div><h1>引用图谱</h1><p>笔记里的明确引用和你已确认的知识关联。点击节点打开资料。</p></div><div class="graph-controls"><label for="graph-focus">聚焦笔记</label><select id="graph-focus"><option value="">显示全部</option>${nodes.map(n => `<option value="${e(n.id)}">${e(n.title)}</option>`).join('')}</select><span class="graph-legend"><i></i> 明确笔记链接 <i class="relation"></i> 已确认 AI / 关键词关联</span><span class="muted">${nodes.length} 节点 · ${edges.length} 条边${graph.truncated ? ' · 仅显示最近 200 份资料' : ''}</span></div>${nodes.length ? `<div class="graph-scroll" data-testid="note-graph"><svg class="note-graph" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" style="width:${size}px;height:${size}px" role="group" aria-label="笔记引用图谱">${edges.map(edge => { const a = positions.get(edge.source), b = positions.get(edge.target); return a && b ? `<line class="graph-edge ${edge.kind === 'relation' ? 'relation' : ''}" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" data-source="${e(edge.source)}" data-target="${e(edge.target)}"><title>${edge.kind === 'relation' ? '已确认关联：' + e(edge.relation_kind) : '明确引用：' + e(edge.kind)}</title></line>` : ''; }).join('')}${nodes.map(n => { const p = positions.get(n.id)!; return `<g class="graph-node" role="button" tabindex="0" aria-label="打开笔记：${e(n.title)}" data-action="document" data-id="${e(n.id)}" transform="translate(${p.x},${p.y})"><circle r="19"/><text text-anchor="middle" y="40">${e(n.title.length > 14 ? n.title.slice(0,14) + '…' : n.title)}${n.bookmarked ? ' ★' : ''}</text><title>${e(n.title)}${n.tags?.length ? ' · #' + e(n.tags.join(' #')) : ''}</title></g>`; }).join('')}</svg></div><details class="graph-edge-list"><summary>查看链接与关联明细</summary>${edges.map(edge => `<p><span class="pill">${edge.kind === 'relation' ? '已确认关联' : '明确链接'}</span> ${e(nodes.find(n=>n.id===edge.source)?.title)} → ${e(nodes.find(n=>n.id===edge.target)?.title)}${edge.relation_kind ? ' · ' + e(edge.relation_kind) : ''}</p>`).join('') || '<p class="muted">尚无引用边。可在笔记里加入 [[笔记标题]]。</p>'}</details>` : '<div class="empty"><h3>还没有笔记</h3><p>创建笔记并用 [[笔记标题]] 连接资料。</p></div>'}`;
}

export function featureModal(state: Row) {
  const close = btn('close-modal', '×', 'aria-label="关闭"', 'icon-button');
  const heading = (title:string) => `<div class="modal-heading"><h2>${title}</h2>${close}</div>`;
  if (state.modal === 'create-note') return `${heading('新建笔记')}<form id="create-note-form"><label for="note-title">笔记标题</label><input id="note-title" name="title" value="${e(state.newNoteTitle || '')}" required maxlength="200"/><label for="note-content">Markdown 正文</label><textarea id="note-content" name="content" placeholder="用 [[笔记标题]] 连接其他笔记，用 #标签 分类。" required></textarea><div class="modal-footer"><small>支持 Markdown、双链和标签</small><button class="button primary" type="submit">创建笔记</button></div></form>`;
  if (state.modal === 'link-resolution') {
    const link = state.linkResolution;
    return `${heading(link.reason === 'ambiguous' ? '选择要打开的笔记' : '笔记链接尚未解析')}<p class="muted">${e(link.target)}</p>${link.reason === 'unsafe' ? '<p>该链接不属于知识库内的安全笔记路径。</p>' : (link.candidates || []).length ? `<div class="link-candidates">${link.candidates.map((c:Row) => `<div>${btn('choose-note-link', e(c.title), `data-id="${e(c.document_id)}"`)}<small>${e(c.path)}</small></div>`).join('')}</div><p class="small-note">打开后可在原笔记中将链接改为完整笔记路径，消除歧义。</p>` : `<p>目标笔记可能尚未创建，或已经删除。</p>${btn('create-linked-note', '按此标题创建笔记', '', 'button primary')}`}`;
  }
  if (state.modal === 'versions') return `${heading('版本历史')}<p class="muted">最多显示最近 100 个版本，长正文预览前 8000 字；恢复使用完整版本。恢复前会保留当前版本，旧来源索引和练习会重新校验。</p><div class="version-list">${(state.versions || []).map((v:Row,i:number) => `<details ${i===0?'open':''}><summary><strong>${e(v.title)}</strong><span>${new Date(v.created_at).toLocaleString('zh-CN')} · ${e(({import:'导入',edit:'编辑',tutorial:'教程生成',restore:'版本恢复',migration:'旧数据升级'} as Row)[v.reason] || v.reason)}</span></summary><pre>${e(v.content)}</pre>${v.preview_truncated ? '<p class="muted">此处为部分预览，完整内容仍保存在本地。</p>' : ''}${btn('restore-version', '恢复这个版本', `data-id="${e(v.id)}"`, 'button')}</details>`).join('') || '<p>暂无历史版本。</p>'}</div>`;
  if (state.modal === 'source-map') return `${heading('选择原文出处')}<p class="muted">收藏内容：</p><blockquote class="selected-quote">${e(state.cardSelection?.text)}</blockquote><p class="small-note">请选择能够支持这段理解的当前原始片段。AI 改写内容需要你明确确认出处。</p><form id="source-map-form"><div class="source-picker">${(state.sourceMapSegments || []).map((s:Row,i:number) => `<label class="source-pick"><input type="checkbox" name="source_ids" value="${e(s.id)}" ${(state.sourceMapIds || []).includes(s.id)?'checked':''}/><span><strong>来源 ${i+1}${s.start!=null?' · '+timestamp(Number(s.start)):''}</strong><span>${e(s.text)}</span></span></label>`).join('') || '<p class="source-warning">当前资料没有可用原文，无法建立收藏出处。</p>'}</div><div class="modal-footer"><small>至少选择一个当前有效来源</small><button class="button primary" type="submit" ${(state.sourceMapSegments || []).length ? '' : 'disabled'}>确认出处并保存</button></div></form>`;
  if (state.modal === 'tutorial-options') return `${heading('AI 整理为教程')}<form id="tutorial-form"><label for="tutorial-style">笔记风格</label><select id="tutorial-style" name="style">${[['tutorial','学习教程'],['summary','精简摘要'],['outline','结构大纲'],['steps','操作步骤'],['concepts','概念解释'],['questions','问答整理'],['timeline','时间线'],['review','复习要点'],['examples','案例讲解']].map(([v,t])=>`<option value="${v}">${t}</option>`).join('')}</select><label class="checkbox-label"><input type="checkbox" name="use_images" ${state.detail?.assets?.length?'':'disabled'}/> 结合当前视频截图理解画面</label><p class="small-note">结合画面需要支持图片的对话模型。生成保留原文引用与历史版本。</p><div class="modal-footer"><small>${state.detail?.assets?.length || 0} 张受管理截图</small><button class="button primary" type="submit">开始整理</button></div></form>`;
  return '';
}
