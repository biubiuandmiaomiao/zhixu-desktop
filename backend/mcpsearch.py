"""Minimal MCP (Model Context Protocol) stdio client for web search.

The app speaks newline-delimited JSON-RPC 2.0 to a locally installed MCP server
(open-websearch by default): initialize -> notifications/initialized -> tools/list
-> tools/call. Only a locally configured command is spawned; results are treated
as untrusted data.
"""
import json
import shutil
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request

PROTOCOL_VERSION = '2024-11-05'
CLIENT_INFO = {'name': 'zhixu-desktop', 'version': '0.4.5'}
DEFAULT_COMMAND = 'open-websearch'
DEFAULT_TOOL = 'search'
DEFAULT_ENGINES = ('sogou', 'baidu')
STARTUP_TIMEOUT = 60
REDIRECT_LIMIT = 5
BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml',
}
_PORTAL_HOSTS = ('baidu.com', 'sogou.com', 'so.com', 'bing.com')


def command_available(command):
    return bool(command and shutil.which(command))


def resolve_portal_url(url, timeout=8):
    """Baidu/Sogou return /link?url= redirects; follow them to the real page."""
    parsed = urllib.parse.urlsplit(url or '')
    host = (parsed.hostname or '').lower()
    if not any(host == portal or host.endswith('.' + portal) for portal in _PORTAL_HOSTS):
        return url
    if '/link' not in parsed.path:
        return url
    request = urllib.request.Request(url, headers=BROWSER_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final = response.geturl()
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError):
        return ''
    if not final or not final.startswith(('http://', 'https://')):
        return ''
    return final


class McpSearch:
    def __init__(self, command=DEFAULT_COMMAND, args=None, env=None, tool=DEFAULT_TOOL,
                 engines=None, timeout=STARTUP_TIMEOUT):
        self.command = command or DEFAULT_COMMAND
        self.args = list(args or [])
        self.env = {'MODE': 'stdio', **(env or {})}
        self.tool = tool or DEFAULT_TOOL
        self.engines = list(engines or DEFAULT_ENGINES)
        self.timeout = timeout

    @property
    def configured(self):
        return command_available(self.command)

    def _argv(self):
        """npm global installs are .cmd shims on Windows; those need cmd.exe."""
        resolved = shutil.which(self.command)
        if not resolved:
            raise ValueError(f'未找到 MCP 搜索命令 {self.command}，请先安装 open-websearch')
        if resolved.lower().endswith(('.cmd', '.bat')):
            return ['cmd.exe', '/c', resolved, *self.args]
        return [resolved, *self.args]

    def search(self, query, limit=5):
        query = (query or '').strip()
        if not query:
            return []
        if not self.configured:
            raise ValueError(f'未找到 MCP 搜索命令 {self.command}，请先安装 open-websearch')
        rows, error = self._call(query, limit)
        if error:
            raise ValueError(error)
        return rows

    # ---- protocol ---------------------------------------------------------
    def _call(self, query, limit):
        import os
        env = {**os.environ, **self.env, 'MCP_STDIO': '1'}
        try:
            argv = self._argv()
        except ValueError as exc:
            return [], str(exc)
        try:
            process = subprocess.Popen(argv, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       text=True, encoding='utf-8', errors='replace',
                                       env=env, bufsize=1, shell=False)
        except OSError as exc:
            return [], f'无法启动 MCP 搜索服务：{exc}'
        timer = threading.Timer(self.timeout, process.kill)
        timer.start()
        try:
            return self._converse(process, query, limit)
        finally:
            timer.cancel()
            try:
                process.stdin.close()
            except Exception:
                pass
            try:
                process.wait(timeout=5)
            except Exception:
                process.kill()

    def _converse(self, process, query, limit):
        counter = [0]

        def send(method, params=None, notify=False):
            message = {'jsonrpc': '2.0', 'method': method}
            if not notify:
                counter[0] += 1
                message['id'] = counter[0]
            if params is not None:
                message['params'] = params
            process.stdin.write(json.dumps(message, ensure_ascii=False) + '\n')
            process.stdin.flush()
            return counter[0]

        def receive(request_id):
            while True:
                line = process.stdout.readline()
                if not line:
                    raise RuntimeError('MCP 服务已退出')
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if value.get('id') != request_id:
                    continue
                if 'error' in value:
                    error = value['error']
                    raise RuntimeError(str(error.get('message') if isinstance(error, dict) else error))
                return value.get('result') or {}

        try:
            request_id = send('initialize', {'protocolVersion': PROTOCOL_VERSION, 'capabilities': {},
                                             'clientInfo': CLIENT_INFO})
            receive(request_id)
            send('notifications/initialized', {}, notify=True)
            request_id = send('tools/list')
            tools = receive(request_id).get('tools') or []
            name = self._pick_tool(tools)
            if not name:
                return [], 'MCP 服务没有提供搜索工具'
            request_id = send('tools/call', {'name': name, 'arguments': {
                'query': query, 'limit': limit, **({'engines': self.engines} if self.engines else {})}})
            result = receive(request_id)
            return self._parse(result), ''
        except RuntimeError as exc:
            return [], f'MCP 搜索失败：{exc}'
        except (OSError, ValueError) as exc:
            return [], f'MCP 搜索失败：{type(exc).__name__}'

    def _pick_tool(self, tools):
        names = [tool.get('name') for tool in tools if isinstance(tool, dict)]
        if self.tool in names:
            return self.tool
        for name in names:
            if 'search' in str(name).lower():
                return name
        return ''

    def _parse(self, result):
        """Turn MCP content blocks into search rows (open-websearch returns JSON text)."""
        texts = []
        for block in result.get('content') or []:
            if isinstance(block, dict) and isinstance(block.get('text'), str):
                texts.append(block['text'])
        payload = None
        for text in texts:
            try:
                payload = json.loads(text)
                break
            except ValueError:
                continue
        if isinstance(payload, dict):
            data = payload.get('data') if isinstance(payload.get('data'), dict) else payload
            entries = data.get('results') if isinstance(data, dict) else None
            if not isinstance(entries, list):
                entries = payload.get('results') if isinstance(payload.get('results'), list) else []
        elif isinstance(payload, list):
            entries = payload
        else:
            entries = []
        rows = []
        resolved_count = 0
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get('title') or '').strip()
            url = str(entry.get('url') or '').strip()
            snippet = str(entry.get('description') or entry.get('snippet') or entry.get('content') or '').strip()
            if not title or not url.startswith(('http://', 'https://')) or not snippet:
                continue
            if resolved_count < REDIRECT_LIMIT:
                resolved = resolve_portal_url(url)
                resolved_count += 1
                if not resolved:
                    continue
                url = resolved
            if url.startswith('http://'):
                url = 'https://' + url[len('http://'):]
            if any(existing['url'] == url for existing in rows):
                continue
            rows.append({'title': title[:200], 'url': url, 'snippet': snippet[:800]})
        return rows
