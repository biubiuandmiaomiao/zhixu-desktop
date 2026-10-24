import './style.css';

type Row = Record<string, any>;
declare global {
  interface Window { knowledge: {
    call(action: string, args?: Row): Promise<any>;
    saveCredential(value: string): Promise<any>;
    importFile(): Promise<Row | null>;
    exportDocument(id: string): Promise<boolean>;
    openLink(url: string): Promise<void>;
    onClosing(callback: () => void): void;
    finishClose(saved: boolean): Promise<void>;
  } }
}

const api = window.knowledge;
const root = document.querySelector<HTMLDivElement>('#app')!;
const state: Row = { view: 'library', data: null, selected: null, detail: null, busy: '', modal: '',
  quiz: null, question: 0, search: '', results: null, answer: null, askScope: '', sourceTab: false };
let draftTimer: ReturnType<typeof setTimeout> | undefined;
const escape = (x: unknown) => String(x ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
const e = escape;
const typeNames: Row = { single: '单选题', multiple: '多选题', short: '简答题' };
const relationNames: Row = { shared: '同一知识点', prerequisite: '前置知识 → 进阶', supplement: '补充案例', difference: '内容差异' };
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
  let code = false;
  return text.split('\n').map(line => {
    if (line.startsWith('```')) { code = !code; return ''; }
    if (code) return `<div class="code-line">${e(line) || ' '}</div>`;
    const heading = /^(#{1,4})\s+(.*)/.exec(line);
    if (heading) return `<h${heading[1].length + 1}>${e(heading[2])}</h${heading[1].length + 1}>`;
    if (!line.trim()) return '<div class="paragraph-gap"></div>';
    const rendered = e(line).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>');
    if (/^[-*]\s/.test(line)) return `<p class="bullet">${rendered.slice(2)}</p>`;
    return `<p>${rendered}</p>`;
  }).join('');
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
    ['relations', 'link', '知识关联', d.relations.filter((r: Row) => r.status === 'confirmed').length],
    ['ask', 'chat', '知识问答', ''], ['review', 'quiz', '复习与题库', d.sessions.length], ['memory', 'brain', '长期记忆', d.memories.length]];
  return `<aside class="sidebar"><div class="brand"><span class="brand-mark">${icon('leaf')}</span><div>知序<small>ZHIXU · YOUR LEARNING SPACE</small></div></div>
    ${button('new', icon('plus') + ' 导入学习资料', 'button primary add-button')}
    <div class="nav-label">我的学习空间</div><nav>${items.map(([view, ico, label, count]) => `<button data-action="nav" data-view="${view}" class="nav-item ${state.view === view ? 'active' : ''}">${icon(String(ico))}<span>${label}</span>${count !== '' ? `<small>${count}</small>` : ''}</button>`).join('')}</nav>
    <div class="sidebar-bottom"><div class="local-badge"><i></i> 本地知识库 <span>只属于你</span></div><button data-action="nav" data-view="settings" class="nav-item ${state.view === 'settings' ? 'active' : ''}">${icon('gear')}<span>模型与设置</span></button><div class="version">知序 · Windows 预览版 0.2</div></div></aside>`;
}

