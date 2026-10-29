import './style.css';
import { renderMarkdown, headingId } from './markdown';
import { libraryTools, notebook, notebookAside, screenshotGallery, mediaJobs, graphView, featureModal, tutorialAttempts, timestamp } from './notebook-ui';

type Row = Record<string, any>;
declare global {
  interface Window { knowledge: {
    call(action: string, args?: Row): Promise<any>;
    saveCredential(value: string): Promise<any>;
    saveSearchCredential(value: string): Promise<any>;
    importFile(): Promise<Row | null>;
    importVault(): Promise<Row | null>;
    exportVault(): Promise<Row | null>;
    importMedia(options?:Row): Promise<Row | null>;
    exportDocument(id: string): Promise<boolean>;
    openLink(url: string): Promise<void>;
    onClosing(callback: () => void): void;
    finishClose(saved: boolean): Promise<void>;
  } }
}

const api = window.knowledge;
const root = document.querySelector<HTMLDivElement>('#app')!;
const state: Row = { view: 'library', data: null, selected: null, detail: null, busy: '', modal: '',
  quiz: null, question: 0, search: '', results: null, answer: null, askScope: '', sourceTab: false,
  tagFilter: '', bookmarkFilter: false, graph: null, jobs: [], followUps: [], followUpDraft: '' };
