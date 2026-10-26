"""Anonymous public API fallback for Bilibili pages without usable initial state.

No cookies, browser credentials or access-control tokens are acquired here.
Only a complete public MP4 returned for the exact selected cid is admitted.
"""
import gzip
import http.client
import io
import json
import math
import re
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlencode, urlsplit

from .ranged_media import download_budget, download_ranges

RANGE_CHUNK_BYTES = 2 * 1024 * 1024
RANGE_THRESHOLD_BYTES = RANGE_CHUNK_BYTES


def validate_url(value, kind):
    if isinstance(value, str) and value.startswith('//'):
        value = 'https:' + value
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or '').lower()
        if kind == 'api':
            trusted = host == 'api.bilibili.com'
        elif kind == 'caption':
            trusted = any(host == suffix or host.endswith('.' + suffix) for suffix in ('hdslb.com', 'bilibili.com'))
        else:
            trusted = any(host == suffix or host.endswith('.' + suffix) for suffix in ('bilivideo.com', 'bilivideo.cn')) or bool(re.fullmatch(r'upos-[a-z0-9-]+\.akamaized\.net', host))
        if not trusted or parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('B站返回的公开资源地址无效，已停止读取') from None
    return value


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl, getattr(req, '_bili_kind', 'api'))
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected._bili_kind = getattr(req, '_bili_kind', 'api')
        return redirected


class _TransientPublicError(ValueError):
    """Sanitized transport failure eligible for metadata-only retries."""


