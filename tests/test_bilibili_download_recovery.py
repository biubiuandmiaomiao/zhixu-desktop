import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.bilibili import BilibiliPublic, _TransientPublicError


class Response(io.BytesIO):
    def __init__(self, body, headers=None, status=200):
        super().__init__(body)
        self.headers = headers or {}
        self.status = status


class DownloadRecoveryTests(unittest.TestCase):
    def run_download(self, responses, expected=10, check=lambda: None, observer=None):
        client = BilibiliPublic('https://www.bilibili.com/video/BV1AJen6SEVQ/', observer=observer)
        self.calls = 0

        def open_stream(*args, **kwargs):
            self.calls += 1
            return responses[min(self.calls - 1, len(responses) - 1)]()

        with tempfile.TemporaryDirectory() as directory, patch.object(client, 'media', return_value={'url':'https://a.bilivideo.com/a.mp4','size':expected}), patch.object(client, '_open', side_effect=open_stream):
            target = Path(directory) / 'video.mp4'
            try:
                client.download(target, check, lambda value: None, 100)
                return target.read_bytes()
            finally:
                self.assertFalse(target.with_suffix('.mp4.part').exists())

    def test_transient_primary_uses_validated_backup(self):
        client = BilibiliPublic('https://www.bilibili.com/video/BV1AJen6SEVQ/')
        primary = 'https://a.bilivideo.com/video.mp4'
        backup = 'https://upos-hz-mirrorakam.akamaized.net/video.mp4'
        opened = []
        def open_stream(url, *args, **kwargs):
            opened.append(url)
            if url == primary:
                raise _TransientPublicError('connection')
            return Response(b'0123456789', {'Content-Length': '10'})
        with tempfile.TemporaryDirectory() as directory, patch.object(client, 'media', return_value={
                'url': primary, 'backup_url': [backup], 'size': 10}), patch.object(client, '_open', side_effect=open_stream):
            target = Path(directory) / 'video.mp4'
            client.download(target, lambda: None, lambda value: None, 100)
            self.assertEqual(target.read_bytes(), b'0123456789')
        self.assertEqual(opened, [primary, backup])

    def test_untrusted_backup_is_never_opened(self):
        client = BilibiliPublic('https://www.bilibili.com/video/BV1AJen6SEVQ/')
        primary = 'https://a.bilivideo.com/video.mp4'
        opened = []
        def unavailable(url, *args, **kwargs):
            opened.append(url)
            raise _TransientPublicError('connection')
        with tempfile.TemporaryDirectory() as directory, patch.object(client, 'media', return_value={
                'url': primary, 'backup_url': [123, {}, ['bad'], 'https://evil.example/video.mp4', 'http://a.bilivideo.com/a'], 'size': 10}), patch.object(client, '_open', side_effect=unavailable):
            with self.assertRaises(ValueError):
                client.download(Path(directory) / 'video.mp4', lambda: None, lambda value: None, 100)
        self.assertEqual(opened, [primary] * 3)

    def test_early_eof_restarts_with_truncate(self):
        self.assertEqual(self.run_download([
            lambda: Response(b'abc', {'Content-Length':'10'}),
            lambda: Response(b'0123456789', {'Content-Length':'10'})]), b'0123456789')
        self.assertEqual(self.calls, 2)

    def test_short_header_cannot_override_metadata_size(self):
        with self.assertRaises(ValueError):
            self.run_download([lambda: Response(b'abc', {'Content-Length':'3'})])
        self.assertLessEqual(self.calls, 3)

    def test_wrong_range_never_commits_partial(self):
        with self.assertRaises(ValueError):
            self.run_download([lambda: Response(b'0123456789', {'Content-Length':'10','Content-Range':'bytes 5-14/20'}, 206)])

    def test_lengthless_valid_response_is_accepted(self):
        self.assertEqual(self.run_download([lambda: Response(b'0123456789')]), b'0123456789')
        self.assertEqual(self.run_download([lambda: Response(b'abc')], expected=0), b'abc')

    def test_cancel_is_not_retried(self):
        def cancel():
            raise RuntimeError('cancelled')
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            self.run_download([lambda: Response(b'0123456789')], check=cancel)
        self.assertEqual(self.calls, 0)

    def test_repeated_short_body_stops_at_three(self):
        with self.assertRaises(ValueError):
            self.run_download([lambda: Response(b'abc', {'Content-Length':'10'})])
        self.assertEqual(self.calls, 3)

    def test_cancel_between_chunks_does_not_retry(self):
        checks = []
        def cancel():
            checks.append(1)
            if len(checks) == 3:
                raise RuntimeError('cancelled')
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            self.run_download([lambda: Response(b'0123456789')], check=cancel)
        self.assertEqual(self.calls, 1)

    def test_shared_deadline_is_not_reset_on_retry(self):
        with patch('backend.bilibili.time.monotonic', side_effect=[0, 0, 0, 601]):
            with self.assertRaises(ValueError):
                self.run_download([lambda: Response(b'abc')])
        self.assertEqual(self.calls, 1)

    def test_http_auth_failure_is_not_retried(self):
        def denied():
            raise ValueError('HTTP 403')
        with self.assertRaisesRegex(ValueError, '403'):
            self.run_download([denied])
        self.assertEqual(self.calls, 1)

    def test_safe_observer_records_recovery_and_cannot_break_download(self):
        events = []
        def observe(event, details):
            events.append((event, details))
        self.run_download([lambda: Response(b'abc', {'Content-Length':'10'}),
                           lambda: Response(b'0123456789')], observer=observe)
        self.assertEqual([x[0] for x in events], ['download_attempt', 'download_retry', 'download_attempt', 'download_completed'])
        self.assertEqual(events[1][1]['reason'], 'early_eof')
        self.assertEqual(events[1][1]['received_bytes'], 3)
        for _, details in events:
            self.assertLessEqual(set(details), {'attempt','expected_bytes','header_bytes','received_bytes','status','reason'})
        def broken(*args):
            raise RuntimeError('observer failure')
        self.assertEqual(self.run_download([lambda: Response(b'0123456789')], observer=broken), b'0123456789')

    def test_read1_checks_deadline_after_each_available_piece(self):
        from types import SimpleNamespace
        clock = [0]
        timeouts = []
        class Trickle(Response):
            fp = SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(settimeout=lambda value: timeouts.append(value))))
            def read(self, size=-1):
                raise AssertionError('must use read1')
            def read1(self, size=-1):
                clock[0] += 301
                return b'x'
        with patch('backend.bilibili.time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaises(ValueError):
                self.run_download([lambda: Trickle(b'')])
        self.assertEqual(self.calls, 1)
        self.assertTrue(timeouts)
        self.assertLessEqual(timeouts[-1], 20)

    def test_legacy_response_without_read1_remains_supported(self):
        class Legacy:
            headers = {}
            status = 200
            def __init__(self):
                self.body = io.BytesIO(b'0123456789')
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.body.close()
            def read(self, size=-1):
                return self.body.read(size)
        self.assertEqual(self.run_download([Legacy]), b'0123456789')


if __name__ == '__main__':
    unittest.main()