let draftTimer: ReturnType<typeof setTimeout> | undefined;
const pendingDocumentRefresh = new Set<string>();
const escape = (x: unknown) => String(x ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
const e = escape;
const typeNames: Row = { single: '单选题', multiple: '多选题', short: '简答题' };
const relationNames: Row = { shared: '同一知识点', prerequisite: '前置知识 → 进阶', supplement: '补充案例', difference: '内容差异' };
const entityKindNames: Row = { person: '人物', org: '组织', product: '产品', work: '作品', place: '地点', tech: '技术', concept: '概念' };
const icon = (name: string) => {
  const paths: Record<string, string> = {
    book: '<path d="M4 4h6a3 3 0 0 1 3 3v14a4 4 0 0 0-4-2H4z"/><path d="M13 7a3 3 0 0 1 3-3h5v15h-5a4 4 0 0 0-3 2"/>',
    star: '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9z"/>',
    link: '<circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><circle cx="12" cy="18" r="3"/><path d="m7.5 8.5 3 7m6-7-3 7M9 6h6"/>',
    brain: '<path d="M12 4c-4-4-9 1-7 5-4 2-3 8 1 8 0 4 6 5 6 1V4zm0 0c4-4 9 1 7 5 4 2 3 8-1 8 0 4-6 5-6 1"/><path d="m7 9 3 2m7-2-3 2M7 16l3-2m7 2-3-2"/>',
    quiz: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 3h6v4H9zM9 12h6m-6 4h4"/>',
    chat: '<path d="M21 11a8 8 0 0 1-8 8H7l-4 3v-8a8 8 0 0 1 8-10h2a8 8 0 0 1 8 7Z"/><path d="M8 10h8m-8 4h5"/>',
    gear: '<path d="m9 3 6 0 1 3 3 1 2 5-2 4-3 1-1 4H9l-1-4-3-1-2-4 2-5 3-1z"/><circle cx="12" cy="12" r="3"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
    search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
    play: '<rect x="3" y="4" width="18" height="16" rx="4"/><path d="m10 8 6 4-6 4z"/>',
    leaf: '<path d="M20 3C8 2 2 8 5 15c7 5 15-1 15-12Z"/><path d="M4 21 16 9"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    close: '<path d="m6 6 12 12M6 18 18 6"/>',
  };
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.book}</svg>`;
};
const date = (value: string) => new Date(value).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
const button = (action: string, text: string, cls = 'button', attrs = '') => `<button class="${cls}" data-action="${action}" ${attrs}>${text}</button>`;
const empty = (title: string, text: string, action = '', label = '') => `<div class="empty"><span class="empty-icon">${icon('leaf')}</span><h3>${title}</h3><p>${text}</p>${action ? button(action, label, 'button primary') : ''}</div>`;

function markdown(text: string) {
  return renderMarkdown(text,{documentId:state.selected,sources:state.detail?.segments || [],assets:state.detail?.assets || []});
}

function toast(message: string, error = false) {
  document.querySelector('#toast')?.remove();
  const box = document.createElement('div');
  box.id = 'toast'; box.className = error ? 'error' : ''; box.setAttribute('role', error ? 'alert' : 'status');
  box.textContent = message; document.body.append(box);
  setTimeout(() => box.remove(), error ? 10000 : 5000);
}

async function refresh() {
  state.data = await api.call('bootstrap');
  state.jobs = state.data.media_jobs || state.jobs || [];
  const live = new Set(state.data.documents.map((d: Row) => d.id));
  if (state.quiz && !state.data.sessions.some((s: Row) => s.id === state.quiz.id)) state.quiz = null;
  if (state.answer?.citations?.some((s: Row) => !live.has(s.document_id))) state.answer = null;
  if (state.results) state.results.results = state.results.results.filter((s: Row) => live.has(s.document_id));
  if (state.askScope && !live.has(state.askScope)) state.askScope = '';
}
async function work(label: string, fn: () => Promise<void>) {
  if (state.busy) return;
  state.busy = label; render();
  try { await fn(); } catch (err) { toast((err as Error).message.replace(/^Error invoking remote method '[^']+': Error: /, ''), true); }
  finally { state.busy = ''; render(); }
}

function nav() {
  const d = state.data;
  const items = [['library', 'book', '知识库', d.documents.length], ['cards', 'star', '我的收藏', d.cards.length],
    ['relations', 'link', '知识关联', d.relations.filter((r: Row) => r.status === 'confirmed').length], ['graph', 'link', '引用图谱', ''],
    ['ask', 'chat', '知识问答', ''], ['review', 'quiz', '复习与题库', d.sessions.length], ['memory', 'brain', '长期记忆', d.memories.length]];
  return `<aside class="sidebar"><div class="brand"><span class="brand-mark">${icon('leaf')}</span><div>知序<small>ZHIXU · YOUR LEARNING SPACE</small></div></div>
    ${button('new', icon('plus') + ' 导入学习资料', 'button primary add-button')}
    <div class="nav-label">我的学习空间</div><nav>${items.map(([view, ico, label, count]) => `<button data-action="nav" data-view="${view}" class="nav-item ${state.view === view ? 'active' : ''}">${icon(String(ico))}<span>${label}</span>${count !== '' ? `<small>${count}</small>` : ''}</button>`).join('')}</nav>
    <div class="sidebar-bottom"><div class="local-badge"><i></i> 本地知识库 <span>只属于你</span></div><button data-action="nav" data-view="settings" class="nav-item ${state.view === 'settings' ? 'active' : ''}">${icon('gear')}<span>模型与设置</span></button><div class="version">知序 · Windows 预览版 0.4.5</div></div></aside>`;
}

function library() {
  if (state.detail) return detail();
  const d = state.data;
  const docs = d.documents.filter((doc: Row) => (!state.bookmarkFilter || notebook(doc).bookmarked) && (!state.tagFilter || (notebook(doc).tags || []).some((tag: string) => tag === state.tagFilter || tag.startsWith(state.tagFilter + '/'))));
  return `<div class="welcome"><div><div class="eyebrow">LEARN · CONNECT · REMEMBER</div><h1>让知识，在这里生长<span>。</span></h1><p>把看过的教程，连接成自己的知识。</p></div><div class="welcome-art"><span class="orbit one"></span><span class="orbit two"></span><span class="art-icon">${icon('leaf')}</span><small>每一份理解，都有迹可循</small></div></div>
    <div class="stats">${[['book', d.documents.length, '份学习资料'], ['star', d.cards.length, '条知识收藏'], ['link', d.relations.filter((r: Row) => r.status === 'confirmed').length, '个已确认关联'], ['quiz', d.sessions.filter((s: Row) => s.status === 'completed').length, '次完成复习']].map(([ico, count, label]) => `<div class="stat"><span>${icon(String(ico))}</span><strong>${count}</strong><small>${label}</small></div>`).join('')}</div>
    <div id="media-jobs-region">${mediaJobs(state.jobs)}</div>
    <div class="section-title"><h2>我的知识库 <span>${docs.length}${docs.length !== d.documents.length ? ' / ' + d.documents.length : ''}</span></h2>${button('new', icon('plus') + ' 添加资料', 'button subtle')}</div>
    ${libraryTools(d, state.tagFilter, state.bookmarkFilter)}
    <div id="library-documents">${docs.length ? `<div class="document-grid">${docs.map((doc: Row, i: number) => `<button class="document-card" data-action="document" data-id="${e(doc.id)}"><div class="document-top"><span class="document-icon tone-${i % 3}">${icon(doc.url ? 'play' : 'book')}</span><span class="pill">${notebook(doc).bookmarked ? '★ 书签 · ' : ''}${({ text: '文本笔记', subtitle: '视频字幕', tutorial: 'AI 教程' } as Row)[doc.kind] || '学习资料'}</span></div><h3>${e(doc.title)}</h3><p>${e(doc.content.replace(/[#*`]/g, '').slice(0, 100))}</p><div class="document-tags">${(notebook(doc).tags || []).slice(0,4).map((tag: string) => `<span>#${e(tag)}</span>`).join('')}</div><div class="document-footer"><span>${date(doc.updated_at)} 更新</span>${icon('arrow')}</div></button>`).join('')}</div>` : d.documents.length ? empty('没有符合筛选条件的笔记', '清除标签或书签筛选以查看其他资料。', 'clear-filters', '清除筛选') : empty('第一份知识，从这里开始', '导入公开视频、本地音视频、Markdown 或文本，开始建立自己的学习资料库。', 'new', '导入第一份资料')}</div>
    <div class="tip-card">${icon('link')}<div><strong>知识之间，也会相互照亮</strong><p>打开一份资料，发现相关教程；确认关联后，问答时能一起查阅。</p></div>${button('nav', '了解知识关联 ' + icon('arrow'), 'button text-button', 'data-view="relations"')}</div>`;
}

function followUpPanel() {
  const rounds: Row[] = state.followUps || [];
  const busy = Boolean(state.busy);
  return `<div class="context-box follow-up" data-testid="follow-up">
    <h3>还不懂？继续追问</h3>
    <p>围绕这份资料继续问${state.data?.has_api_key ? '' : '（需先在「模型与设置」配置 AI 服务）'}；上一轮问答会一起交给模型，回答仍必须带原文依据。</p>
    <form id="follow-up-form">
      <label class="sr-only" for="follow-up-question">追问内容</label>
      <textarea id="follow-up-question" name="question" maxlength="2000" placeholder="例如：上面那个例子，能用生活里的场景再讲一遍吗？" ${busy ? 'disabled' : ''}>${e(state.followUpDraft || '')}</textarea>
      <div class="follow-up-actions"><small>${rounds.length ? `已追问 ${rounds.length} 次 · 仅本次打开有效` : 'Ctrl + Enter 发送'}</small><button class="button primary" type="submit" ${busy ? 'disabled' : ''}>${busy ? '追问中…' : '追问'}</button></div>
    </form>
    ${rounds.length ? `<div class="follow-up-thread">${rounds.slice().reverse().map((round: Row) => `<div class="follow-up-item">
      <p class="follow-up-question">${e(round.question)}</p>
      <div class="follow-up-answer">${markdown(round.answer)}</div>
      <div class="follow-up-sources">${(round.citations || []).map((s: Row) => s.kind === 'web' ? `<button class="follow-up-source web" data-action="web-source" data-url="${e(s.url)}">联网 ↗</button>` : `<button class="follow-up-source" data-action="citation" data-id="${e(s.id)}" data-doc="${e(s.document_id || state.selected)}">原文${typeof s.start === 'number' ? ' · ' + timestamp(s.start) : ''} ↗</button>`).join('')}</div>
      ${round.notice ? `<p class="follow-up-notice">${e(round.notice)}</p>` : ''}
    </div>`).join('')}</div>` : ''}
  </div>`;
}

function detail() {
  const { document: doc, segments, relations } = state.detail;
  const active = relations.filter((r: Row) => r.status !== 'rejected');
  return `<div class="breadcrumb">${button('back-library', '← 我的知识库', 'button text-button')}<span>/</span><span>${e(doc.title)}</span></div>
    <div class="page-heading"><div><div class="eyebrow">YOUR KNOWLEDGE, WITH SOURCES</div><h1>${e(doc.title)}</h1><p>${date(doc.updated_at)} 更新 · ${segments.length} 个来源片段 · 选中文字可收藏</p></div><div class="toolbar">${button('toggle-note-bookmark', state.detail.notebook?.bookmarked ? '★ 已加书签' : '☆ 笔记书签')}${button('edit', '编辑')}${button('versions', '版本历史')}${button('export', '导出')}${button('delete-document', '删除', 'button danger-quiet')}</div></div>
    <div class="reading-layout"><section class="paper"><div class="paper-tabs">${button('tab-tutorial', '资料正文', `tab ${!state.sourceTab ? 'active' : ''}`)}${button('tab-source', '来源片段', `tab ${state.sourceTab ? 'active' : ''}`)}<span></span>${button('bookmark', icon('star') + ' 收藏选中内容', 'button subtle')}</div>
      ${state.sourceTab ? `<div class="source-list">${segments.map((s: Row, i: number) => `<div class="source-block" id="source-${s.id}"><div><span class="pill">来源 ${i + 1}${s.start != null ? ` · ${Math.floor(s.start / 60)}:${String(Math.floor(s.start % 60)).padStart(2, '0')}` : ''}</span>${s.url ? button('source-video', '跳转视频 ↗', 'button text-button', `data-url="${e(s.url)}" data-time="${s.start || 0}"`) : ''}</div><p>${e(s.text)}</p>${button('bookmark-segment', '收藏此段', 'button text-button', `data-id="${s.id}"`)}</div>`).join('')}</div>` : `<article id="reading-content" class="prose">${markdown(doc.content)}</article>`}</section>
      <aside class="context-panel">${followUpPanel()}${notebookAside(state.detail)}<div class="context-box"><span class="mini-icon">${icon('link')}</span><h3>与这份资料相关</h3><p>按「共同实体」查找关联，泛词共现不再算关联。</p><div class="stack-actions">${button('related-local', '查找实体关联', 'button')}${button('related-ai', 'AI 判断关联类型', 'button primary')}</div>${active.map((r: Row) => `<div class="related-mini"><span class="pill">${relationNames[r.kind]}</span><button class="inline-title" data-action="document" data-id="${r.a === doc.id ? r.b : r.a}">${e(r.a === doc.id ? r.b_title : r.a_title)} ↗</button><p>${e(r.reason)}</p>${(r.entities || []).length ? `<div class="relation-entities">${r.entities.slice(0, 4).map((x: Row) => `<span class="pill">${e(x.name)}</span>`).join('')}</div>` : ''}${relationSources(r)}${r.status === 'suggested' ? `${button('confirm-relation', '确认关联', 'button tiny', `data-id="${r.id}"`)} ${button('reject-relation', '忽略', 'button text-button tiny', `data-id="${r.id}"`)}` : '<span class="confirmed">✓ 已确认</span>'}</div>`).join('') || '<div class="mini-empty">发现关联后，会在这里展示具体原因。</div>'}</div>
      <div class="context-box mint"><h3>把理解再向前一步</h3><p>围绕这份资料提问，或用十道题检验掌握情况。</p>${button('ask-current', icon('chat') + ' 问问这份资料', 'button full')}${button('review-current', icon('quiz') + ' 开始十题练习', 'button full')}${button('generate-tutorial', 'AI 整理为中文教程', 'button text-button full')}</div></aside></div>${screenshotGallery(state.detail.assets || [])}${tutorialAttempts(state.detail.tutorial_attempts || [])}`;
}

function cards() {
  return `<div class="page-heading"><div class="eyebrow">KEEP WHAT MATTERS</div><h1>我的收藏</h1><p>留下值得反复理解的一句话、一段解释。来源已更新的收藏会保留快照，重新确认出处后才能用于复习。</p></div>${state.data.cards.length ? `<div class="cards-grid">${state.data.cards.map((c: Row) => `<div class="note-card" data-card-id="${e(c.id)}"><span class="mini-icon">${icon('star')}</span><p class="card-quote">${e(c.text)}</p><div class="note-source">来自 ${e(c.title)}<span class="pill ${c.stale || c.unmapped ? 'amber' : 'green'}">${c.stale ? '来源已更新 · 待重选' : c.unmapped ? '尚未确认原文出处' : `${(c.source_ids || []).length} 个有效原文出处`}</span>${(c.source_snapshots || []).length ? `<details class="source-snapshots"><summary>${c.stale ? '查看保存时的原文快照' : '查看原文出处'}</summary>${c.source_snapshots.map((s: Row) => `<p>${e(s.text)}</p>`).join('')}</details>` : ''}</div><div class="toolbar">${button('document', '回到资料 ↗', 'button text-button', `data-id="${e(c.document_id)}"`)}${button('map-card-sources', '重新选择出处', 'button text-button', `data-id="${e(c.id)}"`)}${button('delete-card', '移除', 'button text-button muted', `data-id="${e(c.id)}"`)}</div></div>`).join('')}</div>` : empty('收藏属于你的理解', '打开一份资料，选中内容后点击“收藏选中内容”，或在来源页收藏整段。', 'nav', '去知识库')}`;
}

function relationSources(relation: Row) {
  return (relation.evidence || []).map((s: Row) => button('citation', '对应段落 · ' + e(s.title), 'button text-button tiny', `data-id="${s.id}" data-doc="${s.document_id}"`)).join('');
}

function relationView() {
  const rows = state.data.relations.filter((r: Row) => r.status !== 'rejected');
  const index = state.data.entity_index || {};
  const indexed = Object.keys(index).length;
  const total = state.data.documents.length;
  return `<div class="page-heading"><div class="eyebrow">CONNECT THE DOTS</div><h1>知识关联</h1><p>关联由「共同实体」产生：两份资料提到同一个人物、产品、技术或概念才会建立关系；泛词共现不再算关联。自动发现的关系需要你确认。</p></div>
    <div class="info-banner">${icon('link')}已建立实体索引 ${indexed} / ${total} 份资料。${indexed < total ? '新导入的资料需要先抽取实体。' : '问答时会带上已确认关联资料的原文。'}<span class="spacer"></span>${button('build-entity-index', indexed ? '补充抽取实体' : '建立实体索引', 'button primary')}</div>
    ${rows.length ? `<div class="relation-list">${rows.map((r: Row) => `<div class="relation-card"><div class="relation-nodes">${button('document', icon('book') + e(r.a_title), 'relation-node', `data-id="${r.a}"`)}<div class="relation-thread"><span>${relationNames[r.kind]}</span><i></i></div>${button('document', icon('book') + e(r.b_title), 'relation-node', `data-id="${r.b}"`)}</div><p>${e(r.reason)}</p>${(r.entities || []).length ? `<div class="relation-entities">${r.entities.map((x: Row) => `<span class="pill">${e(entityKindNames[x.kind] || '概念')} · ${e(x.name)}</span>`).join('')}</div>` : ''}${relationSources(r)}<div class="toolbar"><span class="${r.status === 'confirmed' ? 'confirmed' : 'muted'}">${r.status === 'confirmed' ? '✓ 已确认' : '待确认的关联建议'}</span><span class="spacer"></span>${r.status === 'suggested' ? button('confirm-relation', '确认关联', 'button primary tiny', `data-id="${r.id}"`) : ''}${button('reject-relation', '移除关联', 'button subtle tiny', `data-id="${r.id}"`)}</div></div>`).join('')}</div>` : empty('让教程之间建立联系', '先点「建立实体索引」，再打开一份资料点「查找实体关联」。', 'nav', '前往知识库')}`;
}

function memoryView() {
  return `<div class="page-heading horizontal"><div><div class="eyebrow">A LITTLE MORE UNDERSTANDING</div><h1>长期记忆</h1><p>个人偏好、目标和自述进度在生成前直接读取，不参与知识关联。你可以随时更正或删除。</p></div>${button('new-memory', icon('plus') + ' 添加记忆', 'button primary')}</div>
    <div class="info-banner">${icon('brain')}同名设置只读取当前版本，不进入 mem0 向量索引。学习进度由你确认，不会因为读过就标为已掌握。</div>
    ${state.data.memories.length ? `<div class="cards-grid">${state.data.memories.map((m: Row) => `<div class="note-card"><span class="pill">${({ preference: '讲解偏好', goal: '学习目标', progress: '学习进度' } as Row)[m.kind]}</span><h3>${e(m.title)}</h3><p>${e(m.text)}</p><div class="toolbar">${button('edit-memory', '更正', 'button text-button', `data-id="${m.id}"`)}${button('delete-memory', '删除', 'button text-button muted', `data-id="${m.id}"`)}</div></div>`).join('')}</div>` : empty('下次，仍然记得你', '例如：“讲代码先给例子”“本月目标是掌握 Python 闭包”。', 'new-memory', '写下第一条记忆')}`;
}

function citations(rows: Row[]) {
  return rows.map((s, i) => s.kind === 'web'
    ? `<button class="citation web" data-action="web-source" data-url="${e(s.url)}"><span>${i + 1}</span><div><strong>${e(s.title)}</strong><small>${e(String(s.text || '').slice(0, 90))}</small></div>↗</button>`
    : `<button class="citation" data-action="citation" data-id="${s.id}" data-doc="${s.document_id}"><span>${i + 1}</span><div><strong>${e(s.title)}</strong><small>${e(s.text.slice(0, 90))}</small></div>↗</button>`).join('');
}

function askView() {
  return `<div class="page-heading"><div class="eyebrow">ASK YOUR OWN KNOWLEDGE</div><h1>把问题，交给积累过的知识</h1><p>从你的资料中查找依据，结合长期记忆，用适合你的方式解释。</p></div>
    <form id="ask-form" class="ask-form"><label class="field-label" for="ask-scope">提问范围</label><select id="ask-scope" name="document_id"><option value="">整个知识库</option>${state.data.documents.map((d: Row) => `<option value="${d.id}" ${state.askScope === d.id ? 'selected' : ''}>${e(d.title)}</option>`).join('')}</select><label class="sr-only" for="ask-question">你的问题</label><textarea id="ask-question" name="question" placeholder="例如：闭包和装饰器有什么关系？能结合我收藏的案例解释吗？" required maxlength="8000">${e(state.lastQuestion || '')}</textarea><div class="ask-bottom"><span>回答带有原文出处 · AI 服务需先配置</span><button class="button primary" type="submit">${icon('chat')} 开始提问</button></div></form>
    ${state.answer ? `<section class="answer-card"><div class="section-title"><h2>来自你的知识库</h2><span class="pill">有据可循</span></div><article class="prose">${markdown(state.answer.answer)}</article><div class="citation-list">${citations(state.answer.citations)}</div>${state.answer.learning_memory_count ? `<p class="small-note">本次参考 ${state.answer.learning_memory_count} 条学习经历；事实依据见原文引用。</p>` : ''}${state.answer.notice ? `<p class="small-note">${e(state.answer.notice)}</p>` : ''}</section>` : `<div class="ask-suggestions"><span>理解一个概念</span><span>比较不同讲法</span><span>找到遗漏的前置知识</span></div>`}
    ${state.data.conversations.length ? `<div class="section-title"><h2>最近的提问</h2></div><div class="history-list">${state.data.conversations.slice(0, 5).map((c: Row) => `<button data-action="past-answer" data-id="${c.id}"><span>${icon('chat')}${e(c.question)}</span><small>${date(c.created_at)} ↗</small></button>`).join('')}</div>` : ''}`;
}

function reviewView() {
  if (state.quiz) return quizView();
  const sessions = state.data.sessions;
  return `<section class="review-hero"><div class="eyebrow">RECALL IS WHERE LEARNING HAPPENS</div><h1>把看过的，<br>变成真正会的。</h1><p>每次十道新题，从自己的教程和收藏中出发。<br>试着回忆、解释，再对照来源重新理解。</p><span class="review-art">10<span>QUESTIONS<br>ONE STEP FORWARD</span></span></section>
    <div class="review-start"><div><h2>开始一组十题练习</h2><p>4 道单选 · 3 道多选 · 3 道简答 · 随机顺序</p></div><label class="sr-only" for="review-scope">复习范围</label><select id="review-scope"><option value="">整个知识库</option><option value="__cards__">仅我的收藏</option>${state.data.documents.map((d: Row) => `<option value="${d.id}" ${state.reviewScope === d.id ? 'selected' : ''}>${e(d.title)}</option>`).join('')}</select>${button('generate-quiz', '生成十道题 ' + icon('arrow'), 'button primary')}</div>
    <div class="review-notes"><div>${icon('star')}每组自动存入题库</div><div>${icon('link')}解析可回到原文</div><div>${icon('brain')}薄弱知识点更常出现</div></div>
    <div class="section-title"><h2>我的题库与练习记录 <span>${sessions.length}</span></h2></div>
    ${sessions.length ? `<div class="history-list">${sessions.map((s: Row) => `<button data-action="open-quiz" data-id="${s.id}"><span class="history-icon">${icon('quiz')}</span><div><strong>${e(s.title)}</strong><small>${date(s.created_at)} · 十题综合练习</small></div><span class="spacer"></span><span class="pill ${s.status === 'completed' ? 'green' : 'amber'}">${s.status === 'completed' ? `${s.score} / 100 分` : '未完成 · 继续作答'}</span>${icon('arrow')}</button>`).join('')}</div>` : empty('你的第一组练习，等待开始', '先导入资料并配置 AI 模型。资料和评分要点会随题目一起保存在本地。')}`;
}

function quizView() {
  const quiz = state.quiz, q = quiz.questions[state.question], done = quiz.status === 'completed';
  const answer = quiz.answers[q.id] ?? (q.type === 'short' ? '' : []);
  const answered = quiz.questions.filter((x: Row) => { const a = quiz.answers[x.id]; return typeof a === 'string' ? a.trim() : a?.length; }).length;
  return `<div class="breadcrumb">${button('close-quiz', '← 复习与题库', 'button text-button')}<span>/</span><span>${e(quiz.title)}</span></div>
    <div class="page-heading horizontal"><div><div class="eyebrow">${done ? 'REVIEW & UNDERSTAND' : 'TAKE YOUR TIME, THINK IT THROUGH'}</div><h1>${done ? '每一次回顾，都更进一步' : '十道题，巩固一次理解'}</h1><p>${done ? '查看解析，找到下次学习的起点。简答题分数由 AI 辅助评定。' : `已作答 ${answered} / 10 · 多选题漏选或错选均不得分 · 草稿自动保存`}</p></div>${done ? `<div class="score-badge"><strong>${quiz.score}</strong><span>/ 100 分</span></div>` : '<span id="draft-state" class="pill">草稿已保存</span>'}</div>
    ${quiz.learning_memory_count ? `<p class="small-note">出题时参考了 ${quiz.learning_memory_count} 条相关学习经历，个人偏好已直接读取。</p>` : ''}${quiz.memory_notice ? `<p class="small-note">${e(quiz.memory_notice)}</p>` : ''}
    <div class="quiz-layout"><aside class="quiz-nav"><h3>本组题目</h3><div class="question-numbers">${quiz.questions.map((x: Row, i: number) => `<button data-action="question" data-index="${i}" class="${i === state.question ? 'current' : ''} ${done ? (x.score >= 6 ? 'correct' : 'wrong') : (quiz.answers[x.id]?.length ? 'answered' : '')}" aria-label="第 ${i + 1} 题">${i + 1}</button>`).join('')}</div><p>单选 4 题<br>多选 3 题<br>简答 3 题</p><div class="small-note">${done ? '每道题 10 分。简答按评分要点评定，分数仅作为学习参考。' : '不是为了做完，<br>而是为了真正理解。'}</div></aside>
    <section class="question-card"><div class="question-top"><span class="pill">${typeNames[q.type]}</span><span>第 ${state.question + 1} / 10 题 · 10 分</span>${done ? `<strong class="${q.score >= 6 ? 'confirmed' : 'wrong-text'}">${q.score} 分</strong>` : ''}</div><h2>${e(q.prompt)}</h2>
    ${q.type === 'short' ? `<label class="sr-only" for="short-answer">简答题答案</label><textarea id="short-answer" class="short-answer" placeholder="试着用自己的话解释，可以举例说明……" maxlength="8000" ${done ? 'disabled' : ''}>${e(answer)}</textarea>` : `<div class="options">${q.options.map((o: Row) => `<label class="option ${answer.includes(o.id) ? 'selected' : ''} ${done && q.answer.includes(o.id) ? 'right-option' : ''}"><input type="${q.type === 'single' ? 'radio' : 'checkbox'}" name="choice" value="${o.id}" ${answer.includes(o.id) ? 'checked' : ''} ${done ? 'disabled' : ''}/><span class="option-letter">${o.id}</span><span>${e(o.text)}</span>${done && q.answer.includes(o.id) ? '<span class="option-check">✓</span>' : ''}</label>`).join('')}</div>`}
    ${done ? `<div class="explanation"><h3>${q.type === 'short' ? '参考答案与评分反馈' : `正确答案：${q.answer.join('、')}`}</h3><p>${e(q.explanation)}</p>${q.type === 'short' ? `<div class="rubric">评分要点：${q.rubric.map(e).join('；')}</div>` : ''}<div class="feedback">${e(q.feedback)}</div></div>` : ''}
    <details class="question-sources"><summary>查看这道题的资料出处</summary>${quiz.sources.filter((s: Row) => q.source_ids.includes(s.id)).map((s: Row) => `<div class="source-block"><strong>${e(s.title)}</strong><p>${e(s.text)}</p>${s.url ? button('source-video', '跳转视频 ↗', 'button text-button', `data-url="${e(s.url)}" data-time="${s.start || 0}"`) : ''}</div>`).join('')}</details>
    <div class="quiz-footer">${button('previous', '← 上一题', 'button', state.question === 0 ? 'disabled' : '')}<span class="spacer"></span>${state.question < 9 ? button('next', '下一题 →', 'button primary') : !done ? button('submit-quiz', '提交并查看解析', 'button primary') : button('close-quiz', '完成回顾', 'button primary')}</div></section></div>`;
}

function settingsView() {
  const s = state.data.settings;
  return `<div class="page-heading"><div class="eyebrow">YOUR MODELS, YOUR KNOWLEDGE</div><h1>模型与设置</h1><p>使用你自己的在线 AI 服务。知识保存在本地，需要处理的片段会发送给所配置的服务。</p></div>
    <div class="settings-layout"><form id="settings-form" class="settings-card"><h2>对话与生成模型</h2><label for="base-url">兼容 API 地址（包含 /v1 等前缀）</label><input id="base-url" name="base_url" type="url" placeholder="https://你的服务地址/v1" value="${e(s.base_url || '')}" required/><label for="model">对话模型名称</label><input id="model" name="model" placeholder="填写服务商提供的准确模型 ID" value="${e(s.model || '')}" required/><label for="api-key">API Key ${state.data.has_api_key ? '<span class="confirmed">· 已加密保存</span>' : ''}</label><input id="api-key" name="api_key" type="password" autocomplete="new-password" placeholder="${state.data.has_api_key ? '留空保留现有密钥' : '输入你的 API Key'}"/>
    <div class="form-divider"></div><h2>语义检索 <span class="pill">可选</span></h2><p>未配置时仍可使用本地关键词搜索。mem0 从原文提取知识并存入本地。首次配置或导入新资料后，请同步记忆；未配置时可使用关键词搜索。</p><label for="embedding-model">Embedding 模型名称</label><input id="embedding-model" name="embedding_model" value="${e(s.embedding_model || '')}" placeholder="填写支持中文的 Embedding 模型 ID"/><label for="embedding-url">Embedding API 地址</label><input id="embedding-url" name="embedding_url" type="url" value="${e(s.embedding_url || '')}" placeholder="留空使用上面的 API 地址"/><p class="small-note">Embedding 与对话共用此 API Key，请填写同一服务商或兼容网关的地址。</p><div class="form-divider"></div><h2>联网搜索 <span class="pill">可选</span></h2><p>本地资料不足时自动联网补充依据，并在回答里把网络来源标注为「联网」。搜索结果只作参考，不会覆盖你的本地资料。</p><label for="web-search-provider">搜索服务</label><select id="web-search-provider" name="web_search_provider"><option value="">不启用</option>${Object.entries(s.web_search_providers || {}).map(([value, label]) => `<option value="${value}" ${s.web_search_provider === value ? 'selected' : ''}>${e(label)}</option>`).join('')}</select><label for="search-api-key">搜索 API Key ${state.data.has_search_key ? '<span class="confirmed">· 已加密保存</span>' : ''}</label><input id="search-api-key" name="search_api_key" type="password" autocomplete="new-password" placeholder="${state.data.has_search_key ? '留空保留现有搜索密钥' : '输入搜索服务的 API Key'}"/><p class="small-note">搜索密钥与对话密钥分开加密保存；未配置时只是不联网，本地问答不受影响。</p><div class="toolbar"><button type="submit" class="button primary">保存设置</button>${button('test-model', '测试已保存的连接')}${state.data.has_search_key ? button('test-search', '测试联网搜索') : ''}${state.data.has_search_key ? button('remove-search-key', '移除搜索密钥', 'button danger-quiet') : ''}${button('build-index', '同步 mem0 记忆')}</div></form>
    <aside><div class="context-box"><h3>记忆引擎 · mem0 ${e(state.data.mem0.version)}</h3><p>${state.data.mem0.knowledge_count} 条知识事实<br>${state.data.mem0.relation_count} 条已确认关联 · ${state.data.mem0.review_count} 条复习观察 · ${state.data.mem0.conversation_count} 条历史提问<br>${state.data.mem0.pending} 项资料或学习记录待同步</p><p>问答、出题前自动同步学习记录；新资料请点击同步。需要对话模型与 Embedding 模型，使用当前 API Key。</p><p>${state.data.mem0.preference_count} 条个人设置在生成前直接读取，不使用向量索引。</p></div><div class="context-box"><h3>数据留在你的电脑</h3><p>教程、收藏、题库和记忆保存在：</p><code class="data-path">${e(state.data.data_directory)}</code><p>密钥使用系统加密保存。关闭应用后数据仍保留。</p>${state.data.has_api_key ? button('remove-key', '移除已保存的 API Key', 'button danger-quiet') : ''}</div><div class="context-box"><h3>关于当前版本</h3><p>支持文本、Markdown 笔记库、SRT / VTT / B 站字幕 JSON，以及本地音视频。公开视频优先使用可用字幕，无字幕时尝试本地转写。</p><p>支持本地音视频转写、公开直达视频链接和受管理截图；任务进度在知识库显示。简答评分由 AI 辅助，适合学习反馈。</p></div></aside></div>`;
}

function searchView() {
  return `<div class="page-heading"><div class="eyebrow">FIND WHAT YOU HAVE LEARNED</div><h1>搜索：${e(state.search)}</h1><p>${e(state.results?.notice || '')}</p></div>${state.results?.results.length ? `<div class="search-results">${state.results.results.map((s: Row) => `<button data-action="citation" data-id="${s.id}" data-doc="${s.document_id}" class="search-result"><div><span class="pill">${e(s.retrieval)}匹配</span><h3>${e(s.title)}</h3></div><p>${e(s.text.slice(0, 400))}</p><small>打开来源 ↗</small></button>`).join('')}</div>` : empty('还没有找到相关资料', '试试具体的概念名称，或先导入包含该知识点的资料。')}`;
}

function modal() {
  if (!state.modal) return '';
  let content = featureModal(state);
  if (state.modal === 'new') content = `<div class="modal-heading"><div><span class="eyebrow">ADD TO YOUR KNOWLEDGE</span><h2>导入学习资料</h2></div>${button('close-modal', icon('close'), 'icon-button', 'aria-label="关闭"')}</div><div class="import-methods">${button('import-file', icon('book') + ' 选择文本 / 字幕文件', 'button')}${button('video-modal', icon('play') + ' 从视频链接导入', 'button')}${button('local-media-modal', '本地音视频', 'button')}${button('import-vault', 'Markdown 文件夹', 'button')}</div><form id="import-form"><label for="import-title">资料标题</label><input id="import-title" name="title" placeholder="例如：Python 闭包与装饰器" required maxlength="200"/><label for="import-content">粘贴文本或 Markdown</label><textarea id="import-content" name="content" placeholder="把想保存的知识放进来……" required></textarea><div class="modal-footer"><small>本地保存 · 可搜索 · 可关联 · 可复习</small><button type="submit" class="button primary">保存到知识库</button></div></form>`;
  if (state.modal === 'video' || state.modal === 'local-media') {
    const local = state.modal === 'local-media';
    content = `<div class="modal-heading"><h2>${local ? '导入本地音视频' : '导入公开直达视频'}</h2>${button('close-modal', icon('close'), 'icon-button', 'aria-label="关闭"')}</div><p class="muted">${local ? '通过系统文件选择器读取本地视频或音频；可用字幕优先，没有字幕时使用本地转写。' : '支持 B 站 BV、YouTube、抖音 /video/ 和快手 /short-video/ 的公开直达链接。'}</p><form id="${local ? 'local-media-form' : 'video-form'}">${local ? '' : '<label for="video-url">公开视频链接或 BV 号</label><input id="video-url" name="url" type="text" placeholder="BV… 或 https://www.bilibili.com/video/BV…" required maxlength="8000"/>'}<label for="media-title">资料标题（可选）</label><input id="media-title" name="title" maxlength="200" placeholder="自动使用视频标题"/><label for="media-language">原声转写语言</label><select id="media-language" name="language"><option value="auto">自动检测</option><option value="zh">中文</option><option value="en">英语</option><option value="ja">日语</option></select><label for="asr-model">本地转写质量</label><select id="asr-model" name="asr_model"><option value="tiny">快速 · tiny</option><option value="base" selected>均衡 · base</option><option value="small">高质量 · small</option></select><label class="checkbox-label"><input type="checkbox" name="screenshots" checked/> 提取视频时间点截图</label><label class="checkbox-label"><input type="checkbox" name="generate_tutorial" checked/> 导入后自动生成中文教程</label><p class="small-note">转写保留原声语言，教程用中文讲解；自动整理使用已配置的 AI 模型，勾选截图时会结合画面。取消勾选只保存原文。导入在后台运行，可查看进度、取消和失败重试。受限、需登录或不可访问的视频会显示真实错误。</p><div class="modal-footer"><small>${local ? '本地模型首次转写可能需要下载' : '不接受短链、播放列表或登录凭据'}</small><button class="button primary" type="submit">${local ? '选择文件并开始导入' : '开始后台导入'}</button></div></form>`;
  }
  if (state.modal === 'memory') {
    const m = state.editMemory || {};
    content = `<div class="modal-heading"><h2>${m.id ? '更正记忆' : '添加长期记忆'}</h2>${button('close-modal', icon('close'), 'icon-button', 'aria-label="关闭"')}</div><form id="memory-form"><label for="memory-kind">记忆类型</label><select id="memory-kind" name="kind">${[['preference','讲解偏好'],['goal','学习目标'],['progress','学习进度']].map(([v,l]) => `<option value="${v}" ${m.kind === v ? 'selected' : ''}>${l}</option>`).join('')}</select><label for="memory-title">标题（同名会替代旧版本）</label><input id="memory-title" name="title" value="${e(m.title || '')}" required ${m.id ? 'readonly' : ''}/><label for="memory-text">希望助手记住什么</label><textarea id="memory-text" name="text" required maxlength="8000" placeholder="例如：讲解代码时先给一个最小可运行的例子。">${e(m.text || '')}</textarea><div class="modal-footer"><small>用于后续问答，随时可以删除</small><button class="button primary" type="submit">保存记忆</button></div></form>`;
  }
  if (state.modal === 'edit') {
    const d = state.detail.document;
    content = `<div class="modal-heading"><h2>编辑资料</h2>${button('close-modal', icon('close'), 'icon-button', 'aria-label="关闭"')}</div><form id="edit-form"><label for="edit-title">标题</label><input id="edit-title" name="title" value="${e(d.title)}" required/><label for="edit-content">正文</label><textarea id="edit-content" name="content" class="large-textarea" required>${e(d.content)}</textarea><div class="modal-footer"><small>${d.kind === 'text' ? '修改原文会清理相关旧练习和问答；收藏保留，可先导出版本。' : '原始资料保留在“来源片段”中'}</small><button class="button primary" type="submit">保存修改</button></div></form>`;
  }
  if (state.modal === 'citation') {
    const s = state.citation;
    content = `<div class="modal-heading"><h2>资料出处</h2>${button('close-modal', icon('close'), 'icon-button', 'aria-label="关闭"')}</div><span class="pill">${e(s.title)}</span><div class="citation-full">${e(s.text)}</div><div class="modal-footer">${button('document', '打开完整资料', 'button', `data-id="${s.document_id}"`)}${s.url ? button('source-video', '跳转视频 ↗', 'button primary', `data-url="${e(s.url)}" data-time="${s.start || 0}"`) : ''}</div>`;
  }
  return `<div class="modal-backdrop"><section class="modal" role="dialog" aria-modal="true">${content}</section></div>`;
}

function render() {
  if (!state.data) { root.innerHTML = '<div class="loading-screen">知序<span>正在打开你的学习空间……</span></div>'; return; }
  const views: Record<string, () => string> = { library, cards, relations: relationView, ask: askView, review: reviewView, memory: memoryView, settings: settingsView, search: searchView, graph: () => graphView(state.graph) };
  root.innerHTML = `${nav()}<main><header class="topbar"><span class="workspace-name">个人空间 <small>/ ${({ library: '知识库', cards: '我的收藏', relations: '知识关联', ask: '知识问答', review: '复习与题库', memory: '长期记忆', settings: '设置', search: '搜索', graph: '引用图谱' } as Row)[state.view]}</small></span><form id="search-form" class="global-search">${icon('search')}<input name="query" aria-label="搜索知识库" placeholder="搜索你的知识……" value="${e(state.search)}"/><button type="submit" aria-label="搜索">↵</button></form><span class="avatar">知</span></header><div class="content">${(views[state.view] || library)()}</div></main>${modal()}${state.busy ? `<div class="busy-mask"><span class="spinner"></span><strong>${e(state.busy)}</strong><small>处理中，请稍候。已保存内容会保留在本地。</small></div>` : ''}`;
}

async function openDoc(id: string) {
  state.detail = await api.call('document', { id }); state.view = 'library'; state.selected = id; state.sourceTab = false; state.modal = '';
  state.followUps = []; state.followUpDraft = '';
}

function scrollToHeading(value: string, isId = false) {
  state.sourceTab = false; render();
  requestAnimationFrame(() => {
    const heading = document.getElementById(isId ? value : headingId(value));
    if (heading) { heading.scrollIntoView({behavior:'smooth',block:'start'}); heading.classList.add('heading-highlight'); setTimeout(() => heading.classList.remove('heading-highlight'), 1800); }
    else toast('已打开笔记，但未找到链接指定的标题');
  });
}

async function followNoteLink(documentId: string, target: string) {
  const link = await api.call('resolve_note_link', { id: documentId, target });
  if (link.unresolved || !link.document_id) { state.linkResolution = link; state.modal = 'link-resolution'; return; }
  await openDoc(link.document_id);
  if (link.heading) state.pendingHeading = link.heading;
}

async function sourcePicker(selection: Row, sourceIds: string[] = [], detail?: Row) {
  const data = detail || await api.call('document', {id:selection.document_id});
  state.cardSelection = selection;
  state.sourceMapSegments = data.segments || [];
  const current = new Set(state.sourceMapSegments.map((s:Row) => s.id));
  state.sourceMapIds = sourceIds.filter(id => current.has(id));
  state.modal = 'source-map';
}

async function saveDraft() {
  clearTimeout(draftTimer);
  const quiz = state.quiz;
  if (!quiz || quiz.status === 'completed') return;
  await api.call('save_draft', { id: quiz.id, answers: structuredClone(quiz.answers) });
  const status = document.querySelector('#draft-state'); if (status) status.textContent = '草稿已保存';
}

function invalidateEditedSource(documentId: string) {
  if (state.answer?.citations?.some((s: Row) => s.document_id === documentId)) state.answer = null;
  state.results = null;
}

root.addEventListener('input', event => {
  const target = event.target as HTMLInputElement;
  if (target.id === 'follow-up-question') { state.followUpDraft = (event.target as HTMLTextAreaElement).value; return; }
  if (target.id !== 'short-answer') return;
  state.quiz.answers[state.quiz.questions[state.question].id] = target.value;
  const status = document.querySelector('#draft-state'); if (status) status.textContent = '正在保存…';
  clearTimeout(draftTimer); draftTimer = setTimeout(() => saveDraft().catch(err => toast(err.message, true)), 500);
});
root.addEventListener('change', event => {
  const target = event.target as HTMLInputElement;
  if (target.id === 'bookmark-filter' || target.id === 'tag-filter') { state.bookmarkFilter = target.id === 'bookmark-filter' ? target.checked : state.bookmarkFilter; state.tagFilter = target.id === 'tag-filter' ? target.value : state.tagFilter; render(); return; }
  if (target.id === 'graph-focus') {
    const edges:Row[] = state.graph?.edges || [], id = target.value;
    const visible = new Set([id,...edges.filter(edge => edge.source === id || edge.target === id).flatMap(edge => [edge.source,edge.target])]);
    root.querySelectorAll<SVGElement>('.graph-node').forEach(node => node.style.opacity = !id || visible.has(node.dataset.id!) ? '1' : '.15');
    root.querySelectorAll<SVGElement>('.graph-edge').forEach(edge => edge.style.opacity = !id || edge.dataset.source === id || edge.dataset.target === id ? '1' : '.08');
    return;
  }
  if (target.name !== 'choice') return;
  const q = state.quiz.questions[state.question];
  state.quiz.answers[q.id] = Array.from(root.querySelectorAll<HTMLInputElement>('input[name="choice"]:checked')).map(x => x.value);
  render(); saveDraft().catch(err => toast(err.message, true));
});

root.addEventListener('click', async event => {
  const target = (event.target as Element).closest<HTMLElement>('[data-action]');
  if (!target || state.busy) return;
  const a = target.dataset.action, id = target.dataset.id!;
  if (a === 'nav') { await saveDraft().catch(err => toast(err.message, true)); state.view = target.dataset.view || 'library'; state.detail = null; state.modal = ''; if (state.view === 'graph') { await work('读取引用图谱…', async () => { state.graph = await api.call('note_graph', {limit:200}); }); } else render(); return; }
  if (a === 'new') { state.modal = 'new'; render(); return; }
  if (a === 'create-note' || a === 'create-linked-note') { state.newNoteTitle = a === 'create-linked-note' ? String(state.linkResolution?.target || '').split('#')[0].replace(/\.md$/i,'') : ''; state.modal = 'create-note'; render(); return; }
  if (a === 'video-modal') { state.modal = 'video'; render(); return; }
  if (a === 'local-media-modal') { state.modal = 'local-media'; render(); return; }
  if (a === 'filter-tag') { state.tagFilter = target.dataset.tag; state.detail = null; state.view = 'library'; render(); return; }
  if (a === 'clear-filters') { state.tagFilter = ''; state.bookmarkFilter = false; render(); return; }
  if (a === 'heading') { scrollToHeading(target.dataset.heading!, true); return; }
  if (a === 'generate-tutorial') { state.modal = 'tutorial-options'; render(); return; }
  if (a === 'close-modal') { state.modal = ''; render(); return; }
  if (a === 'new-memory' || a === 'edit-memory') { state.editMemory = a === 'edit-memory' ? state.data.memories.find((m: Row) => m.id === id) : null; state.modal = 'memory'; render(); return; }
  if (a === 'edit') { state.modal = 'edit'; render(); return; }
  if (a === 'tab-tutorial' || a === 'tab-source') { state.sourceTab = a === 'tab-source'; render(); return; }
  if (a === 'back-library') { state.detail = null; render(); return; }
  if (a === 'ask-current') { state.askScope = state.selected; state.view = 'ask'; render(); return; }
  if (a === 'review-current') { state.reviewScope = state.selected; state.quiz = null; state.view = 'review'; render(); return; }
  if (a === 'close-quiz') { await work('保存练习…', async () => { await saveDraft(); state.quiz = null; await refresh(); }); return; }
  if (a === 'question' || a === 'previous' || a === 'next') {
    const next = a === 'question' ? Number(target.dataset.index) : state.question + (a === 'next' ? 1 : -1);
    if (next === state.question) return;
    const saving = saveDraft();
    state.question = next; render();
    await saving.catch(err => toast(err.message, true)); return;
  }
  if (a === 'past-answer') { const c = state.data.conversations.find((c: Row) => c.id === id); state.answer = c; state.lastQuestion = c.question; render(); return; }
  if (a === 'bookmark') {
    const selection = window.getSelection(); const text = selection?.toString().trim();
    const article = document.querySelector('#reading-content');
    if (!text || !selection?.anchorNode || !article?.contains(selection.anchorNode) || !selection.focusNode || !article.contains(selection.focusNode)) { toast('请先在教程正文中选中要收藏的内容'); return; }
    const range = selection.getRangeAt(0);
    const selectedSourceIds = Array.from(article.querySelectorAll<HTMLElement>('[data-source-id]')).filter(node => range.intersectsNode(node)).map(node => node.dataset.sourceId!);
    if (state.detail.document.kind !== 'text') { await sourcePicker({document_id:state.selected,text}, selectedSourceIds,state.detail); render(); return; }
    await work('保存收藏…', async () => {
      try {
        const card = await api.call('add_card', { document_id: state.selected, text }); await refresh();
        if (card.unmapped || card.stale) { await sourcePicker({id:card.id,document_id:state.selected,text},selectedSourceIds,state.detail); toast('收藏已保存，请确认对应的原文出处'); }
        else toast('已收藏，保留原始资料出处');
      }
      catch (err) {
        if (/来源|原文|source/i.test((err as Error).message)) await sourcePicker({document_id:state.selected,text},selectedSourceIds,state.detail);
        else throw err;
      }
    }); return;
  }
  if (a === 'generate-quiz') {
    const scope = (document.querySelector('#review-scope') as HTMLSelectElement).value;
    await work('正在依据资料生成十道题，通常需要 30–90 秒…', async () => { state.quiz = await api.call('generate_quiz', { document_id: scope || null }); state.question = 0; await refresh(); }); return;
  }
  if (a === 'submit-quiz') { await work('保存作答并评阅简答题…', async () => { await saveDraft(); state.quiz = await api.call('submit_quiz', { id: state.quiz.id, answers: state.quiz.answers }); await refresh(); toast('已交卷，解析与成绩已保存'); }); return; }
  if (a === 'delete-document') {
    state.modal = 'confirm-delete';
    // Native confirm is supported by Electron and keeps deletion explicit.
    if (!window.confirm('删除这份资料？关联收藏和含有该来源的练习也会删除，此操作无法撤销。')) { state.modal = ''; return; }
  }
  if (a === 'restore-version' && !window.confirm('恢复这个版本？当前版本仍保留在历史中，相关旧来源索引、问答与练习将重新校验。')) return;
  await work(({ 'import-file': '读取资料文件…', 'generate-tutorial': '正在根据来源整理教程…', 'related-ai': '正在分析教程之间的关系…', 'build-entity-index': '正在抽取实体并建立索引…', 'build-index': 'mem0 正在抽取并保存知识，首次同步可能需要几分钟…' } as Row)[a!] || '处理中…', async () => {
    if (a === 'document') await openDoc(id);
    if (a === 'external-link') await api.openLink(target.dataset.url!);
    if (a === 'note-link') await followNoteLink(target.dataset.doc || state.selected,target.dataset.target!);
    if (a === 'choose-note-link') { const heading = state.linkResolution?.heading; await openDoc(id); if (heading) state.pendingHeading = heading; }
    if (a === 'toggle-note-bookmark') { await api.call('toggle_note_bookmark', {id:state.selected}); await refresh(); await openDoc(state.selected); }
    if (a === 'versions') { state.versions = await api.call('note_versions', {id:state.selected}); state.modal = 'versions'; }
    if (a === 'restore-version') { const documentId = state.selected; await api.call('restore_note_version', {id:documentId,version_id:id}); invalidateEditedSource(documentId); await refresh(); await openDoc(documentId); toast('已恢复版本，旧来源索引已清理'); }
    if (a === 'map-card-sources') { const card = state.data.cards.find((c:Row) => c.id === id); await sourcePicker({id:card.id,document_id:card.document_id,text:card.text},card.source_ids || []); }
    if (a === 'import-vault') { const result = await api.importVault(); if (result) { state.modal = ''; await refresh(); state.detail = null; state.view = 'library'; toast(`已导入 ${result.imported || result.documents?.length || 0} 份笔记${result.skipped?.length ? '，跳过 ' + result.skipped.length + ' 项' : ''}`); } }
    if (a === 'export-vault') { const result = await api.exportVault(); if (result) toast(`已导出 ${result.exported || result.documents?.length || 0} 份笔记，保留来源映射`); }
    if (a === 'retry-media-job' || a === 'cancel-media-job') { await api.call(a === 'retry-media-job' ? 'retry_media_job' : 'cancel_media_job', {id}); await refresh(); toast(a === 'retry-media-job' ? '任务已重新排队' : '已请求取消任务'); }
    if (a === 'citation') { const data = await api.call('document', { id: target.dataset.doc }); state.citation = data.segments.find((s: Row) => s.id === id); if (!state.citation) throw new Error('来源片段已更新或删除'); state.modal = 'citation'; }
    if (a === 'source-video') { const url = new URL(target.dataset.url!); url.searchParams.set('t', String(Math.floor(Number(target.dataset.time)))); await api.openLink(url.toString().replace(/^http:/, 'https:')); }
    if (a === 'web-source') { const url = new URL(target.dataset.url!); if (!['http:', 'https:'].includes(url.protocol)) throw new Error('联网来源地址无效'); await api.openLink(url.toString()); }
    if (a === 'import-file') { const file = await api.importFile(); if (file) { const doc = await api.call('import_text', file); await refresh(); await openDoc(doc.id); toast('资料已导入'); } }
    if (a === 'export') { if (await api.exportDocument(state.selected)) toast('Markdown 已导出'); }
    if (a === 'bookmark-segment') { const s = state.detail.segments.find((s: Row) => s.id === id); await api.call('add_card', { document_id: state.selected, text: s.text, segment_id: s.id }); await refresh(); toast('已收藏此段资料'); }
    if (a === 'delete-document') { await api.call('delete_document', { id: state.selected }); state.detail = null; state.selected = null; state.modal = ''; await refresh(); }
    if (a === 'delete-card' || a === 'delete-memory') { await api.call(a.replace('-', '_'), { id }); await refresh(); }
    if (a === 'related-local' || a === 'related-ai') { await api.call('related', { id: state.selected, use_ai: a === 'related-ai' }); await refresh(); await openDoc(state.selected); toast('关联候选已更新，可确认或忽略'); }
    if (a === 'build-entity-index') { const result = await api.call('build_entity_index', { limit: 8 }); await refresh(); toast(`已为 ${result.documents.length} 份资料抽取 ${result.entities} 个实体`); }
    if (a === 'confirm-relation' || a === 'reject-relation') { await api.call('set_relation', { id, status: a === 'confirm-relation' ? 'confirmed' : 'rejected' }); await refresh(); if (state.detail) await openDoc(state.selected); }
    if (a === 'open-quiz') { state.quiz = await api.call('quiz', { id }); state.question = 0; }
    if (a === 'test-model') { const result = await api.call('test_model'); toast(result.message); }
    if (a === 'test-search') { const result = await api.call('test_search', {}); toast(result.message); }
    if (a === 'build-index') { const result = await api.call('sync_mem0'); await refresh(); toast(result.message); }
    if (a === 'remove-key') { await api.saveCredential(''); await refresh(); toast('已移除 API Key'); }
    if (a === 'remove-search-key') { await api.saveSearchCredential(''); await refresh(); toast('已移除搜索 API Key'); }
  });
  if (state.pendingHeading) { const heading = state.pendingHeading; state.pendingHeading = ''; scrollToHeading(heading); }
});

root.addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.target as HTMLFormElement;
  const values = Object.fromEntries(new FormData(form).entries()) as Record<string, string>;
  if (state.busy) return;
  if (form.id === 'settings-form') { await work('保存模型设置…', async () => { const { api_key, search_api_key, ...settings } = values; await api.call('save_settings', settings); if (api_key.trim()) await api.saveCredential(api_key); if (search_api_key && search_api_key.trim()) await api.saveSearchCredential(search_api_key); await refresh(); toast('设置已保存'); }); return; }
  if (form.id === 'import-form') { await work('保存资料…', async () => { const doc = await api.call('import_text', values); await refresh(); await openDoc(doc.id); toast('已保存到本地知识库'); }); return; }
  if (form.id === 'create-note-form') { await work('创建笔记…', async () => { const doc = await api.call('import_text', values); await refresh(); await openDoc(doc.id); toast('笔记已创建'); }); return; }
  if (form.id === 'video-form' || form.id === 'local-media-form') {
    await work('提交媒体导入任务…', async () => {
      const options = {title:values.title || '',language:values.language || 'auto',asr_model:values.asr_model || 'base',screenshots:new FormData(form).has('screenshots'),generate_tutorial:new FormData(form).has('generate_tutorial')};
      const job = form.id === 'local-media-form' ? await api.importMedia(options) : await api.call('start_video_job', {url:values.url,options});
      if (job) { state.modal = ''; state.view = 'library'; state.detail = null; await refresh(); toast(options.generate_tutorial ? '任务已提交，素材保存后将自动生成中文教程' : '任务已提交，本次只导入原文'); }
    }); return;
  }
  if (form.id === 'source-map-form') {
    const sourceIds = new FormData(form).getAll('source_ids').map(String);
    if (!sourceIds.length) { toast('请至少选择一个能够支持收藏内容的原文片段'); return; }
    await work('保存收藏原文出处…', async () => {
      const selection = state.cardSelection;
      await api.call(selection.id ? 'map_card_sources' : 'add_card', selection.id ? {id:selection.id,source_ids:sourceIds} : {document_id:selection.document_id,text:selection.text,source_ids:sourceIds});
      state.modal = ''; state.cardSelection = null; await refresh(); toast('已保存收藏和明确的原文出处');
    }); return;
  }
  if (form.id === 'tutorial-form') {
    const useImages = new FormData(form).has('use_images');
    await work('正在根据来源整理教程…', async () => {
      const id = state.selected;
      try { await api.call('tutorial', {id,style:values.style,use_images:useImages}); }
      catch (error) {
        // Failed attempts are durable too; show their drafts and errors immediately.
        try { await openDoc(id); } catch { /* Keep the original generation error if the document was deleted. */ }
        throw error;
      }
      invalidateEditedSource(id); await refresh(); await openDoc(id); toast('已生成教程，原始来源与历史版本仍保留');
    }); return;
  }
  if (form.id === 'memory-form') { await work('保存长期记忆…', async () => { await api.call('save_memory', values); state.modal = ''; await refresh(); toast('记忆已保存，将用于后续问答'); }); return; }
  if (form.id === 'edit-form') { await work('保存修改…', async () => { await api.call('update_document', { ...values, id: state.selected }); invalidateEditedSource(state.selected); await refresh(); await openDoc(state.selected); }); return; }
  if (form.id === 'search-form') { if (!values.query.trim()) return; state.search = values.query; await work('检索知识库…', async () => { state.results = await api.call('search', { query: values.query }); state.view = 'search'; }); return; }
  if (form.id === 'ask-form') { state.lastQuestion = values.question; state.askScope = values.document_id; await work('正在检索资料并组织回答…', async () => { state.answer = await api.call('ask', { question: values.question, document_id: values.document_id || null }); await refresh(); }); }
  if (form.id === 'follow-up-form') {
    const question = (values.question || '').trim();
    if (!question) { toast('先写下你想追问的问题'); return; }
    const history = (state.followUps || []).slice(-3).map((round: Row) => ({ question: round.question, answer: round.answer }));
    state.followUpDraft = '';
    await work('正在追问…', async () => {
      const data = await api.call('ask', { question, document_id: state.selected, history });
      state.followUps = [...(state.followUps || []), { question, answer: data.answer, citations: data.citations || [], notice: data.notice || '' }];
    });
    return;
  }
});

api.onClosing(() => {
  saveDraft().then(() => api.finishClose(true)).catch(() => api.finishClose(false));
});
root.addEventListener('keydown', event => {
  const target = event.target as Element;
  if ((event.key === 'Enter' || event.key === ' ') && target.matches('.graph-node')) { event.preventDefault(); target.dispatchEvent(new MouseEvent('click', {bubbles:true})); }
  if (target.id === 'follow-up-question' && event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); (target as HTMLTextAreaElement).form?.requestSubmit(); }
});

let polling = false;
setInterval(async () => {
  if (polling || !state.data || state.busy || state.modal || state.quiz || document.hidden) return;
  polling = true;
  try {
    const jobs = await api.call('media_jobs');
    const before = new Map<string,string>((state.jobs || []).map((job:Row) => [job.id,`${job.status}:${job.document_id || ''}`]));
    const changed = JSON.stringify(jobs) !== JSON.stringify(state.jobs);
    state.jobs = Array.isArray(jobs) ? jobs : jobs.jobs || [];
    const updatedDocuments = new Set<string>(state.jobs.filter((job:Row) => job.document_id && ['completed','failed','cancelled'].includes(job.status) && before.get(job.id) !== `${job.status}:${job.document_id}`).map((job:Row) => job.document_id));
    const completed = updatedDocuments.size > 0;
    updatedDocuments.forEach(id => pendingDocumentRefresh.add(id));
    if (completed) await refresh();
    const selected = state.selected;
    if (state.detail && pendingDocumentRefresh.has(selected) && !state.busy && !state.modal && !state.quiz && state.view === 'library') {
      const incoming = await api.call('document', {id:selected});
      if (state.selected === selected && state.detail && !state.busy && !state.modal && !state.quiz && state.view === 'library') {
        state.detail = incoming;
        // Keep the topbar/search DOM and focus; only replace the read-only document.
        const region = root.querySelector('.content');
        if (region) { region.innerHTML = detail(); pendingDocumentRefresh.delete(selected); }
      }
    }
    // Only replace the task region. Search, editor, settings and answer drafts stay intact.
    if (changed && state.view === 'library' && !state.detail && !state.busy && !state.modal && !state.quiz) {
      const region = document.querySelector('#media-jobs-region');
      if (region) region.innerHTML = mediaJobs(state.jobs);
      if (completed) {
        const fragment = document.createElement('div'); fragment.innerHTML = library();
        const incoming = fragment.querySelector('#library-documents'), current = root.querySelector('#library-documents');
        if (incoming && current) current.replaceWith(incoming);
      }
    }
  } catch { /* The foreground action reports errors; polling must leave drafts untouched. */ }
  finally { polling = false; }
}, 2000);
render();
refresh().then(render).catch(err => { root.textContent = '打开知识库失败：' + err.message; });
