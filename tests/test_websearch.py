import io
import json
import unittest

from backend.websearch import WebSearch, web_source_rows


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class Opener:
    def __init__(self, payload, status=200):
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode('utf-8')
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        return Response(self.payload)


class WebSearchTests(unittest.TestCase):
    def test_bocha_results_are_parsed_and_http_is_upgraded(self):
        opener = Opener({'code': 200, 'data': {'webPages': {'value': [
            {'name': '闭包是什么', 'url': 'http://example.com/a', 'summary': '闭包捕获外部变量'},
            {'name': '坏链接', 'url': 'javascript:alert(1)', 'summary': '不应出现'},
            {'name': '无摘要', 'url': 'https://example.com/b', 'summary': ''},
        ]}}})
        client = WebSearch('bocha', 'search-key', opener=opener)
        rows = client.search('闭包', 4)
        self.assertEqual([row['url'] for row in rows], ['https://example.com/a'])
        self.assertEqual(rows[0]['title'], '闭包是什么')
        request = opener.requests[0]
        self.assertEqual(request.full_url, 'https://api.bochaai.com/v1/web-search')
        self.assertEqual(request.get_header('Authorization'), 'Bearer search-key')
        self.assertIn('闭包', request.data.decode('utf-8'))

    def test_tavily_results_are_parsed(self):
        opener = Opener({'results': [
            {'title': 'Tavily hit', 'url': 'https://example.org/x', 'content': 'snippet text'},
            {'title': 'no url', 'url': None, 'content': 'skip'},
        ]})
        rows = WebSearch('tavily', 'k', opener=opener).search('query')
        self.assertEqual(rows, [{'title': 'Tavily hit', 'url': 'https://example.org/x', 'snippet': 'snippet text'}])
        self.assertEqual(opener.requests[0].full_url, 'https://api.tavily.com/search')

    def test_provider_error_and_unconfigured_state_are_explicit(self):
        with self.assertRaisesRegex(ValueError, '未配置'):
            WebSearch('', 'key').search('q')
        with self.assertRaisesRegex(ValueError, '未配置'):
            WebSearch('bocha', '').search('q')
        with self.assertRaisesRegex(ValueError, '拒绝'):
            WebSearch('bocha', 'k', opener=Opener({'code': 403, 'msg': 'quota exceeded'})).search('q')

    def test_web_sources_are_citable_rows(self):
        rows = web_source_rows([{'title': 't', 'url': 'https://e.com', 'snippet': 's'}], 3)
        self.assertEqual(rows[0]['id'], 'web:3')
        self.assertEqual(rows[0]['kind'], 'web')
        self.assertEqual(rows[0]['retrieval'], '联网')
        self.assertEqual(rows[0]['url'], 'https://e.com')


if __name__ == '__main__':
    unittest.main()