function library() {
  if (state.detail) return detail();
  const d = state.data;
  return `<div class="welcome"><div><div class="eyebrow">LEARN · CONNECT · REMEMBER</div><h1>让知识，在这里生长<span>。</span></h1><p>把看过的教程，连接成自己的知识。</p></div><div class="welcome-art"><span class="orbit one"></span><span class="orbit two"></span><span class="art-icon">${icon('leaf')}</span><small>每一份理解，都有迹可循</small></div></div>
    <div class="stats">${[['book', d.documents.length, '份学习资料'], ['star', d.cards.length, '条知识收藏'], ['link', d.relations.filter((r: Row) => r.status === 'confirmed').length, '个已确认关联'], ['quiz', d.sessions.filter((s: Row) => s.status === 'completed').length, '次完成复习']].map(([ico, count, label]) => `<div class="stat"><span>${icon(String(ico))}</span><strong>${count}</strong><small>${label}</small></div>`).join('')}</div>
    <div class="section-title"><h2>我的知识库 <span>${d.documents.length}</span></h2>${button('new', icon('plus') + ' 添加资料', 'button subtle')}</div>
    ${d.documents.length ? `<div class="document-grid">${d.documents.map((doc: Row, i: number) => `<button class="document-card" data-action="document" data-id="${doc.id}"><div class="document-top"><span class="document-icon tone-${i % 3}">${icon(doc.url ? 'play' : 'book')}</span><span class="pill">${({ text: '文本笔记', subtitle: '视频字幕', tutorial: 'AI 教程' } as Row)[doc.kind] || '学习资料'}</span></div><h3>${e(doc.title)}</h3><p>${e(doc.content.replace(/[#*`]/g, '').slice(0, 100))}</p><div class="document-footer"><span>${date(doc.updated_at)} 更新</span>${icon('arrow')}</div></button>`).join('')}</div>` : empty('第一份知识，从这里开始', '导入 B 站视频字幕、Markdown 或文本，开始建立自己的学习资料库。', 'new', '导入第一份资料')}
    <div class="tip-card">${icon('link')}<div><strong>知识之间，也会相互照亮</strong><p>打开一份资料，发现相关教程；确认关联后，问答时能一起查阅。</p></div>${button('nav', '了解知识关联 ' + icon('arrow'), 'button text-button', 'data-view="relations"')}</div>`;
}

function detail() {
  const { document: doc, segments, relations } = state.detail;
  const active = relations.filter((r: Row) => r.status !== 'rejected');
  return `<div class="breadcrumb">${button('back-library', '← 我的知识库', 'button text-button')}<span>/</span><span>${e(doc.title)}</span></div>
    <div class="page-heading"><div><div class="eyebrow">YOUR KNOWLEDGE, WITH SOURCES</div><h1>${e(doc.title)}</h1><p>${date(doc.updated_at)} 更新 · ${segments.length} 个来源片段 · 选中文字可收藏</p></div><div class="toolbar">${button('edit', '编辑')}${button('export', '导出')}${button('delete-document', '删除', 'button danger-quiet')}</div></div>
    <div class="reading-layout"><section class="paper"><div class="paper-tabs">${button('tab-tutorial', '教程正文', `tab ${!state.sourceTab ? 'active' : ''}`)}${button('tab-source', '来源片段', `tab ${state.sourceTab ? 'active' : ''}`)}<span></span>${button('bookmark', icon('star') + ' 收藏选中内容', 'button subtle')}</div>
      ${state.sourceTab ? `<div class="source-list">${segments.map((s: Row, i: number) => `<div class="source-block" id="source-${s.id}"><div><span class="pill">来源 ${i + 1}${s.start != null ? ` · ${Math.floor(s.start / 60)}:${String(Math.floor(s.start % 60)).padStart(2, '0')}` : ''}</span>${s.url ? button('source-video', '跳转视频 ↗', 'button text-button', `data-url="${e(s.url)}" data-time="${s.start || 0}"`) : ''}</div><p>${e(s.text)}</p>${button('bookmark-segment', '收藏此段', 'button text-button', `data-id="${s.id}"`)}</div>`).join('')}</div>` : `<article id="reading-content" class="prose">${markdown(doc.content)}</article>`}</section>
      <aside class="context-panel"><div class="context-box"><span class="mini-icon">${icon('link')}</span><h3>与这份资料相关</h3><p>跨过课程边界，连接同一份理解。</p><div class="stack-actions">${button('related-local', '发现关键词关联', 'button')}${button('related-ai', 'AI 分析关联', 'button primary')}</div>${active.map((r: Row) => `<div class="related-mini"><span class="pill">${relationNames[r.kind]}</span><button class="inline-title" data-action="document" data-id="${r.a === doc.id ? r.b : r.a}">${e(r.a === doc.id ? r.b_title : r.a_title)} ↗</button><p>${e(r.reason)}</p>${relationSources(r)}${r.status === 'suggested' ? `${button('confirm-relation', '确认关联', 'button tiny', `data-id="${r.id}"`)} ${button('reject-relation', '忽略', 'button text-button tiny', `data-id="${r.id}"`)}` : '<span class="confirmed">✓ 已确认</span>'}</div>`).join('') || '<div class="mini-empty">发现关联后，会在这里展示具体原因。</div>'}</div>
      <div class="context-box mint"><h3>把理解再向前一步</h3><p>围绕这份资料提问，或用十道题检验掌握情况。</p>${button('ask-current', icon('chat') + ' 问问这份资料', 'button full')}${button('review-current', icon('quiz') + ' 开始十题练习', 'button full')}${button('generate-tutorial', 'AI 整理为教程', 'button text-button full')}</div></aside></div>`;
}

function cards() {
  return `<div class="page-heading"><div class="eyebrow">KEEP WHAT MATTERS</div><h1>我的收藏</h1><p>留下值得反复理解的一句话、一段解释。</p></div>${state.data.cards.length ? `<div class="cards-grid">${state.data.cards.map((c: Row) => `<div class="note-card"><span class="mini-icon">${icon('star')}</span><p class="card-quote">${e(c.text)}</p><div class="note-source">来自 ${e(c.title)}</div><div class="toolbar">${button('document', '回到资料 ↗', 'button text-button', `data-id="${c.document_id}"`)}${button('delete-card', '移除', 'button text-button muted', `data-id="${c.id}"`)}</div></div>`).join('')}</div>` : empty('收藏属于你的理解', '打开一份资料，选中内容后点击“收藏选中内容”，或在来源页收藏整段。', 'nav', '去知识库')}`;
}

function relationSources(relation: Row) {
  return (relation.evidence || []).map((s: Row) => button('citation', '对应段落 · ' + e(s.title), 'button text-button tiny', `data-id="${s.id}" data-doc="${s.document_id}"`)).join('');
}

function relationView() {
  const rows = state.data.relations.filter((r: Row) => r.status !== 'rejected');
  return `<div class="page-heading"><div class="eyebrow">CONNECT THE DOTS</div><h1>知识关联</h1><p>相似、互补、前置与差异，让零散教程连接起来。自动发现的关系需要你确认。</p></div>
    ${rows.length ? `<div class="relation-list">${rows.map((r: Row) => `<div class="relation-card"><div class="relation-nodes">${button('document', icon('book') + e(r.a_title), 'relation-node', `data-id="${r.a}"`)}<div class="relation-thread"><span>${relationNames[r.kind]}</span><i></i></div>${button('document', icon('book') + e(r.b_title), 'relation-node', `data-id="${r.b}"`)}</div><p>${e(r.reason)}</p>${relationSources(r)}<div class="toolbar"><span class="${r.status === 'confirmed' ? 'confirmed' : 'muted'}">${r.status === 'confirmed' ? '✓ 已确认' : '待确认的关联建议'}</span><span class="spacer"></span>${r.status === 'suggested' ? button('confirm-relation', '确认关联', 'button primary tiny', `data-id="${r.id}"`) : ''}${button('reject-relation', '移除关联', 'button subtle tiny', `data-id="${r.id}"`)}</div></div>`).join('')}</div>` : empty('让教程之间建立联系', '导入两份有关联的资料，打开其中一份，点击“发现关键词关联”或“AI 分析关联”。', 'nav', '前往知识库')}`;
}

function memoryView() {
  return `<div class="page-heading horizontal"><div><div class="eyebrow">A LITTLE MORE UNDERSTANDING</div><h1>长期记忆</h1><p>让助手记得你的偏好、目标和学习进度。你可以随时更正或删除。</p></div>${button('new-memory', icon('plus') + ' 添加记忆', 'button primary')}</div>
    <div class="info-banner">${icon('brain')}同名记忆更新后，旧版本不再参与默认召回。学习进度由你确认，不会因为读过就标为已掌握。</div>
    ${state.data.memories.length ? `<div class="cards-grid">${state.data.memories.map((m: Row) => `<div class="note-card"><span class="pill">${({ preference: '讲解偏好', goal: '学习目标', progress: '学习进度' } as Row)[m.kind]}</span><h3>${e(m.title)}</h3><p>${e(m.text)}</p><div class="toolbar">${button('edit-memory', '更正', 'button text-button', `data-id="${m.id}"`)}${button('delete-memory', '删除', 'button text-button muted', `data-id="${m.id}"`)}</div></div>`).join('')}</div>` : empty('下次，仍然记得你', '例如：“讲代码先给例子”“本月目标是掌握 Python 闭包”。', 'new-memory', '写下第一条记忆')}`;
}

function citations(rows: Row[]) {
  return rows.map((s, i) => `<button class="citation" data-action="citation" data-id="${s.id}" data-doc="${s.document_id}"><span>${i + 1}</span><div><strong>${e(s.title)}</strong><small>${e(s.text.slice(0, 90))}</small></div>↗</button>`).join('');
}

function askView() {
  return `<div class="page-heading"><div class="eyebrow">ASK YOUR OWN KNOWLEDGE</div><h1>把问题，交给积累过的知识</h1><p>从你的资料中查找依据，结合长期记忆，用适合你的方式解释。</p></div>
    <form id="ask-form" class="ask-form"><label class="field-label" for="ask-scope">提问范围</label><select id="ask-scope" name="document_id"><option value="">整个知识库</option>${state.data.documents.map((d: Row) => `<option value="${d.id}" ${state.askScope === d.id ? 'selected' : ''}>${e(d.title)}</option>`).join('')}</select><label class="sr-only" for="ask-question">你的问题</label><textarea id="ask-question" name="question" placeholder="例如：闭包和装饰器有什么关系？能结合我收藏的案例解释吗？" required maxlength="8000">${e(state.lastQuestion || '')}</textarea><div class="ask-bottom"><span>回答带有原文出处 · AI 服务需先配置</span><button class="button primary" type="submit">${icon('chat')} 开始提问</button></div></form>
    ${state.answer ? `<section class="answer-card"><div class="section-title"><h2>来自你的知识库</h2><span class="pill">有据可循</span></div><article class="prose">${markdown(state.answer.answer)}</article><div class="citation-list">${citations(state.answer.citations)}</div>${state.answer.notice ? `<p class="small-note">${e(state.answer.notice)}</p>` : ''}</section>` : `<div class="ask-suggestions"><span>理解一个概念</span><span>比较不同讲法</span><span>找到遗漏的前置知识</span></div>`}
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
    <div class="form-divider"></div><h2>语义检索 <span class="pill">可选</span></h2><p>未配置时仍可使用本地关键词搜索。mem0 从原文提取知识并存入本地。首次配置或导入新资料后，请同步记忆；未配置时可使用关键词搜索。</p><label for="embedding-model">Embedding 模型名称</label><input id="embedding-model" name="embedding_model" value="${e(s.embedding_model || '')}" placeholder="填写支持中文的 Embedding 模型 ID"/><label for="embedding-url">Embedding API 地址</label><input id="embedding-url" name="embedding_url" type="url" value="${e(s.embedding_url || '')}" placeholder="留空使用上面的 API 地址"/><p class="small-note">Embedding 与对话共用此 API Key，请填写同一服务商或兼容网关的地址。</p><div class="toolbar"><button type="submit" class="button primary">保存设置</button>${button('test-model', '测试已保存的连接')}${button('build-index', '同步 mem0 记忆')}</div></form>
    <aside><div class="context-box"><h3>记忆引擎 · mem0 ${e(state.data.mem0.version)}</h3><p>已接入下载源码的 Memory.add / search。</p><p>${state.data.mem0.knowledge_count} 条知识事实 · ${state.data.mem0.personal_count} 条个人记忆<br>${state.data.mem0.pending} 项资料或记忆待同步</p><p>需要对话模型与 Embedding 模型，使用当前 API Key。</p></div><div class="context-box"><h3>数据留在你的电脑</h3><p>教程、收藏、题库和记忆保存在：</p><code class="data-path">${e(state.data.data_directory)}</code><p>密钥使用系统加密保存。关闭应用后数据仍保留。</p>${state.data.has_api_key ? button('remove-key', '移除已保存的 API Key', 'button danger-quiet') : ''}</div><div class="context-box"><h3>关于当前版本</h3><p>支持文本、Markdown、SRT / VTT / B 站字幕 JSON。B 站自动导入依赖视频提供可获取的字幕。</p><p>当前没有音频转写或截图提取。简答评分由 AI 辅助，适合学习反馈。</p></div></aside></div>`;
}

function searchView() {
  return `<div class="page-heading"><div class="eyebrow">FIND WHAT YOU HAVE LEARNED</div><h1>搜索：${e(state.search)}</h1><p>${e(state.results?.notice || '')}</p></div>${state.results?.results.length ? `<div class="search-results">${state.results.results.map((s: Row) => `<button data-action="citation" data-id="${s.id}" data-doc="${s.document_id}" class="search-result"><div><span class="pill">${e(s.retrieval)}匹配</span><h3>${e(s.title)}</h3></div><p>${e(s.text.slice(0, 400))}</p><small>打开来源 ↗</small></button>`).join('')}</div>` : empty('还没有找到相关资料', '试试具体的概念名称，或先导入包含该知识点的资料。')}`;
}

function modal() {
  if (!state.modal) return '';
  let content = '';
  if (state.modal === 'new') content = `<div class="modal-heading"><div><span class="eyebrow">ADD TO YOUR KNOWLEDGE</span><h2>导入学习资料</h2></div>${button('close-modal', icon('close'), 'icon-button', 'aria-label="关闭"')}</div><div class="import-methods">${button('import-file', icon('book') + ' 选择文本 / 字幕文件', 'button')}${button('video-modal', icon('play') + ' 从 B 站链接导入', 'button')}</div><form id="import-form"><label for="import-title">资料标题</label><input id="import-title" name="title" placeholder="例如：Python 闭包与装饰器" required maxlength="200"/><label for="import-content">粘贴文本或 Markdown</label><textarea id="import-content" name="content" placeholder="把想保存的知识放进来……" required></textarea><div class="modal-footer"><small>本地保存 · 可搜索 · 可关联 · 可复习</small><button type="submit" class="button primary">保存到知识库</button></div></form>`;
  if (state.modal === 'video') content = `<div class="modal-heading"><h2>导入 B 站视频</h2>${button('close-modal', icon('close'), 'icon-button', 'aria-label="关闭"')}</div><p class="muted">获取可用字幕后保存到知识库，再按需生成教程。无可用字幕时可手动导入字幕文件。</p><form id="video-form"><label for="video-url">完整视频链接</label><input id="video-url" name="url" type="url" placeholder="https://www.bilibili.com/video/BV…" required/><div class="modal-footer"><small>仅获取字幕，当前没有音频转写</small><button class="button primary" type="submit">获取字幕并导入</button></div></form>`;
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
  const views: Record<string, () => string> = { library, cards, relations: relationView, ask: askView, review: reviewView, memory: memoryView, settings: settingsView, search: searchView };
  root.innerHTML = `${nav()}<main><header class="topbar"><span class="workspace-name">个人空间 <small>/ ${({ library: '知识库', cards: '我的收藏', relations: '知识关联', ask: '知识问答', review: '复习与题库', memory: '长期记忆', settings: '设置', search: '搜索' } as Row)[state.view]}</small></span><form id="search-form" class="global-search">${icon('search')}<input name="query" aria-label="搜索知识库" placeholder="搜索你的知识……" value="${e(state.search)}"/><button type="submit" aria-label="搜索">↵</button></form><span class="avatar">知</span></header><div class="content">${(views[state.view] || library)()}</div></main>${modal()}${state.busy ? `<div class="busy-mask"><span class="spinner"></span><strong>${e(state.busy)}</strong><small>处理中，请稍候。已保存内容会保留在本地。</small></div>` : ''}`;
}

async function openDoc(id: string) {
  state.detail = await api.call('document', { id }); state.view = 'library'; state.selected = id; state.sourceTab = false; state.modal = '';
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
  if (target.id !== 'short-answer') return;
  state.quiz.answers[state.quiz.questions[state.question].id] = target.value;
  const status = document.querySelector('#draft-state'); if (status) status.textContent = '正在保存…';
  clearTimeout(draftTimer); draftTimer = setTimeout(() => saveDraft().catch(err => toast(err.message, true)), 500);
});
root.addEventListener('change', event => {
  const target = event.target as HTMLInputElement;
  if (target.name !== 'choice') return;
  const q = state.quiz.questions[state.question];
  state.quiz.answers[q.id] = Array.from(root.querySelectorAll<HTMLInputElement>('input[name="choice"]:checked')).map(x => x.value);
  render(); saveDraft().catch(err => toast(err.message, true));
});

root.addEventListener('click', async event => {
  const target = (event.target as Element).closest<HTMLElement>('[data-action]');
  if (!target || state.busy) return;
  const a = target.dataset.action, id = target.dataset.id!;
  if (a === 'nav') { await saveDraft().catch(err => toast(err.message, true)); state.view = target.dataset.view || 'library'; state.detail = null; state.modal = ''; render(); return; }
  if (a === 'new') { state.modal = 'new'; render(); return; }
  if (a === 'video-modal') { state.modal = 'video'; render(); return; }
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
    await work('保存收藏…', async () => { await api.call('add_card', { document_id: state.selected, text }); await refresh(); toast('已收藏，保留原始资料出处'); }); return;
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
  await work(({ 'import-file': '读取资料文件…', 'generate-tutorial': '正在根据来源整理教程…', 'related-ai': '正在分析教程之间的关系…', 'build-index': 'mem0 正在抽取并保存知识，首次同步可能需要几分钟…' } as Row)[a!] || '处理中…', async () => {
    if (a === 'document') await openDoc(id);
    if (a === 'citation') { const data = await api.call('document', { id: target.dataset.doc }); state.citation = data.segments.find((s: Row) => s.id === id); if (!state.citation) throw new Error('来源片段已更新或删除'); state.modal = 'citation'; }
    if (a === 'source-video') { const url = new URL(target.dataset.url!); url.searchParams.set('t', String(Math.floor(Number(target.dataset.time)))); await api.openLink(url.toString().replace(/^http:/, 'https:')); }
    if (a === 'import-file') { const file = await api.importFile(); if (file) { const doc = await api.call('import_text', file); await refresh(); await openDoc(doc.id); toast('资料已导入'); } }
    if (a === 'export') { if (await api.exportDocument(state.selected)) toast('Markdown 已导出'); }
    if (a === 'bookmark-segment') { const s = state.detail.segments.find((s: Row) => s.id === id); await api.call('add_card', { document_id: state.selected, text: s.text, segment_id: s.id }); await refresh(); toast('已收藏此段资料'); }
    if (a === 'delete-document') { await api.call('delete_document', { id: state.selected }); state.detail = null; state.selected = null; state.modal = ''; await refresh(); }
    if (a === 'delete-card' || a === 'delete-memory') { await api.call(a.replace('-', '_'), { id }); await refresh(); }
    if (a === 'related-local' || a === 'related-ai') { await api.call('related', { id: state.selected, use_ai: a === 'related-ai' }); await refresh(); await openDoc(state.selected); toast('关联候选已更新，可确认或忽略'); }
    if (a === 'confirm-relation' || a === 'reject-relation') { await api.call('set_relation', { id, status: a === 'confirm-relation' ? 'confirmed' : 'rejected' }); await refresh(); if (state.detail) await openDoc(state.selected); }
    if (a === 'generate-tutorial') { await api.call('tutorial', { id: state.selected }); await refresh(); await openDoc(state.selected); toast('已生成教程，原始来源片段仍保留'); }
    if (a === 'open-quiz') { state.quiz = await api.call('quiz', { id }); state.question = 0; }
    if (a === 'test-model') { const result = await api.call('test_model'); toast(result.message); }
    if (a === 'build-index') { const result = await api.call('sync_mem0'); await refresh(); toast(result.message); }
    if (a === 'remove-key') { await api.saveCredential(''); await refresh(); toast('已移除 API Key'); }
  });
});

root.addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.target as HTMLFormElement;
  const values = Object.fromEntries(new FormData(form).entries()) as Record<string, string>;
  if (state.busy) return;
  if (form.id === 'settings-form') { await work('保存模型设置…', async () => { const { api_key, ...settings } = values; await api.call('save_settings', settings); if (api_key.trim()) await api.saveCredential(api_key); await refresh(); toast('设置已保存'); }); return; }
  if (form.id === 'import-form') { await work('保存资料…', async () => { const doc = await api.call('import_text', values); await refresh(); await openDoc(doc.id); toast('已保存到本地知识库'); }); return; }
  if (form.id === 'video-form') { await work('正在获取视频字幕…', async () => { const doc = await api.call('import_video', values); await refresh(); await openDoc(doc.id); toast('字幕已保存，可点击 AI 整理为教程'); }); return; }
  if (form.id === 'memory-form') { await work('保存长期记忆…', async () => { await api.call('save_memory', values); state.modal = ''; await refresh(); toast('记忆已保存，将用于后续问答'); }); return; }
  if (form.id === 'edit-form') { await work('保存修改…', async () => { await api.call('update_document', { ...values, id: state.selected }); invalidateEditedSource(state.selected); await refresh(); await openDoc(state.selected); }); return; }
  if (form.id === 'search-form') { if (!values.query.trim()) return; state.search = values.query; await work('检索知识库…', async () => { state.results = await api.call('search', { query: values.query }); state.view = 'search'; }); return; }
  if (form.id === 'ask-form') { state.lastQuestion = values.question; state.askScope = values.document_id; await work('正在检索资料并组织回答…', async () => { state.answer = await api.call('ask', { question: values.question, document_id: values.document_id || null }); await refresh(); }); }
});

api.onClosing(() => {
  saveDraft().then(() => api.finishClose(true)).catch(() => api.finishClose(false));
});
render();
refresh().then(render).catch(err => { root.textContent = '打开知识库失败：' + err.message; });
