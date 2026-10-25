"""Deterministic note metadata, portable provenance and immutable revisions.

Original segments remain the only factual search evidence. Cards and revisions may
retain snapshots for display; those snapshots are never added to the search index.
"""
import csv
import html
import json
import math
import os
import posixpath
import re
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit


PORTABLE_MARKER = '<!-- zhixu-notebook:v1\n'
MAX_FILES = 500
MAX_FILE_BYTES = 24_000_000
MAX_VAULT_BYTES = 40_000_000
MAX_PORTABLE_SEGMENTS = 50_000  # Matches admitted media transcript rows.


def identifier():
    return str(uuid.uuid4())


def date_now():
    return datetime.now(timezone.utc).isoformat()


def without_code(text):
    mask = lambda value: re.sub(r'[^\r\n]', ' ', value)
    lines, fence = [], None
    for line in text.splitlines(keepends=True):
        delimiter = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if fence:
            if delimiter and delimiter[1][0] == fence[0] and len(delimiter[1]) >= len(fence):
                fence = None
            lines.append(mask(line))
        elif delimiter:
            fence = delimiter[1]
            lines.append(mask(line))
        else:
            lines.append(line)
    text = ''.join(lines)
    text = re.sub(r'`+[^`\n]*`+', lambda m: mask(m[0]), text)
    return re.sub(r'<!--.*?-->', lambda m: mask(m[0]), text, flags=re.S)


def frontmatter(text):
    """Read only the useful scalar/list subset; never instantiate YAML objects."""
    match = re.match(r'\A\ufeff?---\s*\n(.*?)\n---\s*(?:\n|$)', text, re.S)
    if not match:
        return {}, text
    data, current = {}, None
    for line in match.group(1).splitlines():
        pair = re.match(r'^(tags?|aliases?):\s*(.*)$', line, re.I)
        if pair:
            current, value = pair.group(1).lower(), pair.group(2).strip()
            current = 'tags' if current.startswith('tag') else 'aliases'
            if value.startswith('[') and value.endswith(']'):
                values = next(csv.reader([value[1:-1]], skipinitialspace=True), [])
            else:
                values = [value] if value else []
            data[current] = [v.strip().strip('"\'') for v in values if v.strip()]
        elif current and re.match(r'^\s+-\s+', line):
            data[current].append(re.sub(r'^\s+-\s+', '', line).strip().strip('"\''))
        elif line.strip():
            current = None
    return data, text[match.end():]


