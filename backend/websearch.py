"""Optional web search used only when the local knowledge base is thin, or when the
user explicitly asks the sidebar follow-up to search the web.

Results are untrusted reference data: they never override local sources and are
always labelled in the answer. The keyless built-in provider scrapes the Bing web
result page (the only search entry reachable from this network); the API providers
are used when a key is configured. No credentials are sent anywhere else.
"""
import base64
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from .mcpsearch import DEFAULT_COMMAND as MCP_DEFAULT_COMMAND, McpSearch, command_available
from .provider import redact

MAX_RESULTS = 6
RESPONSE_LIMIT = 1_000_000

PROVIDERS = {
    'mcp': {
        'label': 'MCP 搜索（open-websearch）',
        'mcp': True,
    },
    'builtin': {
        'label': '网页搜索（免密钥）',
        'keyless': True,
    },
    'bocha': {
        'label': '博查 Bocha',
        'url': 'https://api.bochaai.com/v1/web-search',
        'payload': lambda query, limit: {'query': query, 'count': limit, 'summary': True},
    },
    'tavily': {
        'label': 'Tavily',
        'url': 'https://api.tavily.com/search',
        'payload': lambda query, limit: {'query': query, 'max_results': limit, 'search_depth': 'basic',
                                         'include_answer': False},
    },
}
BUILTIN_SEARCH_URL = 'https://cn.bing.com/search'
BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}
_TAG = re.compile(r'<[^>]+>')
_RESULT_BLOCK = re.compile(r'<li class="b_algo".*?</li>', re.S)
_RESULT_LINK = re.compile(r'<h2[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_RESULT_TEXT = re.compile(r'<p[^>]*>(.*?)</p>', re.S)


def _plain(value):
    return html.unescape(_TAG.sub('', value or '')).strip()


def _decode_bing_href(href):
    """Bing wraps outbound links in /ck/a?...&u=a1<base64url>."""
    href = html.unescape(href or '')
    parsed = urllib.parse.urlsplit(href)
    if parsed.hostname and parsed.hostname.endswith('bing.com') and parsed.path == '/ck/a':
        encoded = urllib.parse.parse_qs(parsed.query).get('u', [''])[0]
        if encoded.startswith('a1'):
            encoded = encoded[2:]
        padding = '=' * (-len(encoded) % 4)
        try:
            return base64.urlsafe_b64decode(encoded + padding).decode('utf-8', 'replace')
        except (ValueError, TypeError):
            return ''
    return href


def parse_bing_results(markup, limit=MAX_RESULTS):
    """Extract {title,url,snippet} rows from a Bing result page."""
    rows = []
    for block in _RESULT_BLOCK.findall(markup or ''):
        match = _RESULT_LINK.search(block)
        if not match:
            continue
        url = _decode_bing_href(match.group(1))
        title = _plain(match.group(2))
        snippet_match = _RESULT_TEXT.search(block)
        snippet = _plain(snippet_match.group(1)) if snippet_match else ''
        parsed = urllib.parse.urlsplit(url) if url else None
        if not parsed or parsed.scheme not in ('http', 'https') or not parsed.hostname:
            continue
        if parsed.hostname.endswith('bing.com'):
            continue
        if not title or not snippet:
            continue
        if parsed.scheme == 'http':
            url = 'https://' + url[len('http://'):]
        rows.append({'title': title[:200], 'url': url, 'snippet': snippet[:800]})
        if len(rows) >= limit:
            break
    return rows


def provider_labels():
    return {key: value['label'] for key, value in PROVIDERS.items()}


def default_provider():
    # Prefer the locally installed MCP search server; fall back to keyless scraping.
    return 'mcp' if command_available(MCP_DEFAULT_COMMAND) else 'builtin'


class WebSearch:
    def __init__(self, provider, api_key, opener=None, mcp_command=None, mcp_args=None, mcp_engines=None):
        self.provider = provider if provider in PROVIDERS else ''
        self.api_key = api_key
        self.opener = opener or urllib.request.build_opener(_NoRedirect())
        self.mcp = McpSearch(mcp_command or MCP_DEFAULT_COMMAND, mcp_args, engines=mcp_engines)

    @property
    def keyless(self):
        return bool(PROVIDERS.get(self.provider, {}).get('keyless'))

    @property
    def configured(self):
        if self.provider == 'mcp':
            return self.mcp.configured
        return bool(self.provider) and (self.keyless or bool(self.api_key))

    def search(self, query, limit=MAX_RESULTS):
        if not self.configured:
            raise ValueError('未配置联网搜索服务')
        query = query.strip()
        if not query:
            return []
        limit = max(1, min(MAX_RESULTS, int(limit)))
        if self.provider == 'mcp':
            scored = [(row, _relevance_score(query, row)) for row in self.mcp.search(query, limit * 2)]
            scored = [(row, score) for row, score in scored if score > 0]
            scored.sort(key=lambda item: -item[1])
            if not scored:
                raise ValueError('MCP 搜索没有返回相关结果')
            return [{'title': redact(row['title'])[:200], 'url': row['url'],
                     'snippet': redact(row['snippet'])[:800]} for row, _ in scored[:limit]]
        if self.provider == 'builtin':
            return self._search_builtin(query, limit)
        spec = PROVIDERS[self.provider]
        body = json.dumps(spec['payload'](query, limit), ensure_ascii=False).encode('utf-8')
        request = urllib.request.Request(spec['url'], data=body, headers={
            'Content-Type': 'application/json', 'Accept': 'application/json',
            'Authorization': 'Bearer ' + self.api_key})
        try:
            with self.opener.open(request, timeout=12) as response:
                raw = response.read(RESPONSE_LIMIT + 1)
        except urllib.error.HTTPError as exc:
            exc.close()
            raise ValueError(f'联网搜索返回 HTTP {exc.code}，请检查搜索服务与密钥') from None
        except (urllib.error.URLError, OSError):
            raise ValueError('联网搜索连接失败或超时') from None
        if len(raw) > RESPONSE_LIMIT:
            raise ValueError('联网搜索结果超过大小限制')
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ValueError('联网搜索未返回有效结果') from None
        return self._rows(payload, limit)

    def _rows(self, payload, limit):
        if not isinstance(payload, dict):
            raise ValueError('联网搜索未返回有效结果')
        if payload.get('code') not in (None, 0, 200):
            raise ValueError('联网搜索被拒绝：' + redact(str(payload.get('msg') or payload.get('message') or ''))[:120])
        if self.provider == 'bocha':
            pages = ((payload.get('data') or {}).get('webPages') or {}).get('value')
            entries = pages if isinstance(pages, list) else []
            rows = [{'title': entry.get('name'), 'url': entry.get('url'),
                     'snippet': entry.get('summary') or entry.get('snippet')} for entry in entries
                    if isinstance(entry, dict)]
        else:
            entries = payload.get('results')
            entries = entries if isinstance(entries, list) else []
            rows = [{'title': entry.get('title'), 'url': entry.get('url'),
                     'snippet': entry.get('content')} for entry in entries if isinstance(entry, dict)]
        results = []
        for row in rows:
            url = row.get('url')
            if not isinstance(url, str):
                continue
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                continue
            title = redact(str(row.get('title') or parsed.hostname))[:200]
            snippet = redact(str(row.get('snippet') or ''))[:800].strip()
            if not snippet:
                continue
            # Keep the canonical https form so the desktop shell only opens web URLs.
            if parsed.scheme == 'http':
                url = 'https://' + url[len('http://'):]
            results.append({'title': title, 'url': url, 'snippet': snippet})
            if len(results) >= limit:
                break
        return results

    def _search_builtin(self, query, limit):
        """Keyless search through public result pages, with a relevance check.

        No single engine is dependable from this network: Bing serves degraded
        results without cookies, and Baidu intermittently answers with a
        verification page. Try each engine, keep the first whose rows actually
        contain the query's own words.
        """
        errors = []
        for name, engine in (('bing', _search_bing), ('so', _search_so)):
            try:
                rows = engine(self.opener, query, limit)
            except ValueError as exc:
                errors.append(f'{name}: {exc}')
                continue
            relevant = [row for row in rows if _relevant(query, row)][:limit]
            if relevant:
                return [{'title': redact(row['title'])[:200], 'url': row['url'],
                         'snippet': redact(row['snippet'])[:800]} for row in relevant]
            errors.append(f'{name}: 结果与问题不相关')
        raise ValueError('联网搜索没有返回可用结果（' + '；'.join(errors[:2]) + '）')


def _relevance_score(query, row):
    """How many of the question's own bigrams appear in the result."""
    haystack = ((row.get('title') or '') + ' ' + (row.get('snippet') or '')).lower()
    score = 0
    for token in re.findall(r'[a-z0-9_]+|[\u4e00-\u9fff]{2,}', query.lower()):
        if re.search(r'[\u4e00-\u9fff]', token):
            score += sum(1 for index in range(len(token) - 1) if token[index:index + 2] in haystack)
        elif token in haystack:
            score += 1
    return score


def _relevant(query, row):
    """A result is only usable when the question's own bigrams appear in it."""
    haystack = (row.get('title') or '') + ' ' + (row.get('snippet') or '')
    lowered = haystack.lower()
    tokens = [token for token in re.findall(r'[a-z0-9_]+|[\u4e00-\u9fff]{2,}', query.lower())]
    if not tokens:
        return True
    for token in tokens:
        if re.search(r'[\u4e00-\u9fff]', token):
            bigrams = [token[index:index + 2] for index in range(len(token) - 1)]
            if any(bigram in lowered for bigram in bigrams):
                return True
        elif token in lowered:
            return True
    return False


def _search_bing(opener, query, limit):
    url = 'https://cn.bing.com/search?' + urllib.parse.urlencode({'q': query, 'setlang': 'zh-CN'})
    request = urllib.request.Request(url, headers=BROWSER_HEADERS)
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read(RESPONSE_LIMIT + 1)
    except urllib.error.HTTPError as exc:
        exc.close()
        raise ValueError(f'HTTP {exc.code}') from None
    except (urllib.error.URLError, OSError):
        raise ValueError('连接失败') from None
    if len(raw) > RESPONSE_LIMIT:
        raise ValueError('响应超过大小限制')
    return parse_bing_results(raw.decode('utf-8', 'replace'), limit)


_SKIP_HOSTS = ('so.com', '360.cn', '360kan.com', 'hao.360.com', 'bing.com', 'baidu.com',
               'sogou.com', 'google.com', 'doubleclick.net')


def _search_so(opener, query, limit):
    """360 search: outbound links are exposed as data-mdurl attributes."""
    url = 'https://www.so.com/s?' + urllib.parse.urlencode({'q': query})
    request = urllib.request.Request(url, headers=BROWSER_HEADERS)
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read(RESPONSE_LIMIT + 1)
    except urllib.error.HTTPError as exc:
        exc.close()
        raise ValueError(f'HTTP {exc.code}') from None
    except (urllib.error.URLError, OSError):
        raise ValueError('连接失败') from None
    if len(raw) > RESPONSE_LIMIT:
        raise ValueError('响应超过大小限制')
    markup = raw.decode('utf-8', 'replace')
    markup = re.sub(r'<(style|script)[^>]*>.*?</\1>', ' ', markup, flags=re.S)
    rows = []
    for block in re.findall(r'<li class="res-list".*?</li>', markup, re.S):
        title_match = re.search(r'<h3[^>]*>(.*?)</h3>', block, re.S)
        if not title_match:
            continue
        title = _plain(title_match.group(1))
        urls = re.findall(r'data-mdurl="(https?://[^"]+)"', block)
        target = ''
        for candidate in urls:
            host = (urllib.parse.urlsplit(candidate).hostname or '').lower()
            if not any(host == skip or host.endswith('.' + skip) for skip in _SKIP_HOSTS):
                target = candidate
                break
        if not title or not target:
            continue
        body = _plain(block)[:600]
        snippet = body.replace(title, '', 1).strip()
        rows.append({'title': title[:200], 'url': target,
                     'snippet': re.sub(r'\s+', ' ', snippet)[:800]})
        if len(rows) >= limit:
            break
    return rows

    def _rows(self, payload, limit):
        if not isinstance(payload, dict):
            raise ValueError('联网搜索未返回有效结果')
        if payload.get('code') not in (None, 0, 200):
            raise ValueError('联网搜索被拒绝：' + redact(str(payload.get('msg') or payload.get('message') or ''))[:120])
        if self.provider == 'bocha':
            pages = ((payload.get('data') or {}).get('webPages') or {}).get('value')
            entries = pages if isinstance(pages, list) else []
            rows = [{'title': entry.get('name'), 'url': entry.get('url'),
                     'snippet': entry.get('summary') or entry.get('snippet')} for entry in entries
                    if isinstance(entry, dict)]
        else:
            entries = payload.get('results')
            entries = entries if isinstance(entries, list) else []
            rows = [{'title': entry.get('title'), 'url': entry.get('url'),
                     'snippet': entry.get('content')} for entry in entries if isinstance(entry, dict)]
        results = []
        for row in rows:
            url = row.get('url')
            if not isinstance(url, str):
                continue
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                continue
            title = redact(str(row.get('title') or parsed.hostname))[:200]
            snippet = redact(str(row.get('snippet') or ''))[:800].strip()
            if not snippet:
                continue
            # Keep the canonical https form so the desktop shell only opens web URLs.
            if parsed.scheme == 'http':
                url = 'https://' + url[len('http://'):]
            results.append({'title': title, 'url': url, 'snippet': snippet})
            if len(results) >= limit:
                break
        return results


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never let a search redirect move the request (and key) to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def web_source_rows(results, start_index, document_id=None):
    """Shape web results as citable sources for one answer."""
    rows = []
    for offset, result in enumerate(results or []):
        rows.append({'id': f'web:{start_index + offset}', 'document_id': document_id,
                     'title': '联网 · ' + result['title'], 'text': result['snippet'],
                     'url': result['url'], 'start': None, 'kind': 'web', 'retrieval': '联网'})
    return rows
