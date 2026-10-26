"""Durable bounded media jobs; each thread owns its SQLite connections.

The desktop must admit local paths with its native picker. Only registered,
managed JPEGs can be read back. ASR uses selectable local faster-whisper CPU/int8 models.
The optional transcriber is an external-model boundary for isolated tests.
"""
import base64
import html
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.client import HTTPException
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .store import Store, now, uid
from .knowledge import Knowledge
from .provider import redact

MAX_MEDIA_BYTES = 1024 * 1024 * 1024
MAX_DURATION_SECONDS = 4 * 60 * 60
MAX_SUBTITLE_BYTES = 4_000_000
MAX_TRANSCRIPT_CHARS = 1_500_000
MAX_ASSET_BYTES = 2_000_000
MEDIA_EXTENSIONS = frozenset(('.mp4', '.mkv', '.webm', '.mov', '.mp3', '.m4a', '.wav', '.flac', '.ogg'))
BILI_HOSTS = frozenset(('bilibili.com', 'www.bilibili.com', 'm.bilibili.com'))
YOUTUBE_HOSTS = frozenset(('youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be', 'www.youtu.be'))
DOUYIN_HOSTS = frozenset(('douyin.com', 'www.douyin.com'))
KUAISHOU_HOSTS = frozenset(('kuaishou.com', 'www.kuaishou.com'))
CAPTION_DOMAINS = ('bilibili.com', 'hdslb.com', 'youtube.com', 'googlevideo.com',
                   'douyin.com', 'douyincdn.com', 'douyinvod.com', 'bytecdn.cn',
                   'kuaishou.com', 'kwaicdn.com', 'ksapisrv.com', 'gifshow.com')
TERMINAL = frozenset(('completed', 'failed', 'cancelled'))
TEXT_SUBTITLE_CODECS = frozenset(('subrip', 'ass', 'ssa', 'webvtt', 'mov_text', 'text'))


class Cancelled(Exception):
    pass


def find_binary(name):
    """Packaged binaries take precedence over the machine's PATH."""
    executable = name + ('.exe' if os.name == 'nt' else '')
    roots = []
    if getattr(sys, '_MEIPASS', None):
        roots.append(Path(sys._MEIPASS))
    roots.extend((Path(sys.executable).parent, Path(__file__).resolve().parent.parent))
    for root in roots:
        for folder in (root / 'ffmpeg_bin', root / 'bin', root / 'ffmpeg' / 'bin', root):
            candidate = folder / executable
            if candidate.is_file():
                return str(candidate)
    return shutil.which(name)


def normalize_bilibili_url(value):
    """Retain video id and page only; never persist tracking/login parameters."""
    if not isinstance(value, str) or not value.strip() or len(value) > 8000:
        raise ValueError('请提供 B 站公开 BV 视频链接或 BV 号')
    value = value.strip()
    link = re.search(r'https?://[^\s<>“”"\u3000]+|(?<![A-Za-z0-9.@_-])(?:www\.|m\.)?bilibili\.com/[^\s<>“”"]+', value, re.I)
    if link:
        candidate = link.group(0).rstrip('，。；,;)）]')
        if not re.match(r'https?://', candidate, re.I):
            candidate = 'https://' + candidate
        try:
            parsed = urlsplit(candidate)
            if parsed.scheme not in ('http', 'https') or parsed.hostname not in BILI_HOSTS or parsed.username or parsed.password or parsed.port not in (None, 80, 443):
                raise ValueError()
            match = re.fullmatch(r'/video/(BV[A-Za-z0-9]{10})/?', parsed.path)
            if not match:
                raise ValueError()
            page = parse_qs(parsed.query).get('p', [''])[0]
            if page and (not page.isdigit() or not 1 <= int(page) <= 10000):
                raise ValueError()
            return 'https://www.bilibili.com/video/' + match.group(1) + ('?p=' + str(int(page)) if page else '')
        except (ValueError, TypeError):
            raise ValueError('仅支持 bilibili.com 上的公开 BV 视频链接') from None
    if '://' in value or '/' in value or '@' in value:
        raise ValueError('仅支持 bilibili.com 上的公开 BV 视频链接')
    match = re.search(r'(?<![A-Za-z0-9])(BV[A-Za-z0-9]{10})(?![A-Za-z0-9])', value)
    if not match:
        raise ValueError('请提供 B 站公开 BV 视频链接或 BV 号')
    return 'https://www.bilibili.com/video/' + match.group(1)


def normalize_video_url(value):
    """Only direct public videos on explicit HTTPS platform hosts are admitted."""
    if not isinstance(value, str) or not value.strip() or len(value) > 8000:
        raise ValueError('请提供公开的视频链接')
    match = re.search(r'https?://[^\s<>“”"\u3000]+', value, re.I)
    if not match:
        return normalize_bilibili_url(value)
    candidate = match.group(0).rstrip('，。；,;)）]')
    try:
        parsed = urlsplit(candidate)
        if parsed.hostname in BILI_HOSTS:
            return normalize_bilibili_url(candidate)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError()
        host, path = parsed.hostname, parsed.path
        if host in YOUTUBE_HOSTS:
            if host.endswith('youtu.be'):
                video = path.strip('/')
            elif path.rstrip('/') == '/watch':
                video = parse_qs(parsed.query).get('v', [''])[0]
            else:
                found = re.fullmatch(r'/(?:shorts|embed|live)/([A-Za-z0-9_-]{11})/?', path)
                video = found.group(1) if found else ''
            if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video):
                raise ValueError()
            return 'https://www.youtube.com/watch?v=' + video
        if host in DOUYIN_HOSTS and re.fullmatch(r'/video/\d{10,25}/?', path):
            return 'https://www.douyin.com' + path.rstrip('/')
        if host in KUAISHOU_HOSTS and re.fullmatch(r'/short-video/[A-Za-z0-9_-]{6,40}/?', path):
            return 'https://www.kuaishou.com' + path.rstrip('/')
    except (ValueError, TypeError):
        pass
    raise ValueError('仅支持 B站 BV、YouTube、抖音 /video/ 和快手 /short-video/ 的公开直达链接；不接受短链、播放列表或登录凭据')


