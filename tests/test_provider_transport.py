import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from backend.provider import Provider


class Response(io.BytesIO):
    def __init__(self, body=b'{"ok":true}'):
        super().__init__(body)
        self.headers = {'Content-Length': str(len(body))}

    def read1(self, size):
        return self.read(size)


class TransportTests(unittest.TestCase):
    def provider(self):
        return Provider({'base_url': 'https://example.com/v1'}, 'private-key-value')

    def test_connection_reset_is_retried_without_losing_diagnostics(self):
        p = self.provider()
        with patch('backend.provider.urllib.request.build_opener') as build, patch('backend.provider.time.sleep'):
            build.return_value.open.side_effect = [ConnectionResetError(10054, 'private-key-value'), Response()]
            self.assertEqual(p.request('/chat/completions', {}), {'ok': True})
            self.assertEqual(build.return_value.open.call_count, 2)
        self.assertEqual([e['outcome'] for e in p.request_events], ['retry', 'completed'])
        self.assertEqual(p.request_events[0]['reason'], 'connection_reset')
        self.assertNotIn('private-key-value', json.dumps(p.request_events))

    def test_transient_http_retries_but_authentication_does_not(self):
        for status, calls in [(429, 2), (503, 2), (401, 1), (403, 1), (400, 1), (302, 1)]:
            with self.subTest(status=status):
                p = self.provider()
                error = urllib.error.HTTPError('https://example.com', status, 'secret', {}, None)
                with patch('backend.provider.urllib.request.build_opener') as build, patch('backend.provider.time.sleep'):
                    build.return_value.open.side_effect = [error, Response()]
                    if calls == 2:
                        self.assertEqual(p.request('/chat/completions', {}), {'ok': True})
                    else:
                        with self.assertRaises(ValueError):
                            p.request('/chat/completions', {})
                    self.assertEqual(build.return_value.open.call_count, calls)

    def test_exhaustion_is_bounded_and_retains_safe_errors(self):
        p = self.provider()
        with patch('backend.provider.urllib.request.build_opener') as build, patch('backend.provider.time.sleep'):
            build.return_value.open.side_effect = urllib.error.URLError('token=secret')
            with self.assertRaises(ValueError) as caught:
                p.request('/chat/completions', {})
            self.assertEqual(build.return_value.open.call_count, 3)
        self.assertEqual(caught.exception.errors[0]['code'], 'request_failed')
        self.assertEqual(len(caught.exception.raw_result['transport_attempts']), 3)
        self.assertNotIn('secret', str(caught.exception.raw_result))

    def test_deadline_prevents_retry_and_reuses_original_budget(self):
        p = self.provider()
        with p.budget(.001), patch('backend.provider.urllib.request.build_opener') as build, patch('backend.provider.time.sleep') as sleep:
            build.return_value.open.side_effect = TimeoutError()
            with self.assertRaises(ValueError):
                p.request('/chat/completions', {})
            self.assertEqual(build.return_value.open.call_count, 1)
            sleep.assert_not_called()

    def test_partial_body_is_not_accepted_or_mixed_with_retry(self):
        p = self.provider()
        short = Response(b'{"ok":')
        short.headers['Content-Length'] = '100'
        with patch('backend.provider.urllib.request.build_opener') as build, patch('backend.provider.time.sleep'):
            build.return_value.open.side_effect = [short, Response()]
            self.assertEqual(p.request('/chat/completions', {}), {'ok': True})
        self.assertEqual(p.request_events[0]['reason'], 'early_eof')

    def test_retry_after_wait_checks_cancellation_before_next_request(self):
        p = self.provider()
        class Cancelled(Exception):
            pass
        cancelled = False
        def check():
            if cancelled:
                raise Cancelled()
        def sleep(seconds):
            nonlocal cancelled
            self.assertLessEqual(seconds, .25)
            cancelled = True
        p.check_request = check
        error = urllib.error.HTTPError('https://example.com', 429, '', {'Retry-After': '120'}, None)
        with patch('backend.provider.urllib.request.build_opener') as build, patch('backend.provider.time.sleep', side_effect=sleep):
            build.return_value.open.side_effect = error
            with self.assertRaises(Cancelled):
                p.request('/chat/completions', {})
            self.assertEqual(build.return_value.open.call_count, 1)


if __name__ == '__main__':
    unittest.main()