def visible_text(text):
    """Normalize display formatting only, keeping an exact character sequence.

    Whitespace is immaterial for matching a rendered selection across raw chunks;
    paraphrases still cannot match and require explicit original source IDs.
    """
    text = re.sub(r'(?m)^\s*(?:`{3,}|~{3,}).*$', '', text)
    text = re.sub(r'\[来源:[^\]]+\]', '', text)
    text = re.sub(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]', lambda m: m[2] or m[1], text)
    text = re.sub(r'!?\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'(?m)^\s*(?:#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)', '', text)
    text = re.sub(r'[\*_`~]', '', text)
    return re.sub(r'\s+', '', html.unescape(text))


def safe_relative(value):
    value = str(value).replace('\\', '/')
    parts = PurePosixPath(value).parts
    if not value or value.startswith('/') or any(p in ('..', '.') or ':' in p or '\x00' in p for p in parts):
        raise ValueError('笔记路径必须位于所选文件夹内')
    if len(value) > 1000 or len(parts) > 16:
        raise ValueError('笔记路径过长')
    return '/'.join(parts)


def filename(title):
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', title).strip(' .')[:100] or '笔记'
    if re.fullmatch(r'(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])', title, re.I):
        title = '_' + title
    return title + '.md'


def is_link(path):
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


class Notebook:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS note_meta(
                document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
                path TEXT NOT NULL, bookmarked INTEGER NOT NULL DEFAULT 0, original_id TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS note_tags(
                document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
                tag TEXT NOT NULL, PRIMARY KEY(document_id,tag));
            CREATE TABLE IF NOT EXISTS note_aliases(
                document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
                alias TEXT NOT NULL, origin TEXT NOT NULL, PRIMARY KEY(document_id,alias));
            CREATE TABLE IF NOT EXISTS note_links(
                document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
                position INTEGER NOT NULL, target TEXT NOT NULL, label TEXT NOT NULL,
                kind TEXT NOT NULL, target_id TEXT, binding_state TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(document_id,position));
            CREATE INDEX IF NOT EXISTS note_links_target ON note_links(target_id);
            CREATE TABLE IF NOT EXISTS document_versions(
                id TEXT PRIMARY KEY, document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
                title TEXT NOT NULL, content TEXT NOT NULL, url TEXT NOT NULL, kind TEXT NOT NULL,
                sources TEXT NOT NULL, created_at TEXT NOT NULL, reason TEXT NOT NULL, links TEXT);
            CREATE TABLE IF NOT EXISTS note_tombstones(
                document_id TEXT PRIMARY KEY, deleted_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS card_provenance(
                card_id TEXT PRIMARY KEY REFERENCES cards(id) ON DELETE CASCADE,
                source_ids TEXT NOT NULL, snapshots TEXT NOT NULL);
        ''')
        if 'binding_state' not in {r['name'] for r in self.store.rows('PRAGMA table_info(note_links)')}:
            self.db.execute("ALTER TABLE note_links ADD COLUMN binding_state TEXT NOT NULL DEFAULT ''")
        if 'links' not in {r['name'] for r in self.store.rows('PRAGMA table_info(document_versions)')}:
            # NULL distinguishes unknown old history from a real empty snapshot.
            self.db.execute('ALTER TABLE document_versions ADD COLUMN links TEXT')
        self.db.execute("""UPDATE note_links SET binding_state=CASE WHEN EXISTS(
            SELECT 1 FROM documents d WHERE d.id=note_links.target_id) THEN 'bound' ELSE 'deleted' END
            WHERE target_id IS NOT NULL AND binding_state=''""")
        self.db.execute("INSERT OR IGNORE INTO note_tombstones SELECT target_id,? FROM note_links WHERE binding_state='deleted' AND target_id IS NOT NULL", (date_now(),))
        # Additive migration: preserve original tables and historical business rows.
        for doc in self.store.documents():
            if not self.store.rows('SELECT 1 FROM note_meta WHERE document_id=?', (doc['id'],)):
                self.added(doc['id'], refresh=False, reason='migration')
        for card in self.store.rows('SELECT * FROM cards'):
            if not self.store.rows('SELECT 1 FROM card_provenance WHERE card_id=?', (card['id'],)):
                self.save_card_evidence(card['id'], card['document_id'], card['text'], card['segment_id'])
        self.refresh_links()
        self.db.commit()

    @staticmethod
    def decode_portable(content):
        match = re.search(r'\n*<!-- zhixu-notebook:v1\s*\n(.*?)\n-->\s*\Z', content, re.S)
        if not match:
            if '<!-- zhixu-notebook:' in content:
                raise ValueError('知序 Markdown 元数据不完整或版本不受支持')
            return None
        try:
            data = json.loads(match[1])
            if data.get('version') != 1 or not isinstance(data.get('segments'), list) or not data['segments'] or len(data['segments']) > MAX_PORTABLE_SEGMENTS:
                raise ValueError()
            if not isinstance(data.get('title'), str) or not data['title'].strip() or len(data['title']) > 200:
                raise ValueError()
            if not isinstance(data.get('url', ''), str) or not isinstance(data.get('kind'), str) or len(data['kind']) > 40:
                raise ValueError()
            parsed = urlsplit(data.get('url', ''))
            if data.get('url') and (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password):
                raise ValueError()
            seen, size = set(), 0
            for source in data['segments']:
                sid, text, start = source['id'], source['text'], source.get('start')
                if not isinstance(sid, str) or not sid or len(sid) > 100 or sid in seen or not isinstance(text, str) or not text.strip():
                    raise ValueError()
                if start is not None and (isinstance(start, bool) or not isinstance(start, (float, int)) or not math.isfinite(start) or start < 0):
                    raise ValueError()
                seen.add(sid)
                size += len(text)
            if size > 2_000_000:
                raise ValueError()
            if 'body_length' in data:
                length = data['body_length']
                marker_start = content.index('<!-- zhixu-notebook:v1', match.start())
                if isinstance(length, bool) or not isinstance(length, int) or not 0 < length <= 2_000_000 or content[length:marker_start] != '\n\n':
                    raise ValueError()
                data['content'] = content[:length]
            else:
                data['content'] = content[:match.start()]
            if data.get('path'):
                data['path'] = safe_relative(data['path'])
            if 'links' in data:
                if not isinstance(data['links'], list) or len(data['links']) > 2000:
                    raise ValueError()
                for link in data['links']:
                    if (not isinstance(link, dict) or not isinstance(link.get('target'), str) or len(link['target']) > 4000
                            or link.get('kind') not in ('wiki', 'markdown') or not isinstance(link.get('position'), int)
                            or not 0 <= link['position'] <= len(data['content'])
                            or link.get('state', '') not in ('', 'bound', 'deleted', 'legacy', 'ambiguous')
                            or (link.get('target_id') is not None and (not isinstance(link['target_id'], str) or not 0 < len(link['target_id']) <= 100))):
                        raise ValueError()
                    if link.get('state') in ('bound', 'deleted', 'ambiguous') and not link.get('target_id'):
                        raise ValueError()
                    if link.get('target_id') and not link.get('state'):
                        link['state'] = 'bound'
            return data
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ValueError('知序 Markdown 元数据或来源无效，未导入') from None

    def added(self, document_id, source_path='', original_id='', refresh=True, reason='import', bindings=None):
        doc = self.store.document(document_id)
        path = safe_relative(source_path) if source_path else filename(doc['title'])
        self.db.execute('INSERT INTO note_meta(document_id,path,original_id) VALUES(?,?,?)', (document_id, path, str(original_id)[:100]))
        if bindings is not None and refresh and original_id:
            bindings = [{**b, 'target_id': document_id} if b.get('target_id') == original_id and b.get('state') == 'bound' else b for b in bindings]
        self.index_document(document_id, bindings=bindings)
        if refresh:
            self.refresh_links()
        self.record_version(document_id, reason)

    def renamed(self, document, title):
        if document['title'] != title:
            self.db.execute('INSERT OR IGNORE INTO note_aliases VALUES(?,?,?)', (document['id'], document['title'], 'rename'))

    def updated(self, document_id, reason='edit', bindings=None, legacy=False):
        self.index_document(document_id, bindings=bindings, legacy=legacy)
        self.refresh_links()
        self.record_version(document_id, reason)

    @staticmethod
    def parsed_links(content):
        _, body = frontmatter(content)
        text = without_code(body)
        links = []
        for match in re.finditer(r'(?<![!\\])\[\[([^\]\n]+)\]\]', text):
            target, _, label = match[1].partition('|')
            links.append((match.start(), target.strip(), label.strip() or target.strip(), 'wiki'))
        for match in re.finditer(r'(?<![!\\])\[([^\]\n]+)\]\(<?([^\s)>]+)>?(?:\s+["\'][^\n]*?["\'])?\)', text):
            target = html.unescape(match[2])
            if not re.match(r'^[a-zA-Z][\w+.-]*:', target) and not target.startswith('//'):
                links.append((match.start(), target, match[1], 'markdown'))
        return sorted(links)[:2000]

    def index_document(self, document_id, bindings=None, legacy=False):
        doc = self.store.document(document_id)
        previous = self.store.rows('SELECT * FROM note_links WHERE document_id=? ORDER BY position', (document_id,))
        if legacy:
            previous = []
        if bindings is not None:
            previous = [{**b, 'binding_state': b.get('state', '')} for b in bindings]
        data, body = frontmatter(doc['content'])
        text = without_code(body)
        tags = data.get('tags', []) + re.findall(r'(?<![\w/#])#([^\W\d][\w/\-]*|[\u4e00-\u9fff][\w/\-]*)', text, re.U)
        tags = list(dict.fromkeys(t.strip().lstrip('#') for t in tags if t.strip().lstrip('#')))
        self.db.execute('DELETE FROM note_tags WHERE document_id=?', (document_id,))
        self.db.executemany('INSERT OR IGNORE INTO note_tags VALUES(?,?)', [(document_id, t[:200]) for t in tags[:200]])
        self.db.execute("DELETE FROM note_aliases WHERE document_id=? AND origin='frontmatter'", (document_id,))
        self.db.executemany('INSERT OR IGNORE INTO note_aliases VALUES(?,?,?)', [(document_id, a[:200], 'frontmatter') for a in data.get('aliases', [])[:100]])
        self.db.execute('DELETE FROM note_links WHERE document_id=?', (document_id,))
        for position, target, label, kind in self.parsed_links(doc['content']):
            match = next((r for r in previous if r['target'] == target and r['kind'] == kind and r['position'] == position), None)
            if match is None:
                match = next((r for r in previous if r['target'] == target and r['kind'] == kind), None)
            binding, state = (match.get('target_id'), match.get('binding_state', '')) if match else (None, 'legacy' if legacy else '')
            self.db.execute('INSERT INTO note_links(document_id,position,target,label,kind,target_id,binding_state) VALUES(?,?,?,?,?,?,?)', (document_id, position, target, label, kind, binding, state))

    def _resolve(self, from_document_id, target, binding=None, state='', preferred_ids=None):
        target = str(target).strip()
        if target.startswith('[[') and target.endswith(']]'):
            target = target[2:-2].split('|', 1)[0]
        raw, _, heading = target.partition('#')
        raw, heading = unquote(raw).replace('\\', '/'), unquote(heading)
        result = {'target': target, 'document_id': None, 'heading': heading, 'unresolved': True, 'reason': 'missing', 'candidates': []}
        documents = {d['id']: d for d in self.store.rows("SELECT id,title FROM documents WHERE workspace='default'")}
        if state == 'legacy':
            return {**result, 'reason': 'history_unknown'}
        if state == 'deleted' or (binding and self.store.rows('SELECT 1 FROM note_tombstones WHERE document_id=?', (binding,))):
            return {**result, 'reason': 'deleted'}
        if state == 'ambiguous':
            return {**result, 'reason': 'ambiguous'}
        if binding:
            if binding not in documents:
                return {**result, 'reason': 'missing_identity'}
            chosen = documents[binding]
        else:
            if re.match(r'^[a-zA-Z][\w+.-]*:', raw) or raw.startswith('//') or '\x00' in raw:
                return {**result, 'reason': 'unsafe'}
            if not raw:
                chosen = documents.get(from_document_id)
                if not chosen:
                    return result
            elif raw in documents and not preferred_ids:
                chosen = documents[raw]
            else:
                meta = {r['document_id']: r for r in self.store.rows('SELECT * FROM note_meta')}
                base = posixpath.dirname(meta.get(from_document_id, {}).get('path', ''))
                relative = posixpath.normpath(posixpath.join(base, raw)) if not raw.startswith('/') else posixpath.normpath(raw.lstrip('/'))
                if relative == '..' or relative.startswith('../'):
                    return {**result, 'reason': 'unsafe'}
                add_ext = lambda p: p if p.lower().endswith('.md') else p + '.md'
                name = raw[:-3] if raw.lower().endswith('.md') else raw
                aliases = self.store.rows('SELECT document_id FROM note_aliases WHERE lower(alias)=lower(?)', (name,))
                alias_ids = {r['document_id'] for r in aliases}

                def candidates_in(ids):
                    available = {did: d for did, d in documents.items() if ids is None or did in ids}
                    found = [d for did, d in available.items() if meta[did]['path'].casefold() == add_ext(relative).casefold()]
                    if not found and '/' in raw:
                        found = [d for did, d in available.items() if meta[did]['path'].casefold() == add_ext(raw.lstrip('/')).casefold()]
                    if not found:
                        found = [d for did, d in available.items() if d['title'].casefold() == name.casefold() or PurePosixPath(meta[did]['path']).stem.casefold() == name.casefold() or did in alias_ids or meta[did]['original_id'] == raw or did == raw]
                    return found

                candidates = candidates_in(preferred_ids) if preferred_ids else []
                if not candidates:
                    candidates = candidates_in(None)
                if len(candidates) != 1:
                    if candidates:
                        result.update(reason='ambiguous', candidates=[{'document_id': d['id'], 'title': d['title'], 'path': meta[d['id']]['path']} for d in candidates])
                    return result
                chosen = candidates[0]
        content = self.store.document(chosen['id'])['content'] if heading else ''
        headings = re.findall(r'(?m)^#{1,6}\s+(.+?)\s*#*$', without_code(content)) if heading else []
        heading_found = not heading or heading in headings or (heading.startswith('^') and bool(re.search(r'(?m)\^' + re.escape(heading[1:]) + r'\s*$', content)))
        return {**result, 'document_id': chosen['id'], 'title': chosen['title'], 'unresolved': False, 'reason': '', 'heading_found': heading_found}

    def binding_snapshot(self, doc_id, content=None):
        rows = self.store.rows('SELECT * FROM note_links WHERE document_id=? ORDER BY position', (doc_id,))
        links = self.parsed_links(content) if content is not None else [(r['position'], r['target'], r['label'], r['kind']) for r in rows]
        snapshots = []
        for index, (position, target, _, kind) in enumerate(links):
            row = rows[index] if index < len(rows) and rows[index]['kind'] == kind else {}
            binding, state = row.get('target_id'), row.get('binding_state', '')
            if binding and self.store.rows('SELECT 1 FROM note_tombstones WHERE document_id=?', (binding,)):
                state = 'deleted'
            snapshots.append({'position': position, 'target': target, 'kind': kind, 'target_id': binding, 'state': state})
        return snapshots

    def _remember_first_bindings(self, doc_ids):
        for doc_id in doc_ids:
            current = {(r['position'], r['target'], r['kind']): r for r in self.binding_snapshot(doc_id)}
            content = self.store.document(doc_id)['content']
            for version in self.store.rows('SELECT id,links FROM document_versions WHERE document_id=? AND content=? AND links IS NOT NULL', (doc_id, content)):
                links, changed = json.loads(version['links']), False
                for link in links:
                    row = current.get((link['position'], link['target'], link['kind']))
                    if row and row['target_id'] and not link.get('target_id') and not link.get('state'):
                        link['target_id'], link['state'], changed = row['target_id'], row['state'], True
                if changed:
                    self.db.execute('UPDATE document_versions SET links=? WHERE id=?', (json.dumps(links, ensure_ascii=False), version['id']))

    def refresh_links(self, document_ids=None, preferred_ids=None):
        changed = set()
        for row in self.store.rows("SELECT * FROM note_links WHERE target_id IS NULL AND binding_state=''"):
            if document_ids is not None and row['document_id'] not in document_ids:
                continue
            result = self._resolve(row['document_id'], row['target'], preferred_ids=preferred_ids)
            if not result['unresolved']:
                self.db.execute("UPDATE note_links SET target_id=?,binding_state='bound' WHERE document_id=? AND position=?", (result['document_id'], row['document_id'], row['position']))
                changed.add(row['document_id'])
        self._remember_first_bindings(changed)

    def deleted(self, doc_id):
        self.db.execute('INSERT OR IGNORE INTO note_tombstones VALUES(?,?)', (doc_id, date_now()))
        self.db.execute("UPDATE note_links SET binding_state='deleted' WHERE target_id=?", (doc_id,))

    def resolve_cohort(self, documents):
        cohort = {doc['id'] for doc in documents}
        if not cohort:
            return
        originals = {}
        for row in self.store.rows('SELECT document_id,original_id FROM note_meta'):
            if row['document_id'] in cohort and row['original_id']:
                originals.setdefault(row['original_id'], []).append(row['document_id'])
        with self.db:
            for link in self.store.rows('SELECT * FROM note_links WHERE target_id IS NOT NULL'):
                if link['document_id'] not in cohort or link['binding_state'] in ('deleted', 'legacy', 'ambiguous'):
                    continue
                matches = originals.get(link['target_id'], [])
                if len(matches) == 1:
                    self.db.execute("UPDATE note_links SET target_id=?,binding_state='bound' WHERE document_id=? AND position=?", (matches[0], link['document_id'], link['position']))
                elif len(matches) > 1:
                    self.db.execute("UPDATE note_links SET binding_state='ambiguous' WHERE document_id=? AND position=?", (link['document_id'], link['position']))
            self.refresh_links(document_ids=cohort, preferred_ids=cohort)
            for doc_id in cohort:
                self.db.execute('UPDATE document_versions SET links=? WHERE rowid=(SELECT max(rowid) FROM document_versions WHERE document_id=?)', (json.dumps(self.binding_snapshot(doc_id), ensure_ascii=False), doc_id))
            self.refresh_links()

    def resolve_link(self, from_doc_id, target):
        self.store.document(from_doc_id)
        rows = self.store.rows('SELECT target_id,binding_state FROM note_links WHERE document_id=? AND target=? ORDER BY position LIMIT 1', (from_doc_id, target))
        return self._resolve(from_doc_id, target, rows[0]['target_id'] if rows else None, rows[0]['binding_state'] if rows else '')

    def metadata(self, doc_id):
        self.store.document(doc_id)
        meta = self.store.rows('SELECT * FROM note_meta WHERE document_id=?', (doc_id,))[0]
        outgoing = [{**self._resolve(doc_id, r['target'], r['target_id'], r['binding_state']), 'kind': r['kind'], 'label': r['label'], 'position': r['position']} for r in self.store.rows('SELECT * FROM note_links WHERE document_id=? ORDER BY position', (doc_id,))]
        backlinks = self.store.rows('''SELECT l.document_id,d.title,l.target,l.kind,l.label FROM note_links l
            JOIN documents d ON d.id=l.document_id WHERE l.target_id=? AND l.binding_state='bound' ORDER BY d.title,l.position''', (doc_id,))
        return {'path': meta['path'], 'bookmarked': bool(meta['bookmarked']),
                'tags': [r['tag'] for r in self.store.rows('SELECT tag FROM note_tags WHERE document_id=? ORDER BY rowid', (doc_id,))],
                'outgoing': outgoing, 'backlinks': backlinks}

    def toggle_bookmark(self, doc_id):
        self.store.document(doc_id)
        with self.db:
            self.db.execute('UPDATE note_meta SET bookmarked=1-bookmarked WHERE document_id=?', (doc_id,))
        return {'document_id': doc_id, 'bookmarked': self.metadata(doc_id)['bookmarked']}

    @staticmethod
    def parse_search(query):
        filters = []

        def extract(match):
            filters.append((match[1].lower(), next(value for value in match.groups()[1:] if value is not None)))
            return ' '

        remaining = re.sub(r'(?:^|\s)(tag|file|path):(?:"([^"]*)"|\'([^\']*)\'|(\S+))', extract, query, flags=re.I)
        return remaining.strip(), filters

    def search_document_ids(self, filters):
        """Return an allowlist shared by keyword and semantic search callers."""
        meta = {r['document_id']: r['path'] for r in self.store.rows('SELECT document_id,path FROM note_meta')}
        tags = {}
        for row in self.store.rows('SELECT document_id,tag FROM note_tags'):
            tags.setdefault(row['document_id'], []).append(row['tag'].casefold())
        admitted = []
        for doc in self.store.rows("SELECT id,title FROM documents WHERE workspace='default'"):
            path = meta[doc['id']].casefold()
            matches = True
            for kind, value in filters:
                value = value.casefold()
                if kind == 'tag':
                    value = value.lstrip('#').rstrip('/')
                    matches = any(t == value or t.startswith(value + '/') for t in tags.get(doc['id'], []))
                elif kind == 'path':
                    matches = value in path
                elif kind == 'file':
                    matches = value in doc['title'].casefold() or value in PurePosixPath(path).name.casefold()
                if not matches:
                    break
            if matches:
                admitted.append(doc['id'])
        return admitted

    def graph(self, limit=200):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError('图谱一次显示 1–200 份资料')
        docs = self.store.rows("SELECT id,title FROM documents WHERE workspace='default' ORDER BY updated_at DESC,rowid DESC")
        tags, bookmarks = {}, {r['document_id']: bool(r['bookmarked']) for r in self.store.rows('SELECT document_id,bookmarked FROM note_meta')}
        for row in self.store.rows('SELECT document_id,tag FROM note_tags ORDER BY rowid'):
            tags.setdefault(row['document_id'], []).append(row['tag'])
        nodes = [{'id': d['id'], 'title': d['title'], 'tags': tags.get(d['id'], []), 'bookmarked': bookmarks.get(d['id'], False)} for d in docs[:limit]]
        admitted = {n['id'] for n in nodes}
        edges, seen = [], set()
        for row in self.store.rows("SELECT document_id,target_id,kind FROM note_links WHERE target_id IS NOT NULL AND binding_state='bound'"):
            key = (row['document_id'], row['target_id'], row['kind'])
            if key[0] in admitted and key[1] in admitted and key not in seen:
                seen.add(key)
                edges.append({'source': key[0], 'target': key[1], 'kind': key[2]})
        for row in self.store.relations():
            if row['status'] == 'confirmed' and row['a'] in admitted and row['b'] in admitted:
                edges.append({'source': row['a'], 'target': row['b'], 'kind': 'relation', 'relation_kind': row['kind'], 'id': row['id']})
        return {'nodes': nodes, 'edges': edges, 'truncated': len(docs) > limit}

    def record_version(self, doc_id, reason):
        doc = self.store.document(doc_id)
        self.db.execute('INSERT INTO document_versions(id,document_id,title,content,url,kind,sources,created_at,reason,links) VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (identifier(), doc_id, doc['title'], doc['content'], doc['url'], doc['kind'],
                         json.dumps(self.store.segments(doc_id), ensure_ascii=False), date_now(), reason,
                         json.dumps(self.binding_snapshot(doc_id), ensure_ascii=False)))

    def versions(self, doc_id, preview_chars=None):
        if not self.store.rows("SELECT id FROM documents WHERE id=? AND workspace='default'", (doc_id,)):
            raise ValueError('资料不存在或已删除')
        if preview_chars is not None and (isinstance(preview_chars, bool) or not isinstance(preview_chars, int) or not 0 <= preview_chars <= 2_000_000):
            raise ValueError('版本预览长度无效')
        body = 'content' if preview_chars is None else 'substr(content,1,?) AS content'
        args = (doc_id,) if preview_chars is None else (preview_chars, doc_id)
        rows = self.store.rows('SELECT id,document_id,title,' + body + ',url,kind,created_at,reason,length(content) AS full_length FROM document_versions WHERE document_id=? ORDER BY rowid DESC LIMIT 100', args)
        return [{**r, 'preview_truncated': preview_chars is not None and r['full_length'] > preview_chars} for r in rows]

    def restore_version(self, doc_id, version_id):
        self.store.document(doc_id)
        rows = self.store.rows('SELECT * FROM document_versions WHERE document_id=? AND id=?', (doc_id, version_id))
        if not rows:
            raise ValueError('资料版本不存在')
        version = rows[0]
        sources = json.loads(version['sources'])
        # Service clears mem0/vectors before calling this method. Old snapshots
        # remain display-only and never silently enter the current search index.
        with self.db:
            self.store.invalidate_sources(doc_id)
            mapping = self.store.replace_sources(doc_id, sources, version['title'])
            content = self.rewrite_sources(version['content'], mapping)
            self.renamed(self.store.document(doc_id), version['title'])
            self.db.execute('UPDATE documents SET title=?,content=?,url=?,kind=?,updated_at=? WHERE id=?',
                            (version['title'], content, version['url'], version['kind'], date_now(), doc_id))
            self.updated(doc_id, 'restore', bindings=json.loads(version['links']) if version['links'] is not None else None, legacy=version['links'] is None)
        return self.store.document(doc_id)

    @staticmethod
    def rewrite_sources(content, mapping):
        return re.sub(r'\[来源:([^\]]+)\]', lambda m: '[来源:' + mapping.get(m[1], m[1]) + ']', content)

    def _export_links(self, doc_id, content, source_path, link_paths):
        _, body = frontmatter(content)
        prefix = len(content) - len(body)
        for link in self.store.rows('SELECT * FROM note_links WHERE document_id=? ORDER BY position DESC', (doc_id,)):
            if link['target_id'] not in link_paths or link['binding_state'] != 'bound':
                continue
            start = prefix + link['position']
            relative = posixpath.relpath(link_paths[link['target_id']], posixpath.dirname(source_path) or '.')
            _, separator, heading = link['target'].partition('#')
            suffix = separator + heading
            if link['kind'] == 'wiki':
                match = re.match(r'\[\[([^\]\n]+)\]\]', content[start:])
                if not match:
                    continue
                target = relative[:-3] if relative.lower().endswith('.md') else relative
                _, delimiter, label = match[1].partition('|')
                replacement = '[[' + target + suffix + '|' + (label if delimiter else link['label']) + ']]'
            else:
                match = re.match(r'\[([^\]\n]+)\]\(<?([^\s)>]+)>?(?:\s+["\'][^\n]*?["\'])?\)', content[start:])
                if not match:
                    continue
                replacement = '[' + match[1] + '](' + quote(relative, safe='/._-~') + suffix + ')'
            content = content[:start] + replacement + content[start + match.end():]
        return content

    def export_document(self, doc_id, path=None, link_paths=None):
        doc = self.store.document(doc_id)
        path = path or self.metadata(doc_id)['path']
        body = self._export_links(doc_id, doc['content'], path, link_paths) if link_paths else doc['content']
        data = {'version': 1, 'document_id': doc_id, 'title': doc['title'], 'url': doc['url'], 'kind': doc['kind'],
                'body_length': len(body), 'path': path,
                'links': self.binding_snapshot(doc_id, content=body),
                'segments': [{k: s[k] for k in ('id', 'text', 'start')} for s in self.store.segments(doc_id)]}
        encoded = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e')
        return body + '\n\n' + PORTABLE_MARKER + encoded + '\n-->\n'

    @staticmethod
    def _selected_root(directory, create=False):
        root = Path(directory)
        if not root.is_absolute():
            raise ValueError('请选择绝对路径的笔记文件夹')
        if create:
            root.mkdir(parents=True, exist_ok=True)
        if not root.is_dir() or is_link(root):
            raise ValueError('请选择普通笔记文件夹，不能使用符号链接')
        return root.resolve(strict=True)

    def import_vault(self, directory):
        root = self._selected_root(directory)
        documents, skipped, total, visited = [], [], 0, 0

        def finish():
            self.resolve_cohort(documents)
            return {'imported': len(documents), 'documents': documents, 'skipped': skipped}

        for parent, directories, files in os.walk(root, followlinks=False):
            parent = Path(parent)
            directories[:] = [name for name in sorted(directories) if not name.startswith('.') and not is_link(parent / name) and (parent / name).resolve().is_relative_to(root) and len((parent / name).relative_to(root).parts) <= 16]
            for name in sorted(files):
                visited += 1
                if visited > 5000 or len(documents) >= MAX_FILES:
                    skipped.append({'path': '', 'reason': '已达到单次导入数量限制'})
                    return finish()
                path = parent / name
                if path.suffix.lower() != '.md':
                    continue
                relative = path.relative_to(root).as_posix()
                try:
                    if is_link(path) or not path.resolve().is_relative_to(root):
                        raise ValueError('不读取文件夹外的链接文件')
                    size = path.stat().st_size
                    if size > MAX_FILE_BYTES or total + size > MAX_VAULT_BYTES:
                        raise ValueError('已达到单次导入文件大小限制')
                    content = path.read_text(encoding='utf-8-sig')
                    documents.append(self.store.add_document(path.stem, content, source_path=relative, defer_links=True))
                    total += size
                except (ValueError, OSError, UnicodeError) as exc:
                    skipped.append({'path': relative, 'reason': str(exc)[:200]})
        return finish()

    def export_vault(self, directory, transform=None):
        if transform is not None and not callable(transform):
            raise ValueError('无效的笔记导出转换器')
        root = self._selected_root(directory, create=True)
        exported, skipped, total, plan, reserved = [], [], 0, [], set()
        for doc in self.store.documents()[:MAX_FILES]:
            relative = safe_relative(self.metadata(doc['id'])['path'])
            target = root.joinpath(*PurePosixPath(relative).parts)
            try:
                for parent in reversed(target.parents):
                    if parent == root or root in parent.parents:
                        if parent.exists() and is_link(parent):
                            raise ValueError('不写入链接文件夹')
                if target.exists() or target.is_symlink() or relative.casefold() in reserved:
                    target = target.with_name(target.stem + '-' + doc['id'][:8] + '.md')
                relative = target.relative_to(root).as_posix()
                if target.exists() or target.is_symlink() or relative.casefold() in reserved:
                    raise ValueError('目标文件已存在，未覆盖')
                reserved.add(relative.casefold())
                plan.append((doc, target, relative))
            except (ValueError, OSError) as exc:
                skipped.append({'path': relative, 'reason': str(exc)[:200]})
        link_paths = {doc['id']: relative for doc, _, relative in plan}
        for doc, target, relative in plan:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.parent.resolve().is_relative_to(root):
                    raise ValueError('导出目标超出所选文件夹')
                text = self.export_document(doc['id'], path=relative, link_paths=link_paths)
                if transform is not None:
                    try:
                        text = transform(doc['id'], text)
                        if not isinstance(text, str):
                            raise ValueError('笔记导出转换器未返回 Markdown 文本')
                    except Exception as exc:
                        raise ValueError(str(exc)[:200] or '笔记导出转换失败') from None
                total += len(text.encode('utf8'))
                if total > MAX_VAULT_BYTES:
                    raise ValueError('已达到单次导出大小限制')
                with target.open('x', encoding='utf8') as stream:
                    stream.write(text)
                exported.append({'id': doc['id'], 'title': doc['title'], 'path': relative})
            except (ValueError, OSError) as exc:
                skipped.append({'path': relative, 'reason': str(exc)[:200]})
        return {'exported': len(exported), 'documents': exported, 'skipped': skipped}

    def map_selection(self, document_id, text):
        sources = self.store.segments(document_id)
        wanted = visible_text(text)
        if not wanted:
            return []
        pieces = [visible_text(s['text']) for s in sources]
        offset = ''.join(pieces).find(wanted)
        if offset < 0:
            return []
        end, position, selected = offset + len(wanted), 0, []
        for source, piece in zip(sources, pieces):
            if position < end and position + len(piece) > offset:
                selected.append(source['id'])
            position += len(piece)
        return selected

    def save_card_evidence(self, card_id, document_id, text, segment_id=None, source_ids=None):
        if source_ids is not None and (not isinstance(source_ids, list) or len(source_ids) > 100 or any(not isinstance(s, str) for s in source_ids)):
            raise ValueError('收藏来源格式无效')
        ids = list(dict.fromkeys(([segment_id] if segment_id else []) + (source_ids or [])))
        if not ids:
            ids = self.map_selection(document_id, text)
        by_id = {s['id']: s for s in self.store.segments(document_id)}
        if any(s not in by_id for s in ids):
            raise ValueError('收藏来源不属于当前资料或已删除')
        snapshots = [by_id[s] for s in ids]
        self.db.execute('INSERT OR REPLACE INTO card_provenance VALUES(?,?,?)',
                        (card_id, json.dumps(ids), json.dumps(snapshots, ensure_ascii=False)))
        return ids

    def map_card_sources(self, card_id, source_ids):
        rows = self.store.rows('SELECT * FROM cards WHERE id=?', (card_id,))
        if not rows:
            raise ValueError('收藏不存在或已经删除')
        if not isinstance(source_ids, list) or not source_ids:
            raise ValueError('请至少选择一个当前原始来源')
        card = rows[0]
        with self.db:
            ids = self.save_card_evidence(card_id, card['document_id'], card['text'], source_ids=source_ids)
            self.db.execute('UPDATE cards SET segment_id=? WHERE id=?', (ids[0], card_id))
        return next(c for c in self.cards() if c['id'] == card_id)

    def cards(self):
        rows = self.store.rows('''SELECT c.*,d.title,p.source_ids,p.snapshots FROM cards c
            JOIN documents d ON d.id=c.document_id LEFT JOIN card_provenance p ON p.card_id=c.id ORDER BY c.created_at DESC''')
        current = {s['id']: s for s in self.store.segments()}
        for row in rows:
            row['source_ids'] = json.loads(row['source_ids'] or '[]')
            row['source_snapshots'] = json.loads(row.pop('snapshots') or '[]')
            row['unmapped'] = not bool(row['source_ids'])
            row['stale'] = any(s['id'] not in current or current[s['id']]['text'] != s['text'] or current[s['id']]['document_id'] != row['document_id'] for s in row['source_snapshots'])
        return rows

    def favorite_sources(self):
        cards = self.cards()
        unavailable = [c for c in cards if c['stale'] or c['unmapped']]
        if unavailable:
            raise ValueError(f'收藏中有 {len(unavailable)} 条来源已过期或尚未定位，请重新选择原始来源后再复习')
        by_id = {s['id']: s for s in self.store.segments()}
        collected = {}
        for card in cards:
            for sid in card['source_ids']:
                source = by_id[sid]
                exact = len(card['source_ids']) == 1 and card['text'] in source['text']
                if sid not in collected:
                    collected[sid] = {**source, 'text': card['text'] if exact else source['text'], 'selected_texts': [card['text']], 'card_ids': [card['id']], 'evidence_kind': 'original', '_whole': not exact}
                else:
                    entry = collected[sid]
                    entry['card_ids'].append(card['id'])
                    entry['selected_texts'].append(card['text'])
                    if not exact:
                        entry['text'], entry['_whole'] = source['text'], True
                    elif not entry['_whole'] and card['text'] not in entry['text']:
                        entry['text'] += '\n' + card['text']
        return [{k: v for k, v in source.items() if k != '_whole'} for source in collected.values()]