def _options(value):
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - {'screenshots', 'language', 'title', 'generate_tutorial', 'asr_model'}:
        raise ValueError('媒体选项仅支持 screenshots、language、title、generate_tutorial 和 asr_model；不接受登录凭据')
    asr_model = value.get('asr_model', 'base')
    if not isinstance(asr_model, str) or asr_model not in ('tiny', 'base', 'small'):
        raise ValueError('ASR 模型仅支持 tiny、base 或 small')
    screenshots = value.get('screenshots', False)
    generate_tutorial = value.get('generate_tutorial', False)
    language = value.get('language', 'auto')
    title = value.get('title', '')
    if not isinstance(screenshots, bool) or not isinstance(generate_tutorial, bool) or not isinstance(language, str) or not re.fullmatch(r'auto|[a-z]{2,3}', language):
        raise ValueError('请提供有效的截图选项与转写语言')
    if not isinstance(title, str) or len(title.strip()) > 200:
        raise ValueError('媒体标题不得超过 200 字符')
    return {'screenshots': screenshots, 'language': language, 'title': title.strip(), 'generate_tutorial': generate_tutorial, 'asr_model': asr_model}


def _local_path(value):
    try:
        if not isinstance(value, (str, Path)) or '\x00' in str(value):
            raise ValueError()
        path = Path(value).expanduser().resolve(strict=True)
        if not path.is_file() or path.suffix.lower() not in MEDIA_EXTENSIONS:
            raise ValueError()
        if not 0 < path.stat().st_size <= MAX_MEDIA_BYTES:
            raise ValueError('媒体文件为空或超过 1 GiB 限制')
        return path
    except (OSError, RuntimeError):
        raise ValueError('媒体文件不存在、无法读取或路径无效') from None
    except ValueError as exc:
        if str(exc):
            raise
        raise ValueError('请选择有效的 MP4、MKV、WebM、MOV、MP3、M4A、WAV、FLAC 或 OGG 文件') from None


def _timestamp(seconds):
    value = int(seconds)
    return f'{value // 3600:02}:{value // 60 % 60:02}:{value % 60:02}'


def _subtitle_rows(text):
    text = text.lstrip('\ufeff \n\r')
    if text.startswith('{'):
        try:
            data = json.loads(text)
            return [{'text': str(r['content']).strip(), 'start': float(r['from'])}
                    for r in data.get('body', []) if r.get('content')]
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ValueError('公开视频字幕格式无效') from None
    rows = []
    pattern = r'((?:\d{2,}:)?\d{2}:\d{2}[.,]\d{3})\s*-->[^\n]*\n(.*?)(?=\n\s*\n|\Z)'
    for match in re.finditer(pattern, text, re.S):
        start = sum(float(part) * (60 ** i) for i, part in enumerate(reversed(match[1].replace(',', '.').split(':'))))
        content = html.unescape(re.sub(r'<[^>]+>', '', match[2])).strip()
        if content:
            rows.append({'text': content, 'start': start})
    return rows


