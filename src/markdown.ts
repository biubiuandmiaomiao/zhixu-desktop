import { Marked, Renderer, type Tokens } from 'marked';
import DOMPurify from 'dompurify';

type Source = {id:string; document_id?:string};
type Asset = {id:string; data_url:string; caption?:string};
type Context = {documentId?:string; sources?:Source[]; assets?:Asset[]};
const escape = (value:unknown) => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
export const headingId = (value:string) => (value.startsWith('^') ? 'block-' + value.slice(1) : 'heading-' + value.normalize('NFKC').trim().toLowerCase().replace(/[^\p{L}\p{N}_-]+/gu,'-'));

export function renderMarkdown(text:string, context:Context = {}) {
  const sourceIds = new Set((context.sources || []).map(s=>s.id));
  const assets = new Map((context.assets || []).map(a=>[a.id,a]));
  const noteButton = (target:string,label:string) => `<button type="button" class="note-link" data-action="note-link" data-target="${escape(target)}" data-doc="${escape(context.documentId || '')}">${label}</button>`;
  const renderer = new Renderer();
  renderer.html = ({text}) => /^\s*<!--/.test(text) ? '' : escape(text);
  renderer.heading = function(token) {
    return `<h${token.depth} id="${headingId(token.text)}">${this.parser.parseInline(token.tokens)}</h${token.depth}>`;
  };
  renderer.paragraph = function(token) {
    const last = token.tokens.at(-1);
    const marker = last?.type === 'text' ? /(?:^|\s)\^([A-Za-z0-9-]+)\s*$/.exec(last.raw) : null;
    const html = this.parser.parseInline(token.tokens);
    return marker ? `<p id="block-${marker[1]}">${html.replace(/(?:^|\s)\^[A-Za-z0-9-]+\s*$/,'')}</p>\n` : `<p>${html}</p>\n`;
  };
  renderer.link = function(token) {
    const label = this.parser.parseInline(token.tokens);
    if (token.href.startsWith('zhixu-source:')) {
      const id = token.href.slice('zhixu-source:'.length);
      return sourceIds.has(id) ? `<button type="button" class="source-reference" data-action="citation" data-id="${escape(id)}" data-doc="${escape(context.documentId)}" data-source-id="${escape(id)}">${label}</button>` : `<span class="unresolved-link" title="引用的原文已更新或不存在">${label}</span>`;
    }
    if (/^https?:\/\//i.test(token.href)) {
      try {
        const url = new URL(token.href);
        if (url.username || url.password) return label;
        return `<button type="button" class="external-note-link" data-action="external-link" data-url="${escape(url.toString())}">${label} ↗</button>`;
      } catch { return label; }
    }
    if (!/^[a-z][\w+.-]*:/i.test(token.href) && !token.href.startsWith('//')) return noteButton(token.href,label);
    return `<span>${label}</span>`;
  };
  renderer.image = token => {
    if (token.href.length <= 2_000_000 && /^data:image\/(?:jpeg|png|webp);base64,[A-Za-z0-9+/=]+$/.test(token.href)) return `<img src="${token.href}" alt="${escape(token.text)}" loading="lazy"/>`;
    const match = /^zhixu-asset:([a-zA-Z0-9-]+)$/.exec(token.href);
    const asset = match ? assets.get(match[1]) : undefined;
    if (asset && /^data:image\/(?:jpeg|png|webp);base64,[A-Za-z0-9+/=]+$/.test(asset.data_url)) {
      return `<figure><img src="${asset.data_url}" alt="${escape(token.text)}" loading="lazy"/><figcaption>${escape(asset.caption || token.text)}</figcaption></figure>`;
    }
    if (/^https:\/\//i.test(token.href)) return `<button type="button" class="external-note-link" data-action="external-link" data-url="${escape(token.href)}">查看图片：${escape(token.text || '外部图片')} ↗</button>`;
    return `<span class="muted">[图片：${escape(token.text || '附件尚未导入')}]</span>`;
  };
  const parser = new Marked({renderer,gfm:true,breaks:false});
  parser.use({extensions:[{
    name:'wikilink',level:'inline',
    start:src=>src.indexOf('[['),
    tokenizer(src) {
      const match = /^\[\[([^\]\n]+)\]\]/.exec(src);
      if (match) { const [target,...alias] = match[1].split('|'); return {type:'wikilink',raw:match[0],target,label:alias.join('|') || target}; }
      return undefined;
    },
    renderer:token=>noteButton(String(token.target),escape(token.label)),
  },{
    name:'sourceReference',level:'inline',
    start:src=>src.indexOf('[来源:'),
    tokenizer(src) {
      const match = /^\[来源:([a-f0-9-]{36})\]/i.exec(src);
      return match ? {type:'sourceReference',raw:match[0],source:match[1]} : undefined;
    },
    renderer:token=>sourceIds.has(String(token.source)) ? `<button type="button" class="source-reference" data-action="citation" data-id="${escape(token.source)}" data-doc="${escape(context.documentId)}" data-source-id="${escape(token.source)}">原文出处 ↗</button>` : '<span class="unresolved-link">[原文引用已失效]</span>',
  }]});
  // HTML from the note is escaped above. Only renderer-created actions survive.
  return DOMPurify.sanitize(parser.parse(text,{async:false}),{FORBID_TAGS:['style','script','iframe','object','form','input'],ADD_ATTR:['data-action','data-id','data-doc','data-target','data-url','data-source-id']});
}

export function markdownOutline(text:string) {
  return new Marked().lexer(text).filter(t=>t.type === 'heading').slice(0,200).map(token=>{const t = token as Tokens.Heading;return {text:t.text,id:headingId(t.text),depth:t.depth};});
}
