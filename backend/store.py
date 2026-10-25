"""SQLite is authoritative; all search indexes can be rebuilt from segments."""
import hashlib
import json
import math
import random
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


def uid():
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


def tokens(text):
    words = re.findall(r'[a-z0-9_]+|[\u4e00-\u9fff]+', text.lower())
    result = []
    for word in words:
        if re.search(r'[\u4e00-\u9fff]', word):
            result.extend(word[i:i + 2] for i in range(len(word) - 1))
            if len(word) == 1:
                result.append(word)
        else:
            result.append(word)
    return result


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.directory / 'knowledge.sqlite3')
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA foreign_keys=ON;
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS documents(
                id TEXT PRIMARY KEY, workspace TEXT NOT NULL, title TEXT NOT NULL,
                content TEXT NOT NULL, url TEXT NOT NULL, kind TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS segments(
                id TEXT PRIMARY KEY, document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
                text TEXT NOT NULL, start REAL, position INTEGER NOT NULL);
            CREATE VIRTUAL TABLE IF NOT EXISTS segment_fts USING fts5(id UNINDEXED, terms);
            CREATE TABLE IF NOT EXISTS cards(
                id TEXT PRIMARY KEY, document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
                segment_id TEXT REFERENCES segments(id) ON DELETE SET NULL,
                text TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS memories(
                id TEXT PRIMARY KEY, workspace TEXT NOT NULL, title TEXT NOT NULL,
                text TEXT NOT NULL, kind TEXT NOT NULL, active INTEGER NOT NULL,
                created_at TEXT NOT NULL, supersedes TEXT);
            CREATE TABLE IF NOT EXISTS relations(
                id TEXT PRIMARY KEY, a TEXT REFERENCES documents(id) ON DELETE CASCADE,
                b TEXT REFERENCES documents(id) ON DELETE CASCADE,
                kind TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, UNIQUE(a,b,kind));
            CREATE TABLE IF NOT EXISTS relation_evidence(
                relation_id TEXT REFERENCES relations(id) ON DELETE CASCADE,
                segment_id TEXT REFERENCES segments(id) ON DELETE CASCADE,
                PRIMARY KEY(relation_id,segment_id));
            CREATE TABLE IF NOT EXISTS quizzes(
                id TEXT PRIMARY KEY, body TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS conversations(
                id TEXT PRIMARY KEY, question TEXT NOT NULL, answer TEXT NOT NULL,
                citations TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
                status TEXT NOT NULL, error TEXT NOT NULL, created_at TEXT NOT NULL);
        ''')
        self.db.commit()
        from .notebook import Notebook
        self.notebook = Notebook(self)

    def close(self):
        self.db.close()

    def rows(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args)]

    def document(self, document_id):
        rows = self.rows('SELECT * FROM documents WHERE id=? AND workspace=?', (document_id, 'default'))
        if not rows:
            raise ValueError('资料不存在或已删除')
        return rows[0]

    def documents(self):
        return self.rows('SELECT * FROM documents WHERE workspace=? ORDER BY updated_at DESC,rowid DESC', ('default',))

    def add_document(self, title, content, url='', kind='text', workspace='default', segments=None, source_path='', on_saved=None, defer_links=False):
        if on_saved is not None and not callable(on_saved):
            raise ValueError('无效的资料保存回调')
        portable = self.notebook.decode_portable(content) if isinstance(content, str) else None
        original_id = ''
        if portable:
            title, content = portable['title'], portable['content']
            url, kind, segments = portable.get('url', ''), portable['kind'], portable['segments']
            source_path = source_path or portable.get('path', '')
            original_id = portable.get('document_id', '')
        if not isinstance(title, str) or not title.strip() or not isinstance(content, str) or not content.strip():
            raise ValueError('请填写标题和资料内容')
        if len(content) > 2_000_000 or len(title) > 200:
            raise ValueError('资料过长，请分批导入（正文不超过 200 万字符）')
        doc_id, date = uid(), now()
        chunks = segments or [{'text': content[i:i + 900], 'start': None} for i in range(0, len(content), 900)]
        with self.db:
            self.db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?)',
                            (doc_id, workspace, title.strip(), content, url, kind, date, date))
            mapping = {}
            for index, chunk in enumerate(chunks):
                seg_id = uid()
                if chunk.get('id'):
                    mapping[chunk['id']] = seg_id
                self.db.execute('INSERT INTO segments VALUES(?,?,?,?,?)', (seg_id, doc_id, chunk['text'], chunk.get('start'), index))
                self.db.execute('INSERT INTO segment_fts VALUES(?,?)', (seg_id, ' '.join(tokens(title + ' ' + chunk['text']))))
            if mapping:
                self.db.execute('UPDATE documents SET content=? WHERE id=?', (self.notebook.rewrite_sources(content, mapping), doc_id))
            if workspace == 'default':
                self.notebook.added(doc_id, source_path=source_path, original_id=original_id, refresh=not defer_links,
                                    bindings=portable.get('links') if portable else None)
            if on_saved is not None:
                # Callers may atomically attach media assets and finish their job;
                # they must use this connection and must not commit themselves.
                on_saved(doc_id)
        return dict(self.db.execute('SELECT * FROM documents WHERE id=?', (doc_id,)).fetchone())

    def segments(self, document_id=None):
        sql = '''SELECT s.*, d.title, d.url, d.kind FROM segments s
                 JOIN documents d ON d.id=s.document_id WHERE d.workspace='default' '''
        return self.rows(sql + (' AND d.id=?' if document_id else '') + ' ORDER BY s.position', (document_id,) if document_id else ())

    def delete_document(self, document_id):
        self.document(document_id)
        ids = {s['id'] for s in self.segments(document_id)}
        with self.db:
            for session in self.sessions(raw=True):
                if any(ids.intersection(q['source_ids']) for q in session['questions']) or any(s['document_id'] == document_id for s in session.get('sources', [])):
                    self.db.execute('DELETE FROM quizzes WHERE id=?', (session['id'],))
            self.db.executemany('DELETE FROM segment_fts WHERE id=?', [(i,) for i in ids])
            self.forget_conversations(document_id)
            self.notebook.deleted(document_id)
            self.db.execute('DELETE FROM documents WHERE id=?', (document_id,))
            self.notebook.refresh_links()

    def invalidate_sources(self, document_id):
        """Invalidate derived factual records before replacing active evidence."""
        old_ids = {s['id'] for s in self.segments(document_id)}
        for session in self.sessions(raw=True):
            if any(old_ids.intersection(q['source_ids']) for q in session['questions']) or any(s['document_id'] == document_id for s in session.get('sources', [])):
                self.db.execute('DELETE FROM quizzes WHERE id=?', (session['id'],))
        self.forget_conversations(document_id)
        self.db.execute("UPDATE relations SET status='suggested',reason='资料已修改，请重新核对。' || reason WHERE (a=? OR b=?) AND status='confirmed'", (document_id, document_id))

    def replace_sources(self, document_id, sources, title):
        old_ids = [s['id'] for s in self.segments(document_id)]
        self.db.executemany('DELETE FROM segment_fts WHERE id=?', [(s,) for s in old_ids])
        self.db.execute('DELETE FROM segments WHERE document_id=?', (document_id,))
        mapping = {}
        for position, source in enumerate(sources):
            sid = uid()
            if source.get('id'):
                mapping[source['id']] = sid
            self.db.execute('INSERT INTO segments VALUES(?,?,?,?,?)', (sid, document_id, source['text'], source.get('start'), position))
            self.db.execute('INSERT INTO segment_fts VALUES(?,?)', (sid, ' '.join(tokens(title + ' ' + source['text']))))
        return mapping

    def update_document(self, document_id, title, content, preserve_sources=False):
        doc = self.document(document_id)
        if not title.strip() or not content.strip() or len(content) > 2_000_000:
            raise ValueError('标题和正文不能为空，正文不超过 200 万字符')
        with self.db:
            self.notebook.renamed(doc, title)
            if doc['kind'] == 'text' and not preserve_sources:
                self.invalidate_sources(document_id)
                self.replace_sources(document_id, [{'text': content[offset:offset + 900], 'start': None} for offset in range(0, len(content), 900)], title)
            kind = 'tutorial' if preserve_sources and doc['kind'] == 'text' else doc['kind']
            self.db.execute('UPDATE documents SET title=?, content=?, updated_at=?,kind=? WHERE id=?', (title, content, now(), kind, document_id))
            self.notebook.updated(document_id)
        return self.document(document_id)

    def search(self, query, limit=8, document_id=None, exclude_document_id=None):
        text, filters = self.notebook.parse_search(query)
        admitted = self.notebook.search_document_ids(filters) if filters else None
        if admitted == []:
            return []
        query_tokens = list(dict.fromkeys(tokens(text)))[:60]
        if not query_tokens and not filters:
            return []
        expression = ' OR '.join('"' + t.replace('"', '""') + '"' for t in query_tokens)
        sql = '''SELECT s.*, d.title,d.url,d.kind, bm25(segment_fts) AS rank
                 FROM segment_fts JOIN segments s ON s.id=segment_fts.id
                 JOIN documents d ON d.id=s.document_id
                 WHERE segment_fts MATCH ? AND d.workspace='default' ''' if query_tokens else '''
                 SELECT s.*,d.title,d.url,d.kind,0 AS rank FROM segments s
                 JOIN documents d ON d.id=s.document_id WHERE d.workspace='default' '''
        args = [expression] if query_tokens else []
        if admitted is not None:
            sql += ' AND d.id IN (' + ','.join('?' for _ in admitted) + ')'
            args.extend(admitted)
        if document_id:
            sql += ' AND d.id=?'
            args.append(document_id)
        if exclude_document_id:
            sql += ' AND d.id<>?'
            args.append(exclude_document_id)
        sql += ' ORDER BY rank LIMIT ?'
        args.append(limit)
        rows = self.rows(sql, args)
        for r in rows:
            r['score'] = -r.pop('rank')
            r['retrieval'] = '关键词'
        return rows

    def add_card(self, document_id, text, segment_id=None, source_ids=None):
        self.document(document_id)
        if not text.strip() or len(text) > 20000:
            raise ValueError('收藏内容不能为空或超过 2 万字符')
        if segment_id and segment_id not in {s['id'] for s in self.segments(document_id)}:
            raise ValueError('收藏来源不属于当前资料')
        card_id = uid()
        with self.db:
            self.db.execute('INSERT INTO cards VALUES(?,?,?,?,?)', (card_id, document_id, segment_id, text.strip(), now()))
            self.notebook.save_card_evidence(card_id, document_id, text.strip(), segment_id, source_ids)
        return next(c for c in self.cards() if c['id'] == card_id)

    def cards(self):
        return self.notebook.cards()

    def delete_card(self, card_id):
        with self.db:
            self.db.execute('DELETE FROM cards WHERE id=?', (card_id,))

    def save_memory(self, title, text, kind='preference'):
        if not title.strip() or not text.strip() or kind not in ('preference', 'goal', 'progress'):
            raise ValueError('请填写有效的记忆标题、内容与类型')
        if len(text) > 8000:
            raise ValueError('单条记忆不超过 8000 字符')
        old = self.rows('SELECT id FROM memories WHERE title=? AND workspace=? AND active=1', (title, 'default'))
        memory_id = uid()
        with self.db:
            self.db.execute('UPDATE memories SET active=0 WHERE title=? AND workspace=?', (title, 'default'))
            self.db.execute('INSERT INTO memories VALUES(?,?,?,?,?,?,?,?)',
                            (memory_id, 'default', title.strip(), text.strip(), kind, 1, now(), old[0]['id'] if old else None))
        return next(m for m in self.memories() if m['id'] == memory_id)

    def memories(self, include_inactive=False):
        return self.rows('SELECT * FROM memories WHERE workspace=?' + ('' if include_inactive else ' AND active=1') + ' ORDER BY created_at DESC,rowid DESC', ('default',))

    def delete_memory(self, memory_id):
        with self.db:
            self.db.execute('DELETE FROM memories WHERE id=?', (memory_id,))

    def suggest_relation(self, a, b, kind, reason, evidence=None):
        self.document(a)
        self.document(b)
        if a == b or kind not in ('shared', 'prerequisite', 'supplement', 'difference'):
            raise ValueError('无效的资料关系')
        if kind != 'prerequisite':
            a, b = sorted([a, b])
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO relations VALUES(?,?,?,?,?,?,?)', (uid(), a, b, kind, reason, 'suggested', now()))
        relation = self.rows('SELECT * FROM relations WHERE a=? AND b=? AND kind=?', (a, b, kind))[0]
        if evidence and relation['status'] != 'rejected':
            with self.db:
                for segment_id in evidence:
                    self.db.execute('INSERT OR IGNORE INTO relation_evidence VALUES(?,?)', (relation['id'], segment_id))
        return relation

    def set_relation(self, relation_id, status):
        if status not in ('confirmed', 'rejected', 'suggested'):
            raise ValueError('无效的关系状态')
        with self.db:
            self.db.execute('UPDATE relations SET status=? WHERE id=?', (status, relation_id))

    def relations(self, document_id=None):
        rows = self.rows('''SELECT r.*, da.title AS a_title, db.title AS b_title FROM relations r
                            JOIN documents da ON da.id=r.a JOIN documents db ON db.id=r.b ''' +
                         ('WHERE r.a=? OR r.b=? ' if document_id else '') + 'ORDER BY r.created_at DESC',
                         (document_id, document_id) if document_id else ())
        for row in rows:
            row['evidence'] = self.rows('''SELECT s.id,s.document_id,d.title FROM relation_evidence e
                JOIN segments s ON s.id=e.segment_id JOIN documents d ON d.id=s.document_id WHERE e.relation_id=?''', (row['id'],))
        return rows

    def sample_sources(self, document_id=None, limit=12):
        if document_id == '__cards__':
            sources = self.notebook.favorite_sources()
        else:
            sources = self.segments(document_id)
        if not sources:
            return []
        # Weighted random sampling without replacement, using previous missed source evidence.
        mistakes = {}
        for session in self.sessions(raw=True)[:20]:
            for q in session.get('questions', []):
                if q.get('score', 10) < 6:
                    for source in q['source_ids']:
                        mistakes[source] = mistakes.get(source, 0) + 1
        return sorted(sources, key=lambda s: -math.log(max(random.random(), 1e-9)) / (1 + min(mistakes.get(s['id'], 0), 3)))[:limit]

    def save_session(self, body):
        with self.db:
            self.db.execute('INSERT INTO quizzes VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',
                            (body['id'], json.dumps(body, ensure_ascii=False), body['created_at']))

    def session(self, session_id):
        rows = self.rows('SELECT body FROM quizzes WHERE id=?', (session_id,))
        if not rows:
            raise ValueError('练习不存在或来源已删除')
        return json.loads(rows[0]['body'])

    def sessions(self, raw=False):
        sessions = [json.loads(r['body']) for r in self.rows('SELECT body FROM quizzes ORDER BY created_at DESC,rowid DESC')]
        if raw:
            return sessions
        return [{k: s.get(k) for k in ('id', 'title', 'created_at', 'status', 'score')} for s in sessions]

    def settings(self):
        return {r['key']: json.loads(r['value']) for r in self.rows('SELECT * FROM settings')}

    def save_settings(self, settings):
        allowed = {'base_url', 'model', 'embedding_model', 'embedding_url'}
        with self.db:
            for key, value in settings.items():
                if key in allowed:
                    self.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, json.dumps(value)))

    def add_conversation(self, question, answer, citations):
        with self.db:
            self.db.execute('INSERT INTO conversations VALUES(?,?,?,?,?)', (uid(), question, answer, json.dumps(citations, ensure_ascii=False), now()))

    def conversations(self, limit=20):
        sql = 'SELECT * FROM conversations ORDER BY created_at DESC,rowid DESC'
        return [{**r, 'citations': json.loads(r['citations'])}
                for r in self.rows(sql + (' LIMIT ?' if limit is not None else ''), (limit,) if limit is not None else ())]

    def forget_conversations(self, document_id):
        for row in self.rows('SELECT id,citations FROM conversations'):
            if any(s.get('document_id') == document_id for s in json.loads(row['citations'])):
                self.db.execute('DELETE FROM conversations WHERE id=?', (row['id'],))

    def job(self, kind, payload):
        job_id = uid()
        with self.db:
            self.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)', (job_id, kind, json.dumps(payload), 'running', '', now()))
        return job_id

    def finish_job(self, job_id, error=''):
        with self.db:
            self.db.execute('UPDATE jobs SET status=?,error=? WHERE id=?', ('failed' if error else 'completed', error, job_id))

    def recover_jobs(self):
        with self.db:
            self.db.execute("UPDATE jobs SET status='failed',error='应用退出导致处理中断，可重新导入' WHERE status='running'")