class MediaJobs:
    def __init__(self, directory, transcriber=None, provider_factory=None):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.media_directory = self.directory / 'media'
        self.media_directory.mkdir(parents=True, exist_ok=True)
        self.media_directory = self.media_directory.resolve()
        self.db_path = self.directory / 'knowledge.sqlite3'
        self._transcriber, self._model = transcriber, None
        self._model_name = None
        self._provider_factory = provider_factory
        self._lock = threading.RLock()
        self._stop, self._wake = threading.Event(), threading.Event()
        self._cancelled = set()
        self._process, self._current = None, None
        initial = Store(self.directory)
        initial.close()
        with self._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS media_jobs(
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, source_name TEXT NOT NULL,
                    source_url TEXT NOT NULL, source_path TEXT NOT NULL, title TEXT NOT NULL,
                    status TEXT NOT NULL, stage TEXT NOT NULL, progress REAL NOT NULL,
                    error TEXT NOT NULL, retryable INTEGER NOT NULL,
                    document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
                    attempts INTEGER NOT NULL, options TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    document_ref TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS media_job_events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES media_jobs(id),
                    event TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS media_job_events_job ON media_job_events(job_id,id);
                CREATE TABLE IF NOT EXISTS media_files(
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES media_jobs(id),
                    path TEXT NOT NULL UNIQUE, source_name TEXT NOT NULL, source_url TEXT NOT NULL,
                    duration REAL, has_video INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS media_assets(
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    job_id TEXT NOT NULL REFERENCES media_jobs(id), path TEXT NOT NULL UNIQUE,
                    start REAL NOT NULL, caption TEXT NOT NULL);
            ''')
            if 'document_ref' not in {row['name'] for row in db.execute('PRAGMA table_info(media_jobs)')}:
                db.execute("ALTER TABLE media_jobs ADD COLUMN document_ref TEXT NOT NULL DEFAULT ''")
            db.execute("UPDATE media_jobs SET document_ref=document_id WHERE document_id IS NOT NULL AND document_ref=''")
            db.execute("UPDATE media_jobs SET status='failed',stage='interrupted',retryable=1,error=?,updated_at=? WHERE status IN ('queued','running')",
                       ('应用退出导致媒体处理中断，可点击重试', now()))
        self._worker = threading.Thread(target=self._run, name='zhixu-media', daemon=True)
        self._worker.start()

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def _require_open(self):
        if self._stop.is_set():
            raise ValueError('媒体任务管理器已关闭')

    def _job(self, row):
        result = dict(row)
        result.pop('source_path', None)
        result.pop('document_ref', None)
        result['options'] = _options(json.loads(result['options']))
        result['retryable'] = bool(result['retryable'])
        with self._connect() as db:
            events = db.execute('SELECT event,details,created_at FROM media_job_events WHERE job_id=? ORDER BY id DESC LIMIT 20', (result['id'],)).fetchall()
        result['events'] = [{'event': r['event'], 'details': json.loads(r['details']), 'created_at': r['created_at']} for r in reversed(events)]
        return result

    def _asr_event(self, job_id, event, model, language=None, probability=None, count=None):
        # Only typed, bounded ASR metadata is accepted; never exception text or URLs.
        if event not in ('asr_started', 'asr_completed', 'asr_model_failed') or not isinstance(model, str) or model not in ('tiny', 'base', 'small'):
            raise ValueError('无效的 ASR 诊断事件')
        if event == 'asr_completed' and (type(count) is not int or not 0 <= count <= 50000):
            raise ValueError('无效的 ASR 片段数')
        details = {'asr_model': model}
        if event == 'asr_completed':
            details.update(language=language if isinstance(language, str) and re.fullmatch(r'[a-z]{2,3}', language) else None,
                           language_probability=float(probability) if isinstance(probability, (int, float)) and math.isfinite(probability) and 0 <= probability <= 1 else None,
                           segment_count=count)
        with self._connect() as db:
            db.execute('INSERT INTO media_job_events(job_id,event,details,created_at) VALUES(?,?,?,?)', (job_id, event, json.dumps(details), now()))
            db.execute('DELETE FROM media_job_events WHERE job_id=? AND id NOT IN (SELECT id FROM media_job_events WHERE job_id=? ORDER BY id DESC LIMIT 20)', (job_id, job_id))

    def _download_event(self, job_id, event, details):
        # Downloader callbacks can supply only fixed enums and finite counters.
        allowed = {'attempt', 'expected_bytes', 'header_bytes', 'received_bytes', 'status', 'reason',
                   'range_start', 'range_end', 'committed_bytes', 'segment_attempt', 'request_count',
                   'retry_count', 'range_chunks', 'budget_seconds', 'elapsed_seconds'}
        if event not in ('download_attempt', 'download_retry', 'download_completed', 'download_failed') or not isinstance(details, dict) or set(details) - allowed:
            raise ValueError('无效的下载诊断事件')
        for key, value in details.items():
            if key == 'reason':
                if not isinstance(value, str) or value not in ('early_eof', 'header_mismatch', 'connection', 'deadline', 'request_limit', 'invalid_response', 'representation_changed'):
                    raise ValueError('无效的下载诊断原因')
            elif type(value) not in (int, float) or value < 0 or not math.isfinite(value) or (key == 'status' and type(value) is not int):
                raise ValueError('无效的下载诊断计数')
        with self._connect() as db:
            db.execute('INSERT INTO media_job_events(job_id,event,details,created_at) VALUES(?,?,?,?)', (job_id, event, json.dumps(details), now()))
            db.execute('DELETE FROM media_job_events WHERE job_id=? AND id NOT IN (SELECT id FROM media_job_events WHERE job_id=? ORDER BY id DESC LIMIT 20)', (job_id, job_id))

    def activity(self):
        # UI history is bounded; power protection must count the entire queue.
        with self._connect() as db:
            count = db.execute("SELECT COUNT(*) FROM media_jobs WHERE status IN ('queued','running')").fetchone()[0]
        return {'active': count > 0, 'count': count}

    def _provider_events(self, job_id, events):
        allowed = {'request', 'attempt', 'outcome', 'reason', 'status', 'received_bytes', 'elapsed_seconds'}
        for event in events[-6:]:
            if not isinstance(event, dict) or set(event) != allowed:
                raise ValueError('无效的模型传输诊断')
            if event['outcome'] not in ('retry', 'completed', 'failed') or event['reason'] not in (
                    'ok', 'http', 'timeout', 'dns', 'tls', 'connection_reset', 'connection', 'early_eof', 'deadline', 'invalid_response'):
                raise ValueError('无效的模型传输原因')
            if any(type(event[key]) not in (int, float) or not math.isfinite(event[key]) or event[key] < 0
                   for key in allowed - {'outcome', 'reason'}):
                raise ValueError('无效的模型传输计数')
            with self._connect() as db:
                db.execute('INSERT INTO media_job_events(job_id,event,details,created_at) VALUES(?,?,?,?)',
                           (job_id, 'ai_request', json.dumps(event), now()))
                db.execute('DELETE FROM media_job_events WHERE job_id=? AND id NOT IN (SELECT id FROM media_job_events WHERE job_id=? ORDER BY id DESC LIMIT 20)', (job_id, job_id))

    def status(self, job_id=None):
        with self._connect() as db:
            if job_id is None:
                return [self._job(r) for r in db.execute('SELECT * FROM media_jobs ORDER BY created_at DESC,rowid DESC LIMIT 200')]
            row = db.execute('SELECT * FROM media_jobs WHERE id=?', (job_id,)).fetchone()
            if not row:
                raise ValueError('媒体任务不存在')
            return self._job(row)

    def tutorial_running(self, document_id):
        # The UI's bounded history is not the authority for active-task guards.
        with self._connect() as db:
            rows = db.execute("SELECT options FROM media_jobs WHERE document_id=? AND status IN ('queued','running')",
                              (document_id,)).fetchall()
        return any(json.loads(row['options']).get('generate_tutorial') for row in rows)

    def mark_tutorial_completed(self, document_id):
        with self._lock, self._connect() as db:
            db.execute("UPDATE media_jobs SET status='completed',stage='tutorial_completed',progress=100,error='',retryable=0,updated_at=? "
                       "WHERE document_id=? AND status NOT IN ('queued','running')", (now(), document_id))

    def _enqueue(self, kind, source_name, source_url, source_path, options):
        with self._lock:
            self._require_open()
            job_id, date = uid(), now()
            with self._connect() as db:
                queued = db.execute("SELECT COUNT(*) FROM media_jobs WHERE status IN ('queued','running')").fetchone()[0]
                if queued >= 20:
                    raise ValueError('媒体任务队列已满，请等待现有任务完成')
                db.execute('''INSERT INTO media_jobs(id,kind,source_name,source_url,source_path,title,status,stage,
                              progress,error,retryable,document_id,attempts,options,created_at,updated_at)
                              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                           (job_id, kind, source_name, source_url, source_path,
                            options['title'] or source_name[:200], 'queued', 'queued', 0, '', 0,
                            None, 0, json.dumps(options, ensure_ascii=False), date, date))
            result = self.status(job_id)
            self._wake.set()
            return result

    def start_local(self, path, options=None):
        opts = _options(options)
        path = _local_path(path)
        return self._enqueue('local', path.name, '', str(path), opts)

    def start_video(self, url, options=None):
        opts = _options(options)
        canonical = normalize_video_url(url)
        host = urlsplit(canonical).hostname
        platform = 'bilibili' if host in BILI_HOSTS else 'youtube' if host in YOUTUBE_HOSTS else 'douyin' if host in DOUYIN_HOSTS else 'kuaishou'
        name = canonical.split('/')[-1].split('?')[0] if platform != 'youtube' else parse_qs(urlsplit(canonical).query)['v'][0]
        return self._enqueue(platform, name, canonical, '', opts)

    def retry(self, job_id):
        with self._lock:
            self._require_open()
            job = self.status(job_id)
            if job['status'] not in ('failed', 'cancelled') or not job['retryable']:
                raise ValueError('此媒体任务当前不可重试')
            if self._current == job_id:
                raise ValueError('取消操作仍在收尾，请稍后重试')
            self._cancelled.discard(job_id)
            with self._connect() as db:
                db.execute("UPDATE media_jobs SET status='queued',stage='queued',progress=0,error='',retryable=0,updated_at=? WHERE id=?", (now(), job_id))
            self._wake.set()
            return self.status(job_id)

    def cancel(self, job_id):
        with self._lock:
            job = self.status(job_id)
            if job['status'] in TERMINAL:
                return job
            self._cancelled.add(job_id)
            self._update(job_id, status='cancelled', stage='cancelled', error='用户取消媒体处理，可重试', retryable=1)
            if self._current == job_id:
                self._kill_process()
            self._wake.set()
            return self.status(job_id)

    def close(self):
        with self._lock:
            if not self._stop.is_set():
                self._stop.set()
                with self._connect() as db:
                    db.execute("UPDATE media_jobs SET status='cancelled',stage='cancelled',error=?,retryable=1,updated_at=? WHERE status IN ('queued','running')",
                               ('应用关闭，媒体任务已取消，可重试', now()))
                self._kill_process()
                self._wake.set()
        if self._worker is not threading.current_thread():
            self._worker.join(timeout=2)

    def _kill_process(self):
        process = self._process
        if process and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
            except OSError:
                pass

    def _check(self, job_id):
        if self._stop.is_set() or job_id in self._cancelled:
            raise Cancelled()

    def _update(self, job_id, **fields):
        allowed = {'status', 'stage', 'progress', 'error', 'retryable', 'document_id', 'title'}
        if not fields or set(fields) - allowed:
            raise ValueError('无效的媒体任务更新')
        fields['updated_at'] = now()
        with self._connect() as db:
            db.execute('UPDATE media_jobs SET ' + ','.join(key + '=?' for key in fields) + ' WHERE id=?', (*fields.values(), job_id))

    def _stage(self, job_id, stage, progress):
        with self._lock:
            self._check(job_id)
            self._update(job_id, stage=stage, progress=max(0, min(99, progress)))

    def _managed(self, path):
        path = Path(path)
        if not path.is_absolute():
            path = self.media_directory / path
        resolved = path.resolve()
        if not resolved.is_relative_to(self.media_directory) or resolved == self.media_directory:
            raise ValueError('媒体路径超出受管理目录')
        return resolved

    def _relative(self, path):
        return str(self._managed(path).relative_to(self.media_directory))

    def _run(self):
        store = Store(self.directory)
        try:
            while not self._stop.is_set():
                job = None
                with self._lock:
                    with self._connect() as db:
                        row = db.execute("SELECT * FROM media_jobs WHERE status='queued' ORDER BY created_at,rowid LIMIT 1").fetchone()
                        if row and not self._stop.is_set():
                            job = dict(row)
                            self._current = job['id']
                            db.execute("UPDATE media_jobs SET status='running',stage='starting',attempts=attempts+1,updated_at=? WHERE id=?", (now(), job['id']))
                if job is None:
                    self._wake.wait(.5)
                    self._wake.clear()
                    continue
                try:
                    self._process_job(store, job)
                except Cancelled:
                    pass
                except Exception as exc:
                    with self._lock:
                        if not self._stop.is_set() and job['id'] not in self._cancelled:
                            message = str(exc) if isinstance(exc, ValueError) else '媒体处理失败，请检查文件、公开访问权限与本地依赖后重试'
                            current = self.status(job['id'])
                            stage = 'tutorial_failed' if current['document_id'] and current['options'].get('generate_tutorial') else 'failed'
                            self._update(job['id'], status='failed', stage=stage, error=redact(message)[:1000], retryable=1)
                finally:
                    with self._lock:
                        self._current = None
        finally:
            store.close()

    def _copy_local(self, job, folder):
        self._stage(job['id'], 'copying', 5)
        source = _local_path(job['source_path'])
        target = self._managed(folder / ('input' + source.suffix.lower()))
        with source.open('rb') as reader, target.open('wb') as writer:
            copied = 0
            while True:
                self._check(job['id'])
                chunk = reader.read(1024 * 1024)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > MAX_MEDIA_BYTES:
                    raise ValueError('媒体文件超过 1 GiB 限制')
                writer.write(chunk)
        if not copied:
            raise ValueError('媒体文件为空')
        return target

    def _command(self, job_id, command, timeout=40):
        self._check(job_id)
        options = {'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE, 'stdin': subprocess.DEVNULL}
        if os.name == 'nt':
            options['creationflags'] = subprocess.CREATE_NO_WINDOW
        with self._lock:
            self._check(job_id)
            process = subprocess.Popen(command, **options)
            self._process = process
        deadline = time.monotonic() + timeout
        try:
            while True:
                self._check(job_id)
                if time.monotonic() > deadline:
                    raise ValueError('FFmpeg 处理超时，请检查媒体文件后重试')
                try:
                    stdout, stderr = process.communicate(timeout=.2)
                    break
                except subprocess.TimeoutExpired:
                    pass
            self._check(job_id)
            if process.returncode:
                raise ValueError('FFmpeg 无法读取此媒体，请检查格式或文件是否损坏')
            return stdout
        finally:
            with self._lock:
                if process.poll() is None:
                    self._kill_process()
                self._process = None

    def _probe(self, job_id, path):
        self._stage(job_id, 'probing', 15)
        ffprobe, ffmpeg = find_binary('ffprobe'), find_binary('ffmpeg')
        if not ffprobe or not ffmpeg:
            raise ValueError('缺少 FFmpeg/ffprobe，请安装或修复本地媒体依赖后重试')
        raw = self._command(job_id, [ffprobe, '-v', 'error', '-protocol_whitelist', 'file,pipe',
                                    '-show_entries', 'format=duration:stream=codec_type', '-of', 'json', str(path)])
        try:
            result = json.loads(raw)
            duration = float(result.get('format', {}).get('duration', 0))
            kinds = {s.get('codec_type') for s in result.get('streams', [])}
        except (ValueError, TypeError, AttributeError):
            raise ValueError('无法读取媒体时长，请检查格式或文件是否损坏') from None
        if not math.isfinite(duration) or not 0 < duration <= MAX_DURATION_SECONDS:
            raise ValueError('媒体时长无效或超过 4 小时限制，请按章节拆分')
        if not kinds.intersection({'audio', 'video'}):
            raise ValueError('媒体中没有可读取的音视频轨道')
        return duration, 'video' in kinds, 'audio' in kinds

    def _register_file(self, job, path, duration, has_video):
        relative = self._relative(path)
        with self._connect() as db:
            db.execute('INSERT OR REPLACE INTO media_files VALUES(?,?,?,?,?,?,?)',
                       (uid(), job['id'], relative, job['source_name'], job['source_url'], duration, int(has_video)))

    def _embedded_subtitles(self, job_id, path, folder, duration, language):
        """Prefer actual container text tracks; bitmap captions need ASR.

        FFmpeg converts supported text codecs to bounded temporary SRT. No
        arbitrary attachment/sidecar is opened, and temporary text is removed.
        """
        self._stage(job_id, 'subtitles', 20)
        raw = self._command(job_id, [find_binary('ffprobe'), '-v', 'error',
                                    '-protocol_whitelist', 'file,pipe', '-select_streams', 's',
                                    '-show_entries', 'stream=index,codec_name:stream_tags=language',
                                    '-of', 'json', str(path)])
        try:
            streams = [stream for stream in json.loads(raw).get('streams', [])
                       if stream.get('codec_name') in TEXT_SUBTITLE_CODECS
                       and isinstance(stream.get('index'), int) and stream['index'] >= 0]
        except (ValueError, TypeError, AttributeError):
            return None
        preferred = {'zh', 'zho', 'chi'} if language in ('auto', 'zh') else {language}
        streams.sort(key=lambda stream: (str(stream.get('tags', {}).get('language', '')).lower() not in preferred,
                                         stream['index']))
        target = self._managed(folder / 'embedded-subtitle.srt')
        try:
            for stream in streams[:10]:
                self._check(job_id)
                try:
                    self._command(job_id, [find_binary('ffmpeg'), '-nostdin', '-v', 'error',
                                           '-protocol_whitelist', 'file,pipe', '-copyts', '-i', str(path),
                                           '-map', '0:' + str(stream['index']), '-vn', '-an',
                                           '-c:s', 'srt', '-fs', str(MAX_SUBTITLE_BYTES + 1),
                                           '-f', 'srt', '-y', str(target)])
                    if not target.is_file() or not 0 < target.stat().st_size <= MAX_SUBTITLE_BYTES:
                        continue
                    with target.open('rb') as source:
                        text = source.read(MAX_SUBTITLE_BYTES + 1).decode('utf-8-sig')
                    rows = _subtitle_rows(text)
                    if rows:
                        return self._rows(rows, duration)
                except (UnicodeError, ValueError):
                    # Unreadable/corrupt text tracks do not suppress real ASR.
                    continue
                finally:
                    target.unlink(missing_ok=True)
            return None
        finally:
            target.unlink(missing_ok=True)

    def _existing_file(self, job_id):
        with self._connect() as db:
            rows = db.execute('SELECT path FROM media_files WHERE job_id=? ORDER BY rowid DESC', (job_id,)).fetchall()
        for row in rows:
            path = self._managed(row['path'])
            if path.suffix.lower() in MEDIA_EXTENSIONS and path.is_file() and 0 < path.stat().st_size <= MAX_MEDIA_BYTES:
                return path
        return None

    def _transcribe(self, job_id, path, language, duration):
        model_name = self.status(job_id)['options']['asr_model']
        self._asr_event(job_id, 'asr_started', model_name)
        self._stage(job_id, 'transcribing', 35)
        if self._transcriber:
            return self._transcriber(str(path), language)
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ValueError(f'缺少 faster-whisper 本地转写依赖，无法使用 {model_name} 模型；首次使用需下载模型，请修复安装后重试') from None
        if self._model is None or self._model_name != model_name:
            self._stage(job_id, 'loading_model', 30)
            try:
                self._model = None
                self._model_name = None
                self._model = WhisperModel(model_name, device='cpu', compute_type='int8',
                                           download_root=str(self.directory / 'models'),
                                           cpu_threads=min(4, os.cpu_count() or 1))
                self._model_name = model_name
            except Exception:
                self._asr_event(job_id, 'asr_model_failed', model_name)
                raise ValueError(f'本地 Whisper {model_name} 模型未能加载；首次使用需下载到数据目录 models，请检查网络后重试') from None
        self._stage(job_id, 'transcribing', 35)
        try:
            segments, info = self._model.transcribe(str(path), language=None if language == 'auto' else language,
                                                vad_filter=True, beam_size=3)
            result = []
            for segment in segments:
                self._check(job_id)
                if len(result) >= 50000:
                    raise ValueError('转写片段过多，请按章节拆分媒体')
                result.append({'start': segment.start, 'text': segment.text})
                self._stage(job_id, 'transcribing', 35 + min(45, 45 * float(segment.start) / duration))
            self._asr_event(job_id, 'asr_completed', model_name, getattr(info, 'language', None),
                            getattr(info, 'language_probability', None), len(result))
            return result
        except Cancelled:
            raise
        except ValueError:
            raise
        except Exception:
            raise ValueError('本地 Whisper 转写失败，请检查媒体与模型后重试') from None

    def _rows(self, raw, duration=None):
        rows, size = [], 0
        try:
            for row in raw:
                start, text = float(row['start']), row['text']
                if not isinstance(text, str):
                    raise ValueError()
                text = text.strip()
                if not text:
                    continue
                if not math.isfinite(start) or start < 0 or start > MAX_DURATION_SECONDS or (duration and start > duration + .5):
                    raise ValueError()
                if rows and start < rows[-1]['start']:
                    raise ValueError()
                size += len(text)
                if size > MAX_TRANSCRIPT_CHARS or len(rows) >= 50000:
                    raise ValueError('转写内容过长，请按章节拆分媒体')
                rows.append({'start': start, 'text': text})
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ValueError) and str(exc):
                raise
            raise ValueError('转写文本或时间点无效，未保存资料') from None
        if not rows:
            raise ValueError('没有识别到有效语音或字幕，未保存空白资料；可检查语言后重试')
        return rows

    def _subtitle_url(self, value):
        try:
            parsed = urlsplit(value)
            host = parsed.hostname or ''
            trusted = any(host == domain or host.endswith('.' + domain) for domain in CAPTION_DOMAINS)
            if not trusted or parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443):
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('公开视频字幕地址不受信任，已停止读取') from None
        return value

    def _public_video(self, job, options, folder):
        self._stage(job['id'], 'subtitles', 5)
        try:
            import yt_dlp
        except ImportError:
            raise ValueError('缺少 yt-dlp 公开视频依赖，请修复安装后重试') from None
        try:
            from yt_dlp.networking.exceptions import RequestError
            recoverable_caption_errors = (OSError, HTTPException, RequestError)
        except ImportError:
            recoverable_caption_errors = (OSError, HTTPException)
        class Quiet:
            def debug(self, msg):
                pass
            def warning(self, msg):
                pass
            def error(self, msg):
                pass
        base_options = {'quiet': True, 'no_warnings': True, 'noplaylist': True,
                        'socket_timeout': 20, 'retries': 1, 'extractor_retries': 1,
                        'skip_download': True, 'logger': Quiet(), 'nocheckcertificate': False,
                        'writesubtitles': True, 'writeautomaticsub': True}
        try:
            with yt_dlp.YoutubeDL(base_options) as ydl:
                info = ydl.extract_info(job['source_url'], download=False)
                self._check(job['id'])
                if info and info.get('entries'):
                    info = next(iter(info['entries']), None)
                if not isinstance(info, dict):
                    raise ValueError('未能读取公开视频信息，视频可能需要登录或已失效')
                if info.get('is_live') or info.get('live_status') == 'is_live':
                    raise ValueError('暂不支持直播，请选择已完成的公开视频')
                duration = info.get('duration')
                if duration and (not math.isfinite(float(duration)) or float(duration) > MAX_DURATION_SECONDS):
                    raise ValueError('媒体超过 4 小时限制，请按章节拆分')
                title = options['title'] or str(info.get('title') or job['source_name'])[:200]
                self._update(job['id'], title=title)
                subtitles = {**(info.get('automatic_captions') or {}), **(info.get('subtitles') or {})}
                languages = sorted(subtitles, key=lambda language: (not language.startswith('zh'), language))
                candidates = [caption for language in languages for caption in subtitles[language]
                              if caption.get('ext') in ('json', 'srt', 'vtt')]
                rows = None
                for candidate in candidates[:10]:
                    self._check(job['id'])
                    inline = isinstance(candidate.get('data'), str)
                    # Admission remains fail-closed. Only transient transport
                    # and read errors advance to another public caption/ASR.
                    url = None if inline else self._subtitle_url(candidate.get('url', ''))
                    try:
                        if inline:
                            text = candidate['data'].encode('utf-8')
                        else:
                            with ydl.urlopen(url) as response:
                                final_url = response.geturl() if hasattr(response, 'geturl') else url
                                self._subtitle_url(final_url)
                                text = response.read(MAX_SUBTITLE_BYTES + 1)
                    except (*recoverable_caption_errors, UnicodeError):
                        continue
                    if len(text) > MAX_SUBTITLE_BYTES:
                        raise ValueError('公开视频字幕超过大小限制')
                    try:
                        parsed = _subtitle_rows(text.decode('utf-8-sig'))
                        if parsed:
                            rows = self._rows(parsed, float(duration) if duration else None)
                            break
                    except (UnicodeError, ValueError):
                        continue
            path = None
            if rows is None or options['screenshots']:
                path = self._existing_file(job['id']) or self._download(job, options, folder, base_options, yt_dlp)
            return title, rows, path
        except (Cancelled, ValueError):
            raise
        except Exception:
            if job['kind'] == 'bilibili':
                return self._bilibili_public(job, options, folder)
            raise ValueError('获取公开视频失败，可能需要登录或视频不可访问；仅支持无需登录的公开内容，请稍后重试或选择本地媒体') from None

    def _bilibili_public(self, job, options, folder):
        # Bilibili sometimes serves a shell page without usable initial state.
        # Anonymous APIs still identify the exact cid and may allow a public MP4.
        from .bilibili import BilibiliPublic
        self._check(job['id'])
        client = BilibiliPublic(job['source_url'], observer=lambda event, details: self._download_event(job['id'], event, details))
        info = client.info()
        self._check(job['id'])
        title = options['title'] or info['title'][:200]
        self._update(job['id'], title=title)
        rows = None
        for track in info['subtitles'][:10]:
            self._check(job['id'])
            self._subtitle_url('https:' + track['subtitle_url'] if track['subtitle_url'].startswith('//') else track['subtitle_url'])
            try:
                parsed = _subtitle_rows(client.caption(track))
                if parsed:
                    rows = self._rows(parsed, info['duration'])
                    break
            except (ValueError, OSError):
                continue
        path = None
        if rows is None or options['screenshots']:
            path = self._existing_file(job['id'])
            if path is None:
                self._stage(job['id'], 'downloading', 20)
                path = client.download(self._managed(folder / 'public.mp4'),
                                       lambda: self._check(job['id']),
                                       lambda value: self._stage(job['id'], 'downloading', 20 + value * 10),
                                       MAX_MEDIA_BYTES)
        return title, rows, path

    def _download(self, job, options, folder, base_options, yt_dlp):
        if not find_binary('ffmpeg') or not find_binary('ffprobe'):
            raise ValueError('缺少 FFmpeg/ffprobe，请修复本地媒体依赖后重试')
        self._stage(job['id'], 'downloading', 20)
        last_report = [0.0]
        def progress(data):
            self._check(job['id'])
            downloaded = data.get('downloaded_bytes') or 0
            total = data.get('total_bytes') or data.get('total_bytes_estimate') or 0
            if downloaded > MAX_MEDIA_BYTES or total > MAX_MEDIA_BYTES:
                raise ValueError('公开视频超过 1 GiB 限制')
            if time.monotonic() - last_report[0] > .5:
                self._stage(job['id'], 'downloading', 20 + (10 * downloaded / total if total else 0))
                last_report[0] = time.monotonic()
        # A single native format avoids unmanaged FFmpeg merging subprocesses.
        download_options = {**base_options, 'skip_download': False,
                            'writesubtitles': False, 'writeautomaticsub': False,
                            'outtmpl': str(self._managed(folder / 'download.%(ext)s')),
                            'format': 'best[ext=mp4]/best' if options['screenshots'] else 'bestaudio[ext=m4a]/bestaudio/best',
                            'max_filesize': MAX_MEDIA_BYTES, 'fixup': 'never',
                            'progress_hooks': [progress], 'postprocessors': [],
                            'external_downloader': 'native'}
        with yt_dlp.YoutubeDL(download_options) as ydl:
            info = ydl.extract_info(job['source_url'], download=True)
            self._check(job['id'])
            if info and info.get('entries'):
                info = next(iter(info['entries']), None)
            if not isinstance(info, dict):
                raise ValueError('公开视频下载未完成')
            requested = info.get('requested_downloads') or []
            filename = next((r.get('filepath') for r in requested if r.get('filepath')), None) or info.get('_filename') or ydl.prepare_filename(info)
            path = self._managed(filename)
            if not path.is_file() or path.suffix.lower() not in MEDIA_EXTENSIONS or not 0 < path.stat().st_size <= MAX_MEDIA_BYTES:
                raise ValueError('公开视频下载未完成或超过大小限制')
            return path

    def _screenshots(self, job_id, path, rows, duration, folder):
        self._stage(job_id, 'screenshots', 85)
        count = min(6, len(rows))
        positions = sorted({round(i * (len(rows) - 1) / max(1, count - 1)) for i in range(count)})
        frames = []
        for index in positions:
            row = rows[index]
            if row['start'] >= duration:
                continue
            self._check(job_id)
            target = self._managed(folder / f'frame-{len(frames) + 1}.jpg')
            self._command(job_id, [find_binary('ffmpeg'), '-nostdin', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-ss', str(row['start']),
                                   '-i', str(path), '-frames:v', '1', '-vf', 'scale=960:-2',
                                   '-q:v', '4', '-y', str(target)])
            if not target.is_file() or not 0 < target.stat().st_size <= MAX_ASSET_BYTES:
                raise ValueError('未能提取有效截图，请关闭截图选项后重试')
            frames.append({'path': self._relative(target), 'start': row['start'], 'caption': row['text'][:200]})
        return frames

    def _process_job(self, store, job):
        job_id = job['id']
        options = json.loads(job['options'])
        # A tutorial failure/cancellation retains its imported source. Retry only generation.
        if job['document_id'] and options.get('generate_tutorial'):
            self._generate_tutorial(store, job, options)
            return
        folder = self._managed(job_id)
        folder.mkdir(parents=True, exist_ok=True)
        rows, frames, path = None, [], None
        title = options['title'] or job['title']
        if job['kind'] == 'local':
            path = self._existing_file(job_id) or self._copy_local(job, folder)
        else:
            title, rows, path = self._public_video(job, options, folder)
        duration, has_video = None, False
        if path:
            duration, has_video, has_audio = self._probe(job_id, path)
            self._register_file(job, path, duration, has_video)
            if rows is None:
                rows = self._embedded_subtitles(job_id, path, folder, duration, options['language'])
            had_subtitles = rows is not None
            if rows is None:
                if not has_audio:
                    raise ValueError('此媒体没有音轨，无法转写；请选择含语音的视频或导入字幕')
                rows = self._rows(self._transcribe(job_id, path, options['language'], duration), duration)
        else:
            rows = self._rows(rows)
            had_subtitles = True
        kind = 'subtitle' if had_subtitles else 'media'
        if options['screenshots']:
            if not has_video:
                raise ValueError('截图需要视频轨道；音频文件请关闭截图选项后重试')
            frames = self._screenshots(job_id, path, rows, duration, folder)
        source = '来源：本地媒体 ' + job['source_name'] if job['kind'] == 'local' else '来源：' + job['source_url']
        content = source + '\n\n' + '\n\n'.join('[' + _timestamp(row['start']) + '] ' + row['text'] for row in rows)
        self._stage(job_id, 'saving', 95)
        # Cancellation and the authoritative save are serialized.
        with self._lock:
            self._check(job_id)
            def completed(document_id):
                for frame in frames:
                    store.db.execute('INSERT INTO media_assets VALUES(?,?,?,?,?,?)',
                                     (uid(), document_id, job_id, frame['path'], frame['start'], frame['caption']))
                    # File ownership survives canonical asset-row cascade so
                    # cleanup also works after Store.delete_document().
                    store.db.execute('INSERT OR REPLACE INTO media_files VALUES(?,?,?,?,?,?,?)',
                                     (uid(), job_id, frame['path'], Path(frame['path']).name,
                                      job['source_url'], None, 0))
                automatic = options.get('generate_tutorial', False)
                store.db.execute("UPDATE media_jobs SET status=?,stage=?,progress=?,error='',retryable=0,document_id=?,document_ref=?,title=?,updated_at=? WHERE id=?",
                                 ('running' if automatic else 'completed', 'generating_tutorial' if automatic else 'completed',
                                  96 if automatic else 100, document_id, document_id, title, now(), job_id))
            document = store.add_document(title, content, job['source_url'], kind, segments=rows, on_saved=completed)
            job['document_id'] = document['id']
        if options.get('generate_tutorial'):
            self._generate_tutorial(store, job, options)

    def _generate_tutorial(self, store, job, options):
        job_id, document_id = job['id'], job['document_id']
        self._stage(job_id, 'generating_tutorial', 96)

        @contextmanager
        def commit():
            # Network calls never hold this lock. A late result cannot win against
            # cancellation/deletion, or overwrite a source edited while it was in flight.
            with self._lock:
                self._check(job_id)
                with store.db:
                    store.db.execute('BEGIN IMMEDIATE')
                    yield
                self._update(job_id, status='completed', stage='tutorial_completed', progress=100,
                             error='', retryable=0)

        try:
            if self._provider_factory is None:
                raise ValueError('请在模型与设置中配置对话模型和 API Key')
            frames = self.assets(document_id) if options.get('screenshots') else []
            provider = self._provider_factory(store)
            provider.check_request = lambda: self._check(job_id)
            try:
                Knowledge(store, provider, None).tutorial(document_id, images=frames,
                                                         use_images=bool(frames), save_guard=commit,
                                                         check_generation=lambda: self._check(job_id))
            finally:
                self._provider_events(job_id, getattr(provider, 'request_events', []))
        except Cancelled:
            raise
        except Exception as exc:
            message = str(exc) if isinstance(exc, ValueError) else '模型服务暂不可用，请检查设置后重试'
            raise ValueError('原文已保存，中文教程尚未生成：' + redact(message)) from None

    def delete_document(self, document_id):
        """Remove registrations belonging to a deleted document, before/after Store.

        The private document_ref survives the document FK's ON DELETE SET NULL,
        allowing cleanup after canonical deletion without retaining its content.
        Unregistered files, models and the original selected file are untouched.
        """
        with self._lock:
            with self._connect() as db:
                job_ids = [row['id'] for row in db.execute(
                    'SELECT id FROM media_jobs WHERE document_id=? OR document_ref=?', (document_id, document_id))]
                if not job_ids:
                    return {'jobs': 0, 'files_removed': 0}
                placeholders = ','.join('?' for _ in job_ids)
                registrations = db.execute(
                    f'SELECT job_id,path FROM media_files WHERE job_id IN ({placeholders}) UNION '
                    f'SELECT job_id,path FROM media_assets WHERE job_id IN ({placeholders})', (*job_ids, *job_ids)).fetchall()
            owned = []
            for row in registrations:
                path = self._managed(row['path'])
                folder = self._managed(row['job_id'])
                if not path.is_relative_to(folder) or path == folder or path.suffix.lower() not in (MEDIA_EXTENSIONS | {'.jpg', '.jpeg'}):
                    raise ValueError('媒体清理路径不属于此任务，已停止删除')
                if path.exists() and not path.is_file():
                    raise ValueError('媒体清理对象不是受管理文件，已停止删除')
                owned.append(path)
            # Invalidate retry before touching files, including when an OS file
            # lock prevents cleanup and the caller later repeats this method.
            with self._connect() as db:
                db.execute(f"UPDATE media_jobs SET status='cancelled',stage='deleted',document_id=NULL,retryable=0,error=?,updated_at=? WHERE id IN ({placeholders})",
                           ('来源资料已删除', now(), *job_ids))
            self._cancelled.update(job_ids)
            removed = 0
            try:
                for path in set(owned):
                    if path.exists():
                        path.unlink()
                        removed += 1
            except OSError:
                raise ValueError('媒体文件正在使用，部分受管理文件尚未清理，请稍后重试删除') from None
            with self._connect() as db:
                db.execute(f'DELETE FROM media_assets WHERE job_id IN ({placeholders})', job_ids)
                db.execute(f'DELETE FROM media_files WHERE job_id IN ({placeholders})', job_ids)
            for job_id in job_ids:
                try:
                    self._managed(job_id).rmdir()
                except OSError:
                    pass
            return {'jobs': len(job_ids), 'files_removed': removed}

    def assets(self, document_id):
        with self._connect() as db:
            rows = db.execute('''SELECT a.* FROM media_assets a JOIN documents d ON d.id=a.document_id
                                 WHERE a.document_id=? AND d.workspace='default' ORDER BY a.start,a.rowid''', (document_id,)).fetchall()
        result = []
        for row in rows[:6]:
            path = self._managed(row['path'])
            if path.suffix.lower() not in ('.jpg', '.jpeg') or not path.is_file() or path.stat().st_size > MAX_ASSET_BYTES:
                raise ValueError('受管理截图已失效或格式不正确')
            data = path.read_bytes()
            if not data.startswith(b'\xff\xd8\xff'):
                raise ValueError('受管理截图不是有效 JPEG')
            result.append({'id': row['id'], 'document_id': row['document_id'], 'job_id': row['job_id'],
                           'start': row['start'], 'caption': row['caption'], 'mime_type': 'image/jpeg',
                           'data_url': 'data:image/jpeg;base64,' + base64.b64encode(data).decode('ascii')})
        return result
