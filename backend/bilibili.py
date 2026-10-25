"""Anonymous public API fallback for Bilibili pages without usable initial state.

No cookies, browser credentials or access-control tokens are acquired here.
Only a complete public MP4 returned for the exact selected cid is admitted.
"""
import gzip
import io
import json
import math
import re
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlencode, urlsplit


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


class BilibiliPublic:
    def __init__(self, url, opener=None):
        parsed = urlsplit(url)
        match = re.fullmatch(r'/video/(BV[A-Za-z0-9]{10})/?', parsed.path)
        if parsed.hostname != 'www.bilibili.com' or not match:
            raise ValueError('B站视频链接无效')
        self.bvid = match[1]
        self.page = int(parse_qs(parsed.query).get('p', ['1'])[0])
        self.url = url
        self.opener = opener or urllib.request.build_opener(SafeRedirect())
        self.metadata = None

    def _open(self, url, kind):
        url = validate_url(url, kind)
        req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0', 'Referer':self.url, 'Accept-Encoding':'identity'})
        req._bili_kind = kind
        try:
            response = self.opener.open(req, timeout=20)
            validate_url(response.geturl(), kind)
            return response
        except urllib.error.HTTPError as exc:
            raise ValueError(f'B站公开接口返回 HTTP {exc.code}，请稍后重试或导入本地媒体') from None
        except (urllib.error.URLError, OSError):
            raise ValueError('B站公开资源连接失败或超时，请稍后重试') from None

    def _json(self, url, kind='api'):
        limit = 4_000_000
        with self._open(url, kind) as response:
            raw = response.read(limit + 1)
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
        partial = path.with_suffix(path.suffix + '.part')
        deadline, size = time.monotonic() + 600, 0
        try:
            check()
            with self._open(row['url'], 'media') as response, partial.open('wb') as writer:
                total = int(response.headers.get('Content-Length') or row.get('size') or 0)
                if total > limit:
                    raise ValueError('B站公开视频超过大小限制')
                while True:
                    check()
                    if time.monotonic() > deadline:
                        raise ValueError('B站公开视频下载超时，可重试')
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > limit:
                        raise ValueError('B站公开视频超过大小限制')
                    writer.write(chunk)
                    progress(min(1, size / total) if total else 0)
            if not size or (total and size != total):
                raise ValueError('B站公开视频下载不完整，可重试')
            check()
            partial.replace(path)
            progress(1)
            return path
        finally:
            partial.unlink(missing_ok=True)
