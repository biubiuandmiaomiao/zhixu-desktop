import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.media import MediaJobs, _options


class MediaQualityTests(unittest.TestCase):
    def test_range_diagnostics_are_bounded_and_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(MediaJobs, '_run', lambda self: None):manager=MediaJobs(directory)
            try:
                job=manager.start_video('BV1xx411c7mD')
                detail={'attempt':1,'expected_bytes':100,'received_bytes':40,'status':206,
                        'range_start':40,'range_end':59,'committed_bytes':40,'segment_attempt':2,
                        'request_count':4,'retry_count':1,'budget_seconds':600,'reason':'early_eof'}
                manager._download_event(job['id'],'download_retry',detail)
                manager._download_event(job['id'],'download_failed',{**detail,'reason':'deadline','elapsed_seconds':601})
                events=manager.status(job['id'])['events']
                self.assertEqual(events[0]['details'],detail)
                self.assertEqual(events[1]['details']['elapsed_seconds'],601)
            finally:manager.close()

    def test_bounded_model_options_and_legacy_default(self):
        self.assertEqual(_options({}).get('asr_model'), 'base')
        for name in ('tiny', 'base', 'small'):
            self.assertEqual(_options({'asr_model': name})['asr_model'], name)
        for value in ('large', '', None, 1, [], {}):
            with self.assertRaises(ValueError):
                _options({'asr_model': value})

    def test_selected_model_switches_and_persists_language_metadata(self):
        calls = []
        def model(name, **kwargs):
            calls.append(name)
            return types.SimpleNamespace(transcribe=lambda *a, **kw: (
                iter([types.SimpleNamespace(start=0, text='Neural network')]),
                types.SimpleNamespace(language='en', language_probability=.97)))
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(MediaJobs, '_run', lambda self: None):
                manager = MediaJobs(directory)
            try:
                with patch.dict('sys.modules', {'faster_whisper': types.SimpleNamespace(WhisperModel=model)}):
                    for name in ('tiny', 'base', 'small', 'small'):
                        job = manager.start_video('BV1xx411c7mD', {'asr_model': name})
                        result = manager._transcribe(job['id'], Path('mock.wav'), 'auto', 10)
                        self.assertEqual(result[0]['text'], 'Neural network')
                        event = manager.status(job['id'])['events'][-1]
                        self.assertEqual(event['details'], {'asr_model': name, 'language': 'en', 'language_probability': .97, 'segment_count': 1})
                    self.assertEqual(calls, ['tiny', 'base', 'small'])
                with manager._connect() as db:
                    db.execute('UPDATE media_jobs SET options=? WHERE id=?', (json.dumps({'language':'auto'}), job['id']))
                with patch.dict('sys.modules', {'faster_whisper': types.SimpleNamespace(WhisperModel=model)}):
                    manager._transcribe(job['id'], Path('mock.wav'), 'auto', 10)
                self.assertEqual(calls[-1], 'base')
            finally:
                manager.close()
            with patch.object(MediaJobs, '_run', lambda self: None):
                reopened = MediaJobs(directory)
            try:
                self.assertEqual(reopened.status(job['id'])['events'][-1]['details']['language'], 'en')
            finally:
                reopened.close()

    def test_model_failure_is_explicit_and_does_not_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(MediaJobs, '_run', lambda self: None):
                manager = MediaJobs(directory)
            try:
                job = manager.start_video('BV1xx411c7mD', {'asr_model': 'small'})
                factory = unittest.mock.Mock(side_effect=RuntimeError('https://cdn.invalid/?token=secret'))
                with patch.dict('sys.modules', {'faster_whisper': types.SimpleNamespace(WhisperModel=factory)}):
                    with self.assertRaisesRegex(ValueError, 'small.*首次.*下载'):
                        manager._transcribe(job['id'], Path('mock.wav'), 'auto', 10)
                self.assertEqual(factory.call_count, 1)
                self.assertNotIn('secret', json.dumps(manager.status(job['id'])))
            finally:
                manager.close()

    def test_events_are_bounded_and_reject_untrusted_language_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(MediaJobs, '_run', lambda self: None):
                manager = MediaJobs(directory)
            try:
                job = manager.start_video('BV1xx411c7mD')
                with self.assertRaises(ValueError):
                    manager._asr_event(job['id'], 'unsafe', 'https://cdn.invalid/?token=secret')
                for _ in range(30):
                    manager._asr_event(job['id'], 'asr_completed', 'base',
                                       'https://cdn.invalid/?token=secret', float('nan'), 1)
                events = manager.status(job['id'])['events']
                self.assertEqual(len(events), 20)
                self.assertIsNone(events[-1]['details']['language'])
                self.assertIsNone(events[-1]['details']['language_probability'])
                self.assertNotIn('secret', json.dumps(events))
            finally:
                manager.close()

    def test_injected_transcriber_keeps_two_argument_contract(self):
        received = []
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(MediaJobs, '_run', lambda self: None):
                manager = MediaJobs(directory, transcriber=lambda path, language: received.append((path, language)) or [{'start': 0, 'text': 'ok'}])
            try:
                job = manager.start_video('BV1xx411c7mD', {'asr_model': 'small'})
                self.assertEqual(manager._transcribe(job['id'], Path('mock.wav'), 'en', 10)[0]['text'], 'ok')
                self.assertEqual(received, [('mock.wav', 'en')])
            finally:
                manager.close()

    def test_download_diagnostics_are_strict_bounded_and_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(MediaJobs, '_run', lambda self: None):
                manager = MediaJobs(directory)
            try:
                job = manager.start_video('BV1xx411c7mD')
                invalid = [
                    ('unsafe', {}), ('download_retry', {'url': 'https://cdn/?token=secret'}),
                    ('download_retry', {'reason': 'https://cdn/?token=secret'}),
                    ('download_attempt', {'attempt': True}), ('download_attempt', {'attempt': -1}),
                    ('download_completed', {'received_bytes': float('inf')}),
                    ('download_completed', {'received_bytes': 'secret'}),
                    ('download_completed', {'status': 200.5}),
                    ('download_retry', {'expected_bytes': float('nan')}),
                ]
                for event, details in invalid:
                    with self.assertRaises(ValueError):
                        manager._download_event(job['id'], event, details)
                self.assertEqual(manager.status(job['id'])['events'], [])
                details = {'attempt': 2, 'expected_bytes': 1234, 'header_bytes': 1234,
                           'received_bytes': 500, 'status': 200, 'reason': 'early_eof'}
                for _ in range(25):
                    manager._download_event(job['id'], 'download_retry', details)
                self.assertEqual(len(manager.status(job['id'])['events']), 20)
                self.assertEqual(manager.status(job['id'])['events'][-1]['details'], details)
            finally:
                manager.close()
            with patch.object(MediaJobs, '_run', lambda self: None):
                reopened = MediaJobs(directory)
            try:
                events = reopened.status(job['id'])['events']
                self.assertEqual(len(events), 20)
                self.assertEqual(events[-1]['event'], 'download_retry')
                self.assertEqual(events[-1]['details'], details)
                self.assertNotIn('secret', json.dumps(events))
            finally:
                reopened.close()

    def test_public_download_observer_is_connected_to_job_status(self):
        class Public:
            def __init__(self, url, observer=None):
                self.observer = observer
            def info(self):
                return {'title': 'test', 'subtitles': [], 'duration': 3}
            def download(self, target, check, progress, limit):
                self.observer('download_completed', {'attempt': 1, 'received_bytes': 8})
                return target
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(MediaJobs, '_run', lambda self: None):
                manager = MediaJobs(directory)
            try:
                job = manager.start_video('BV1xx411c7mD')
                with patch('backend.bilibili.BilibiliPublic', Public):
                    manager._bilibili_public(job, job['options'], manager.media_directory / job['id'])
                event = manager.status(job['id'])['events'][-1]
                self.assertEqual(event['event'], 'download_completed')
                self.assertEqual(event['details']['received_bytes'], 8)
            finally:
                manager.close()

    def test_activity_includes_running_job_older_than_201_terminal_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(MediaJobs, '_run', lambda self: None):
                manager = MediaJobs(directory)
            try:
                self.assertEqual(manager.activity(), {'active': False, 'count': 0})
                active = manager.start_video('BV1xx411c7mD')
                manager._update(active['id'], status='running')
                for _ in range(201):
                    job = manager.start_video('BV1xx411c7mD')
                    manager.cancel(job['id'])
                self.assertNotIn(active['id'], [j['id'] for j in manager.status()])
                self.assertEqual(manager.activity(), {'active': True, 'count': 1})
                manager.cancel(active['id'])
                self.assertEqual(manager.activity(), {'active': False, 'count': 0})
            finally:
                manager.close()

    def test_service_exposes_authoritative_activity_and_bootstrap_flag(self):
        from backend.service import Service
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(MediaJobs, '_run', lambda self: None):
                service = Service(directory)
            try:
                self.assertEqual(service.dispatch('media_activity'), {'active': False, 'count': 0})
                self.assertIs(service.dispatch('bootstrap')['media_active'], False)
                job = service.media.start_video('BV1xx411c7mD')
                self.assertEqual(service.dispatch('media_activity'), {'active': True, 'count': 1})
                self.assertIs(service.dispatch('bootstrap')['media_active'], True)
                service.media.cancel(job['id'])
                self.assertEqual(service.dispatch('media_activity'), {'active': False, 'count': 0})
            finally:
                service.close()
