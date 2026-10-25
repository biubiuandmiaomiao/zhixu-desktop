import json
import re
import time
from contextlib import contextmanager
import urllib.error
import urllib.parse
import urllib.request


def redact(text):
    text = re.sub(r'\b(?:sk|rk|m0)-[A-Za-z0-9_-]{12,}', '[已过滤密钥]', str(text))
    return re.sub(r'(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*\S+', r'\1=[已过滤]', text)


def parse_json(text):
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text)
    try:
        result = json.loads(text)
    except (ValueError, TypeError):
        raise ValueError('AI 返回的内容不是有效 JSON，请重试') from None
    if not isinstance(result, dict):
        raise ValueError('AI 返回格式应为 JSON 对象')
    return result


class Provider:
    def __init__(self, settings, api_key=''):
        self.settings = settings
        self.api_key = api_key
        # One Provider is created per backend operation; leave margin before IPC's 300 s limit.
        self._deadline = time.monotonic() + 240

    @contextmanager
    def budget(self, seconds):
        previous = self._deadline
        self._deadline = min(previous, time.monotonic() + seconds)
        try:
            yield
        finally:
            self._deadline = previous

    def _timeout(self):
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('AI 请求时间预算已用尽，已保存内容不受影响，请稍后重试')
        return min(100, remaining)

    def request(self, endpoint, payload, embedding=False):
        if not self.api_key:
            raise ValueError('请先在设置中填写 API Key 和模型，资料仍可在本地保存与搜索')
        base = self.settings.get('embedding_url' if embedding else 'base_url', '') or self.settings.get('base_url', '')
        parsed = urllib.parse.urlparse(base)
        local = parsed.hostname in ('localhost', '127.0.0.1', '::1')
        if not parsed.hostname or parsed.username or parsed.password or (parsed.scheme != 'https' and not (local and parsed.scheme == 'http')):
            raise ValueError('服务地址必须为 HTTPS，本机服务可使用 HTTP；地址不能包含账号密码')
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(base.rstrip('/') + endpoint, data=data,
                                     headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.api_key})
        # Never forward credentials across redirects.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=self._timeout()) as response:
                parts, size = [], 0
                while size < 5_000_000:
                    timeout = self._timeout()
                    # Recompute the socket timeout for each read, including trickling responses.
                    socket = getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
                    if socket is not None:
                        socket.settimeout(timeout)
                    chunk = response.read1(min(65536, 5_000_000 - size))
                    self._timeout()
                    if not chunk:
                        break
                    parts.append(chunk)
                    size += len(chunk)
                return json.loads(b''.join(parts))
        except urllib.error.HTTPError as exc:
            raise ValueError(f'AI 服务返回 HTTP {exc.code}，请检查地址、密钥、模型和额度') from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ValueError('AI 服务连接失败或超时，已保存的数据不会丢失，请稍后重试') from None

    def json(self, system, payload, images=None):
        model = self.settings.get('model', '')
        if not model:
            raise ValueError('请先在设置中填写对话模型名称')
        content = json.dumps(payload, ensure_ascii=False)
        if images:
            if len(images) > 6 or any(not isinstance(i, str) or len(i) > 2_000_000 or not re.fullmatch(r'data:image/(?:jpeg|png|webp);base64,[A-Za-z0-9+/=]+', i) for i in images):
                raise ValueError('图片必须为有界的本地截图数据')
            content = [{'type': 'text', 'text': content}] + [{'type': 'image_url', 'image_url': {'url': i}} for i in images]
        response = self.request('/chat/completions', {'model': model, 'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': content}], 'temperature': 0.75})
        try:
            content = response['choices'][0]['message']['content']
        except (KeyError, IndexError, TypeError):
            raise ValueError('AI 服务未返回有效回答') from None
        return parse_json(content)

    def embed(self, texts):
        self._timeout()
        model = self.settings.get('embedding_model', '')
        if not model:
            raise ValueError('未配置 Embedding 模型，当前使用本地关键词检索')
        response = self.request('/embeddings', {'model': model, 'input': texts}, embedding=True)
        self._timeout()
        try:
            vectors = [r['embedding'] for r in sorted(response['data'], key=lambda x: x['index'])]
            if len(vectors) != len(texts) or not vectors or not all(isinstance(v, list) and v for v in vectors):
                raise ValueError()
            return vectors
        except (KeyError, TypeError, ValueError):
            raise ValueError('Embedding 接口返回格式无效') from None