class BilibiliPublic:
    def __init__(self, url, opener=None, observer=None):
        parsed = urlsplit(url)
        match = re.fullmatch(r'/video/(BV[A-Za-z0-9]{10})/?', parsed.path)
        if parsed.hostname != 'www.bilibili.com' or not match:
            raise ValueError('B站视频链接无效')
        self.bvid = match[1]
        self.page = int(parse_qs(parsed.query).get('p', ['1'])[0])
        self.url = url
        self.opener = opener or urllib.request.build_opener(SafeRedirect())
        self.metadata = None
        self.observer = observer

    def _emit(self, event, details):
        if self.observer is not None:
            try:
                self.observer(event, details)
            except Exception:
                pass

    def _open(self, url, kind, timeout=20, headers=None):
        url = validate_url(url, kind)
        req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0', 'Referer':self.url, 'Accept-Encoding':'identity', **(headers or {})})
        req._bili_kind = kind
        try:
            response = self.opener.open(req, timeout=timeout)
            validate_url(response.geturl(), kind)
            return response
        except urllib.error.HTTPError as exc:
            error = _TransientPublicError if exc.code == 429 or 500 <= exc.code <= 599 else ValueError
            exc.close()
            failure = error(f'B站公开接口返回 HTTP {exc.code}，请稍后重试或导入本地媒体')
            failure.status = exc.code
            raise failure from None
        except (urllib.error.URLError, OSError):
            raise _TransientPublicError('B站公开资源连接失败或超时，请稍后重试') from None

    def _json(self, url, kind='api'):
        limit = 4_000_000
        # Retry only bounded metadata GETs, never media bodies or API denial codes.
        # At most three 8-second socket timeouts plus 1.5 seconds backoff.
        for attempt in range(3):
            try:
                with self._open(url, kind, timeout=8) as response:
                    raw = response.read(limit + 1)
                break
            except (_TransientPublicError, OSError, http.client.IncompleteRead) as exc:
                if attempt == 2:
                    message = str(exc) if isinstance(exc, _TransientPublicError) else 'B站公开资源连接失败或超时，请稍后重试'
                    raise ValueError(message) from None
                time.sleep(0.5 * (attempt + 1))
        if len(raw) > limit:
            raise ValueError('B站公开元数据超过大小限制')
        if raw.startswith(b'\x1f\x8b'):
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
                raw = compressed.read(limit + 1)
            if len(raw) > limit:
                raise ValueError('B站公开元数据超过大小限制')
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ValueError('B站公开接口未返回有效元数据') from None
        if not isinstance(value, dict):
            raise ValueError('B站公开接口未返回有效元数据')
        if kind == 'api' and value.get('code') != 0:
            raise ValueError(f"B站公开接口拒绝访问（代码 {value.get('code')}），请稍后重试或导入本地媒体")
        return value.get('data') if kind == 'api' else value

    def info(self):
        pages = self._json('https://api.bilibili.com/x/player/pagelist?' + urlencode({'bvid':self.bvid}))
        selected = next((p for p in pages if isinstance(p, dict) and p.get('page') == self.page), None) if isinstance(pages, list) else None
        if not selected or not isinstance(selected.get('cid'), int) or selected['cid'] <= 0:
            raise ValueError('指定分 P 不存在或无法读取；未改为导入其他集')
        duration = float(selected.get('duration') or 0)
        if not math.isfinite(duration) or not 0 < duration <= 14400:
            raise ValueError('视频时长无效或超过 4 小时限制')
        try:
            player = self._json('https://api.bilibili.com/x/player/wbi/v2?' + urlencode({'bvid':self.bvid,'cid':selected['cid']}))
            tracks = (player.get('subtitle') or {}).get('subtitles') or []
        except ValueError:
            tracks = []
        if not isinstance(tracks, list):
            tracks = []
        self.metadata = {'cid':selected['cid'], 'duration':duration,
                         'title':f"{self.bvid} P{self.page} · {str(selected.get('part') or '视频')[:140]}",
                         'subtitles':sorted([s for s in tracks[:100] if isinstance(s, dict) and s.get('subtitle_url')],
                                            key=lambda s: ('zh' not in str(s.get('lan','')), bool(s.get('ai_type'))))}
        return self.metadata

    def caption(self, track):
        return json.dumps(self._json(track['subtitle_url'], 'caption'), ensure_ascii=False)

    def media(self):
        info = self.metadata or self.info()
        data = self._json('https://api.bilibili.com/x/player/playurl?' + urlencode({'bvid':self.bvid,'cid':info['cid'],'qn':16,'fnval':0,'fourk':0}))
        if not isinstance(data, dict):
            raise ValueError('B站没有返回可获取的公开视频')
        if data.get('is_preview'):
            raise ValueError('B站仅返回试看内容，未将其当作完整课程导入')
        rows = data.get('durl') or []
        if len(rows) != 1 or not isinstance(rows[0], dict):
            raise ValueError('B站未提供可直接获取的完整 MP4；可改用本地媒体')
        if float(rows[0].get('length') or 0) / 1000 < info['duration'] - 5:
            raise ValueError('B站仅返回部分或试看内容，未将其当作完整课程导入')
        return {**rows[0], 'url':validate_url(rows[0].get('url'), 'media')}

    def download(self, path, check, progress, limit):
        row = self.media()
        if int(row.get('size') or 0) > limit:
            raise ValueError('B站公开视频超过大小限制')
        urls = [validate_url(row['url'], 'media')]
        backups = row.get('backup_url')
        for candidate in backups[:8] if isinstance(backups, list) else []:
            if not isinstance(candidate, str):
                continue
            try:
                candidate = validate_url(candidate, 'media')
            except ValueError:
                continue
            if candidate not in urls:
                urls.append(candidate)
        partial = path.with_suffix(path.suffix + '.part')
        expected = int(row.get('size') or 0)
        budget = download_budget(expected)
        deadline = time.monotonic() + budget
        try:
            if expected > RANGE_THRESHOLD_BYTES:
                if download_ranges(urls, expected, partial, path, deadline, budget,
                                   RANGE_CHUNK_BYTES, check, progress, self._open,
                                   self._emit, _TransientPublicError):
                    return path
            for attempt in range(3):
                check()
                if time.monotonic() >= deadline:
                    raise ValueError('B站公开视频下载超时，可重试')
                size = 0
                total, status, reason = 0, 0, 'connection'
                details = {'attempt': attempt + 1, 'expected_bytes': expected,
                           'received_bytes': 0, 'status': 0}
                self._emit('download_attempt', dict(details))
                try:
                    # Restart at byte zero: never append an unverified CDN range.
                    # Public playurl provides equivalent CDN alternatives for this
                    # exact cid/rendition. Rotate on transient failure, retaining
                    # the shared deadline and full-size verification.
                    with self._open(urls[attempt % len(urls)], 'media', timeout=min(20, max(1, deadline - time.monotonic()))) as response, partial.open('wb') as writer:
                        status = getattr(response, 'status', 200)
                        if status != 200 or response.headers.get('Content-Range'):
                            raise ValueError('B站公开视频返回了非完整响应，已停止下载')
                        header = response.headers.get('Content-Length')
                        total = int(header) if header is not None else 0
                        details['status'] = status
                        if header is not None:
                            details['header_bytes'] = total
                        if total < 0:
                            raise ValueError('B站公开视频长度无效')
                        if total > limit:
                            raise ValueError('B站公开视频超过大小限制')
                        if expected and header is not None and total != expected:
                            reason = 'header_mismatch'
                            raise _TransientPublicError('B站公开视频下载不完整，可重试')
                        while True:
                            check()
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise ValueError('B站公开视频下载超时，可重试')
                            # HTTPResponse.read1 performs at most one raw read, so
                            # a trickling peer cannot hide inside read(chunk_size).
                            sock = getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
                            if sock is not None:
                                sock.settimeout(min(20, remaining))
                            try:
                                chunk = getattr(response, 'read1', response.read)(256 * 1024)
                            except (OSError, http.client.IncompleteRead) as exc:
                                raise _TransientPublicError('B站公开视频下载连接中断，可重试') from None
                            if not chunk:
                                break
                            size += len(chunk)
                            details['received_bytes'] = size
                            if size > limit:
                                raise ValueError('B站公开视频超过大小限制')
                            if (expected and size > expected) or (header is not None and size > total):
                                raise ValueError('B站公开视频长度不符，已停止下载')
                            writer.write(chunk)
                            progress(min(1, size / (expected or total)) if expected or total else 0)
                    if not size or (expected and size != expected) or (header is not None and size != total):
                        reason = 'early_eof'
                        raise _TransientPublicError('B站公开视频下载不完整，可重试')
                    check()
                    partial.replace(path)
                    progress(1)
                    self._emit('download_completed', dict(details))
                    return path
                except _TransientPublicError as exc:
                    details['status'] = getattr(exc, 'status', details['status'])
                    self._emit('download_retry', {**details, 'reason': reason})
                    check()
                    if attempt == 2:
                        raise ValueError('B站公开视频下载不完整或连接中断，可重试') from None
        finally:
            partial.unlink(missing_ok=True)
