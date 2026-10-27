"""Optional web search used only when the local knowledge base is thin.

Results are untrusted reference data: they never override local sources and are
always labelled in the answer. Only the two configured providers' HTTPS
endpoints are contacted; no credentials are sent anywhere else.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from .provider import redact

MAX_RESULTS = 6
RESPONSE_LIMIT = 1_000_000

PROVIDERS = {
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


def provider_labels():
    return {key: value['label'] for key, value in PROVIDERS.items()}


class WebSearch:
    def __init__(self, provider, api_key, opener=None):
        self.provider = provider if provider in PROVIDERS else ''
        self.api_key = api_key
        self.opener = opener or urllib.request.build_opener(_NoRedirect())

    @property
    def configured(self):
        return bool(self.provider and self.api_key)

    def search(self, query, limit=MAX_RESULTS):
        if not self.configured:
            raise ValueError('未配置联网搜索服务')
        query = query.strip()
        if not query:
            return []
        limit = max(1, min(MAX_RESULTS, int(limit)))
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
