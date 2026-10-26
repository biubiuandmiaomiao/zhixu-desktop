import io
import http.client
import json
import unittest
import urllib.error
from unittest.mock import patch

from backend.bilibili import BilibiliPublic


URL = 'https://api.bilibili.com/x/player/pagelist?bvid=BV1AJen6SEVQ'


class Response(io.BytesIO):
    def geturl(self):
        return URL


class RetryTests(unittest.TestCase):
    def client(self, outcomes):
        class Opener:
            calls = 0
            timeouts = []

            def open(self, request, timeout):
                self.calls += 1
                self.timeouts.append(timeout)
                value = outcomes[min(self.calls - 1, len(outcomes) - 1)]
                if isinstance(value, Exception):
                    raise value
                if isinstance(value, io.BytesIO):
                    return value
                return Response(value if isinstance(value, bytes) else json.dumps(value).encode())

        opener = Opener()
        return BilibiliPublic('https://www.bilibili.com/video/BV1AJen6SEVQ/', opener), opener

    def test_transient_http_keeps_safe_status_for_diagnostics(self):
        client, _ = self.client([urllib.error.HTTPError(URL, 567, 'signed-url-secret', {}, None)])
        with self.assertRaises(ValueError) as error:
            client._open(URL, 'api')
        self.assertEqual(getattr(error.exception, 'status', None), 567)
        self.assertNotIn('signed-url-secret', str(error.exception))

    @patch('backend.bilibili.time.sleep')
    def test_network_and_transient_http_recover(self, sleep):
        for failure in [TimeoutError(), urllib.error.URLError('temporary'),
                        urllib.error.HTTPError(URL, 429, 'rate', {}, None),
                        urllib.error.HTTPError(URL, 503, 'temporary', {}, None)]:
            with self.subTest(failure=failure):
                client, opener = self.client([failure, failure, {'code': 0, 'data': [1]}])
                self.assertEqual(client._json(URL), [1])
                self.assertEqual(opener.calls, 3)
                self.assertLessEqual(sum(opener.timeouts), 24)

    @patch('backend.bilibili.time.sleep')
    def test_retries_are_bounded_and_errors_do_not_leak_url(self, sleep):
        client, opener = self.client([urllib.error.URLError('secret-url-token')])
        with self.assertRaises(ValueError) as error:
            client._json(URL)
        self.assertEqual(opener.calls, 3)
        self.assertNotIn('secret-url-token', str(error.exception))

    @patch('backend.bilibili.time.sleep')
    def test_auth_business_and_malformed_errors_do_not_retry(self, sleep):
        for failure in [urllib.error.HTTPError(URL, 401, 'auth', {}, None),
                        urllib.error.HTTPError(URL, 403, 'auth', {}, None),
                        urllib.error.HTTPError(URL, 404, 'missing', {}, None),
                        {'code': -403, 'message': 'denied'}, b'not-json']:
            client, opener = self.client([failure])
            with self.assertRaises(ValueError):
                client._json(URL)
            self.assertEqual(opener.calls, 1)
        sleep.assert_not_called()

    @patch('backend.bilibili.time.sleep')
    def test_incomplete_metadata_body_is_retried_from_start(self, sleep):
        class InterruptedResponse(Response):
            def read(self, size=-1):
                raise http.client.IncompleteRead(b'partial')

        interrupted = InterruptedResponse(b'')
        client, opener = self.client([interrupted, {'code': 0, 'data': [2]}])
        self.assertEqual(client._json(URL), [2])
        self.assertEqual(opener.calls, 2)
        self.assertTrue(interrupted.closed)


if __name__ == '__main__':
    unittest.main()
