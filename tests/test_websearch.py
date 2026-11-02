import io
import json
import unittest

from backend.websearch import WebSearch, _relevant, _search_so, web_source_rows


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

    def test_builtin_provider_is_configured_without_a_key(self):
        self.assertTrue(WebSearch('builtin', '').configured)
        self.assertEqual(WebSearch('bocha', '').configured, False)

    def test_relevance_check_rejects_off_topic_results(self):
        self.assertTrue(_relevant('闭包是什么', {'title': '闭包是什么?五分钟了解闭包', 'snippet': '闭包捕获变量'}))
        self.assertFalse(_relevant('闭包是什么', {'title': '闭_百度百科', 'snippet': '闭的拼音与部首'}))
        self.assertTrue(_relevant('Python closure', {'title': 'Python closures', 'snippet': 'nested function'}))

    def test_so_results_use_mdurl_and_skip_portal_links(self):
        markup = ''.join([
            '<li class="res-list"><style>.a{color:red}</style>',
            '<h3 class="res-title"><a href="https://www.so.com/link?m=x">闭包是什么?五分钟带你了解闭包 - 知乎</a></h3>',
            '<div class="res-desc">闭包捕获外部变量，即使外层函数返回仍然保留。</div>',
            '<span data-mdurl="https://www.so.com/link?m=skip"></span>',
            '<span data-mdurl="https://zhuanlan.zhihu.com/p/703373072"></span></li>',
        ])
        rows = _search_so(Opener(markup.encode('utf-8')), '闭包是什么', 3)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['url'], 'https://zhuanlan.zhihu.com/p/703373072')
        self.assertIn('闭包是什么', rows[0]['title'])
        self.assertIn('闭包捕获外部变量', rows[0]['snippet'])

    def test_builtin_falls_back_to_the_second_engine_when_results_are_irrelevant(self):
        bing = ('<li class="b_algo"><h2><a href="https://baike.baidu.com/closed">闭_百度百科</a></h2>'
                '<p>闭的拼音是 bi。</p></li>')
        so = ('<li class="res-list"><h3><a href="https://www.so.com/link?m=x">闭包是什么 - 知乎</a></h3>'
              '<div class="res-desc">闭包捕获外部变量。</div>'
              '<span data-mdurl="https://zhuanlan.zhihu.com/p/1"></span></li>')

        class MultiOpener:
            def __init__(self):
                self.requests = []

            def open(self, request, timeout=None):
                self.requests.append(request.full_url)
                payload = bing if 'bing.com' in request.full_url else so
                return Response(payload.encode('utf-8'))

        opener = MultiOpener()
        rows = WebSearch('builtin', '', opener=opener).search('闭包是什么', 3)
        self.assertEqual(len(opener.requests), 2, 'bing first, then so.com fallback')
        self.assertEqual(rows[0]['url'], 'https://zhuanlan.zhihu.com/p/1')
        self.assertIn('闭包', rows[0]['title'])

    def test_builtin_reports_when_every_engine_fails(self):
        class Broken:
            def open(self, request, timeout=None):
                raise OSError('blocked')
        with self.assertRaisesRegex(ValueError, '没有返回可用结果'):
            WebSearch('builtin', '', opener=Broken()).search('闭包是什么')


if __name__ == '__main__':
    unittest.main()
