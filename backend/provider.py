import json
import re
import time
import socket
import ssl
import http.client
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


class AIResponseError(ValueError):
    """Model output rejected without losing the draft or safe diagnostics."""
    def __init__(self, content, finish_reason, parse_error=None):
        truncated = finish_reason == 'length'
        message = 'AI 输出达到长度上限，JSON 可能不完整' if truncated else 'AI 返回的内容不是有效 JSON'
        super().__init__(message)
        self.raw_result = {'response_text': content if isinstance(content, str) else '',
                           'finish_reason': finish_reason if finish_reason in ('stop', 'length', 'content_filter', 'tool_calls') else 'unknown'}
        self.errors = [{'code': 'output_truncated' if truncated else 'malformed_json', 'message': message}]
        if isinstance(parse_error, json.JSONDecodeError):
            self.errors[0].update(line=parse_error.lineno, column=parse_error.colno, position=parse_error.pos)


class AIRequestError(ValueError):
    def __init__(self, message, events):
        super().__init__(message)
        self.raw_result = {'transport_attempts': [dict(event) for event in events]}
        self.errors = [{'code': 'request_failed', 'message': message}]


class Provider:
    def __init__(self, settings, api_key=''):
        self.settings = settings
        self.api_key = api_key
        # One Provider is created per backend operation; leave margin before IPC's 300 s limit.
        self._deadline = time.monotonic() + 240
        self.request_events = []
        self.check_request = None
        self._request_count = 0

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
        self._request_count += 1
        events = []
        for attempt in (1, 2, 3):
            if self.check_request:
                self.check_request()
            started, size, status, delay = time.monotonic(), 0, 0, .5 * attempt
            reason, retryable = '', False
            try:
                with urllib.request.build_opener(NoRedirect).open(req, timeout=self._timeout()) as response:
                    parts = []
                    while size < 5_000_000:
                        if self.check_request:
                            self.check_request()
                        timeout = self._timeout()
                        sock = getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
                        if sock is not None:
                            sock.settimeout(timeout)
                        chunk = response.read1(min(65536, 5_000_000 - size))
                        self._timeout()
                        if not chunk:
                            break
                        parts.append(chunk)
                        size += len(chunk)
                    length = response.headers.get('Content-Length')
                    if length and length.isdigit() and size != int(length):
                        reason = 'early_eof'
                        raise http.client.IncompleteRead(b'', max(0, int(length) - size))
                    if size >= 5_000_000:
                        raise ValueError('AI 服务响应超过大小限制')
                    result = json.loads(b''.join(parts))
                event = {'request': self._request_count, 'attempt': attempt, 'outcome': 'completed',
                         'reason': 'ok', 'status': 200, 'received_bytes': size,
                         'elapsed_seconds': round(time.monotonic() - started, 3)}
                events.append(event); self.request_events.append(event)
                return result
            except urllib.error.HTTPError as exc:
                status, reason = exc.code, 'http'
                retryable = status in (429, 500, 502, 503, 504)
                retry_after = exc.headers.get('Retry-After', '') if exc.headers else ''
                if retry_after.isdigit():
                    delay = max(delay, int(retry_after))
                exc.close()
                message = f'AI 服务返回 HTTP {status}，请检查地址、密钥、模型和额度'
            except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
                cause = exc.reason if isinstance(exc, urllib.error.URLError) else exc
                if not reason:
                    reason = ('timeout' if isinstance(cause, TimeoutError) else
                              'dns' if isinstance(cause, socket.gaierror) else
                              'tls' if isinstance(cause, ssl.SSLError) else
                              'connection_reset' if isinstance(cause, ConnectionResetError) else 'connection')
                retryable = reason != 'tls'
                message = 'AI 服务连接失败或超时，已保存的数据不会丢失，请稍后重试'
            except ValueError:
                reason = 'deadline' if time.monotonic() >= self._deadline else 'invalid_response'
                message = 'AI 请求时间预算已用尽' if reason == 'deadline' else 'AI 服务返回了无效或超限响应'
            retry = retryable and attempt < 3 and time.monotonic() + delay < self._deadline
            event = {'request': self._request_count, 'attempt': attempt, 'outcome': 'retry' if retry else 'failed',
                     'reason': reason, 'status': status, 'received_bytes': size,
                     'elapsed_seconds': round(time.monotonic() - started, 3)}
            events.append(event); self.request_events.append(event)
            if not retry:
                raise AIRequestError(message, events) from None
            while delay > 0:
                if self.check_request:
                    self.check_request()
                self._timeout()
                interval = min(.25, delay)
                time.sleep(interval)
                delay -= interval

    def json(self, system, payload, images=None):
        model = self.settings.get('model', '')
        if not model:
            raise ValueError('请先在设置中填写对话模型名称')
        content = json.dumps(payload, ensure_ascii=False)
        if images:
            if len(images) > 6 or any(not isinstance(i, str) or len(i) > 2_000_000 or not re.fullmatch(r'data:image/(?:jpeg|png|webp);base64,[A-Za-z0-9+/=]+', i) for i in images):
                raise ValueError('图片必须为有界的本地截图数据')
            content = [{'type': 'text', 'text': content}] + [{'type': 'image_url', 'image_url': {'url': i}} for i in images]
        request = {'model': model, 'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': content}], 'temperature': 0.75}
        host = urllib.parse.urlparse(self.settings.get('base_url', '')).hostname
        if model in ('hy3', 'hy4-preview', 'deepseek-v4.1-flash', 'deepseek/deepseek-flash') and host in (
                'tokenhub.tencentmaas.com', 'tokenhub.tencentmaas.cn',
                'tokenhub-intl.tencentmaas.com', 'tokenhub-intl.tencentmaas.cn'):
            # Structured extraction needs final JSON within the request budget;
            # these TokenHub models otherwise spend it on default deep thinking.
            request['thinking'] = {'type': 'disabled'}
            if model in ('deepseek-v4.1-flash', 'deepseek/deepseek-flash'):
                # TokenHub's documented JSON mode; do not send provider-specific
                # capability fields to arbitrary compatible API services.
                request['response_format'] = {'type': 'json_object'}
                request['max_tokens'] = 16384
        response = self.request('/chat/completions', request)
        try:
            choice = response['choices'][0]
            content = choice['message']['content']
        except (KeyError, IndexError, TypeError):
            raise ValueError('AI 服务未返回有效回答') from None
        finish = choice.get('finish_reason')
        if finish == 'length':
            raise AIResponseError(content, finish)
        try:
            return parse_json(content)
        except (ValueError, TypeError, AttributeError):
            try:
                json.loads(content)
            except (ValueError, TypeError) as exc:
                raise AIResponseError(content, finish, exc) from None
            raise AIResponseError(content, finish) from None

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
