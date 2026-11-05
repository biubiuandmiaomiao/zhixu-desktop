import json
import sys
import unittest
from unittest.mock import patch

from backend.mcpsearch import McpSearch, resolve_portal_url
from backend.websearch import WebSearch


class FakeProcess:
    def __init__(self, responses):
        self.responses = list(responses)
        self.writes = []

    @property
    def stdin(self):
        outer = self

        class Sink:
            def write(self, text):
                outer.writes.append(text)

            def flush(self):
                pass
        return Sink()

    @property
    def stdout(self):
        outer = self

        class Source:
            def readline(self):
                if outer.responses:
                    return json.dumps(outer.responses.pop(0), ensure_ascii=False) + '\n'
                return ''
        return Source()


class McpSearchTests(unittest.TestCase):
    def test_parse_reads_open_websearch_payload(self):
        client = McpSearch()
        result = {'content': [{'type': 'text', 'text': json.dumps({'status': 'ok', 'data': {
            'results': [
                {'title': '闭包是什么', 'url': 'https://example.com/a', 'description': '闭包解释'},
                {'title': '无地址', 'url': '', 'description': 'skip'},
            ]}})}]}
        with patch('backend.mcpsearch.resolve_portal_url', side_effect=lambda url: url):
            rows = client._parse(result)
        self.assertEqual(rows, [{'title': '闭包是什么', 'url': 'https://example.com/a', 'snippet': '闭包解释'}])

    def test_parse_skips_unresolvable_portal_redirects(self):
        client = McpSearch()
        result = {'content': [{'type': 'text', 'text': json.dumps({'results': [
            {'title': '百度结果', 'url': 'http://www.baidu.com/link?url=abc', 'description': '内容'},
        ]})}]}
        with patch('backend.mcpsearch.resolve_portal_url', return_value=''):
            self.assertEqual(client._parse(result), [])

    def test_pick_tool_prefers_named_search_tool(self):
        client = McpSearch()
        self.assertEqual(client._pick_tool([{'name': 'fetchWebContent'}, {'name': 'search'}]), 'search')
        self.assertEqual(client._pick_tool([{'name': 'webSearch'}]), 'webSearch')
        self.assertEqual(client._pick_tool([{'name': 'other'}]), '')

    def test_missing_command_is_reported_not_crashed(self):
        client = McpSearch(command='definitely-not-installed-xyz')
        self.assertFalse(client.configured)
        with self.assertRaisesRegex(ValueError, 'open-websearch|未找到'):
            client.search('闭包')

    def test_portal_resolution_keeps_plain_urls_untouched(self):
        self.assertEqual(resolve_portal_url('https://example.com/page'), 'https://example.com/page')

    def test_websearch_mcp_provider_ranks_and_filters_results(self):
        search = WebSearch('mcp', '')
        self.assertTrue(search.configured)
        rows = [
            {'title': '闭包是什么', 'url': 'https://example.com/a', 'snippet': '闭包 解释'},
            {'title': '无关内容', 'url': 'https://example.com/b', 'snippet': '篮球比赛'},
            {'title': 'Python 闭包', 'url': 'https://example.com/c', 'snippet': '闭包 捕获变量'},
        ]
        class Client:
            configured = True
            command = 'open-websearch'
            def search(self, query, limit):
                return list(rows)
        search.mcp = Client()
        result = search.search('闭包是什么', 2)
        self.assertEqual(len(result), 2)
        self.assertTrue(all('闭包' in row['title'] or '闭包' in row['snippet'] for row in result))
        self.assertNotIn('https://example.com/b', [row['url'] for row in result])

    def test_websearch_mcp_provider_unconfigured_is_explicit(self):
        search = WebSearch('mcp', '', mcp_command='definitely-not-installed-xyz')
        self.assertFalse(search.configured)
        with self.assertRaisesRegex(ValueError, '未配置'):
            search.search('闭包')


if __name__ == '__main__':
    unittest.main()
