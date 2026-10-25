"""Behavior tests use generated media; ASR/network are external test boundaries."""
import importlib
import http.server
import io
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.store import Store


class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ffmpeg = shutil.which('ffmpeg')
        cls.fixture_dir = tempfile.TemporaryDirectory()
        cls.video = Path(cls.fixture_dir.name) / 'lesson.mp4'
        if cls.ffmpeg:
            subprocess.run([cls.ffmpeg, '-v', 'error', '-f', 'lavfi', '-i',
                            'color=c=blue:s=160x90:r=10', '-f', 'lavfi', '-i',
                            'sine=frequency=440:sample_rate=16000', '-t', '3',
                            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                            '-y', str(cls.video)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.fixture_dir.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.manager = None
        try:
            self.media = importlib.import_module('backend.media')
        except ModuleNotFoundError:
            self.fail('Managed asynchronous media ingestion backend is missing')

    def tearDown(self):
        if self.manager:
            self.manager.close()
        self.tmp.cleanup()

    def jobs(self, transcriber=None):
        self.manager = self.media.MediaJobs(self.tmp.name, transcriber=transcriber)
        return self.manager

    def wait(self, manager, job_id, expected='completed'):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            job = manager.status(job_id)
            if job['status'] in ('completed', 'failed', 'cancelled'):
                self.assertEqual(job['status'], expected, job)
                return job
            time.sleep(.025)
        self.fail('Media job did not terminate: ' + repr(manager.status(job_id)))

    def need_ffmpeg(self):
        if not self.ffmpeg:
            self.skipTest('FFmpeg is required for generated-media integration tests')

    def test_normalizes_public_bv_links_and_rejects_untrusted_hosts(self):
        normalize = self.media.normalize_bilibili_url
        canonical = 'https://www.bilibili.com/video/BV1xx411c7mD'
        for value in ('BV1xx411c7mD', 'www.bilibili.com/video/BV1xx411c7mD/',
                      '分享视频 https://m.bilibili.com/video/BV1xx411c7mD/?spm_id=x 看这里'):
            self.assertEqual(normalize(value), canonical)
        self.assertEqual(normalize(canonical + '?p=2&token=secret'), canonical + '?p=2')
        for value in ('https://evil.invalid/video/BV1xx411c7mD',
                      'https://www.bilibili.com.evil.invalid/video/BV1xx411c7mD',
                      'https://user:password@www.bilibili.com/video/BV1xx411c7mD',
                      'https://www.bilibili.com:8443/video/BV1xx411c7mD',
                      'http://127.0.0.1/video/BV1xx411c7mD'):
            with self.assertRaises(ValueError, msg=value):
                normalize(value)

    def test_admission_rejects_missing_unsupported_oversize_and_credential_options(self):
        jobs = self.jobs()
        missing = Path(self.tmp.name) / 'missing.mp4'
        for path in (missing, Path(self.tmp.name)):
            with self.assertRaises(ValueError):
                jobs.start_local(str(path))
        unsupported = Path(self.tmp.name) / 'run.exe'
        unsupported.write_bytes(b'not media')
        with self.assertRaises(ValueError):
            jobs.start_local(str(unsupported))
        large = Path(self.tmp.name) / 'large.mp4'
        with large.open('wb') as out:
            out.truncate(self.media.MAX_MEDIA_BYTES + 1)
        with self.assertRaises(ValueError):
            jobs.start_local(str(large))
        with self.assertRaises(ValueError):
            jobs.start_video('BV1xx411c7mD', {'cookie': 'secret'})
        self.assertEqual(jobs.status(), [])

    def test_local_job_is_async_copies_media_and_preserves_source_times(self):
        self.need_ffmpeg()
        entered, release = threading.Event(), threading.Event()
        def transcribe(path, language):
            self.assertTrue(Path(path).is_file())
            self.assertNotEqual(Path(path), self.video)
            entered.set()
            release.wait(5)
            return [{'start': .4, 'text': '真实的第一段。'}, {'start': 1.6, 'text': '真实的第二段。'}]
        jobs = self.jobs(transcribe)
        before = time.monotonic()
        created = jobs.start_local(str(self.video), {'title': '测试视频'})
        self.assertLess(time.monotonic() - before, .5)
        self.assertTrue(entered.wait(5))
        pending = jobs.status(created['id'])
        self.assertEqual(pending['status'], 'running')
        self.assertEqual(pending['stage'], 'transcribing')
        self.assertGreater(pending['progress'], 0)
        release.set()
        result = self.wait(jobs, created['id'])
        self.assertEqual(result['progress'], 100)
        self.assertEqual(result['title'], '测试视频')
        store = Store(self.tmp.name)
        try:
            doc = store.document(result['document_id'])
            self.assertEqual(doc['url'], '')
            self.assertIn('本地媒体', doc['content'])
            self.assertEqual([s['start'] for s in store.segments(doc['id'])], [.4, 1.6])
            self.assertEqual([s['text'] for s in store.segments(doc['id'])], ['真实的第一段。', '真实的第二段。'])
        finally:
            store.close()
        copies = list((Path(self.tmp.name) / 'media').rglob('*.mp4'))
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].read_bytes(), self.video.read_bytes())

    def test_screenshots_are_bounded_registered_jpegs_at_transcript_timestamps(self):
        self.need_ffmpeg()
        rows = [{'start': i / 4, 'text': '片段 ' + str(i)} for i in range(10)]
        jobs = self.jobs(lambda path, language: rows)
        job = self.wait(jobs, jobs.start_local(str(self.video), {'screenshots': True})['id'])
        frames = jobs.assets(job['document_id'])
        self.assertGreater(len(frames), 0)
        self.assertLessEqual(len(frames), 6)
        for frame in frames:
            self.assertIn(frame['start'], [r['start'] for r in rows])
            self.assertTrue(frame['data_url'].startswith('data:image/jpeg;base64,/9j/'))
            self.assertNotIn('path', frame)
        self.assertEqual(jobs.assets('unknown-document'), [])
        store = Store(self.tmp.name)
        try:
            store.delete_document(job['document_id'])
        finally:
            store.close()
        self.assertEqual(jobs.assets(job['document_id']), [])

    def test_empty_asr_fails_and_retry_creates_one_real_document(self):
        self.need_ffmpeg()
        attempts = []
        def transcribe(path, language):
            attempts.append(1)
            return [] if len(attempts) == 1 else [{'start': .75, 'text': '重试后真实内容。'}]
        jobs = self.jobs(transcribe)
        first = self.wait(jobs, jobs.start_local(str(self.video))['id'], 'failed')
        self.assertTrue(first['retryable'])
        self.assertTrue(first['error'])
        self.assertIsNone(first['document_id'])
        result = self.wait(jobs, jobs.retry(first['id'])['id'])
        self.assertEqual(result['attempts'], 2)
        store = Store(self.tmp.name)
        try:
            self.assertEqual(len(store.documents()), 1)
        finally:
            store.close()

    def test_restart_marks_interrupted_jobs_retryable(self):
        self.need_ffmpeg()
        jobs = self.jobs(lambda path, language: [{'start': 0, 'text': '保存内容'}])
        job = self.wait(jobs, jobs.start_local(str(self.video))['id'])
        jobs.close()
        with sqlite3.connect(Path(self.tmp.name) / 'knowledge.sqlite3') as db:
            db.execute("UPDATE media_jobs SET status='running',document_id=NULL WHERE id=?", (job['id'],))
        db.close()
        self.manager = self.media.MediaJobs(self.tmp.name)
        interrupted = self.manager.status(job['id'])
        self.assertEqual(interrupted['status'], 'failed')
        self.assertTrue(interrupted['retryable'])
        self.assertIn('中断', interrupted['error'])

    def test_cancel_discards_asr_result_and_close_is_idempotent(self):
        self.need_ffmpeg()
        entered, release = threading.Event(), threading.Event()
        def transcribe(path, language):
            entered.set()
            release.wait(5)
            return [{'start': .5, 'text': '取消后不能保存此文本'}]
        jobs = self.jobs(transcribe)
        job = jobs.start_local(str(self.video))
        self.assertTrue(entered.wait(5))
        self.assertEqual(jobs.cancel(job['id'])['status'], 'cancelled')
        release.set()
        jobs.close()
        jobs.close()
        store = Store(self.tmp.name)
        try:
            self.assertEqual(store.documents(), [])
        finally:
            store.close()

    def test_managed_asset_registration_cannot_read_outside_media(self):
        self.need_ffmpeg()
        jobs = self.jobs(lambda path, language: [{'start': .5, 'text': '图像来源'}])
        job = self.wait(jobs, jobs.start_local(str(self.video), {'screenshots': True})['id'])
        outside = Path(self.tmp.name) / 'private.jpg'
        outside.write_bytes(b'private bytes')
        with sqlite3.connect(Path(self.tmp.name) / 'knowledge.sqlite3') as db:
            db.execute('UPDATE media_assets SET path=? WHERE document_id=?', (str(outside), job['document_id']))
        db.close()
        with self.assertRaises(ValueError):
            jobs.assets(job['document_id'])

    def fake_ytdlp(self, subtitles=True, unsafe_caption=False, inline=False):
        fixture = self.video
        parent = self
        class YoutubeDL:
            def __init__(self, options):
                self.options = options
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def extract_info(self, url, download=False):
                info = {'id': 'BV1xx411c7mD', 'title': '公开视频', 'duration': 3,
                        'subtitles': {'zh': [{'ext': 'json', 'url': ('https://evil.invalid/a' if unsafe_caption else 'https://aisubtitle.hdslb.com/a.json')}]} if subtitles else {}}
                if inline:
                    # Installed yt-dlp Bili extractor only extracts subtitles
                    # when explicitly requested, and returns converted inline SRT.
                    info['subtitles'] = {'zh': [{'ext': 'srt', 'data': '1\n00:00:01,250 --> 00:00:02,000\n内嵌公开字幕\n\n'}]} if (
                        self.options.get('writesubtitles') or self.options.get('listsubtitles')) else {}
                if download:
                    output = Path(self.options['outtmpl'].replace('%(ext)s', 'mp4'))
                    output.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(fixture, output)
                    info['_filename'] = str(output)
                return info
            def urlopen(self, url):
                parent.assertFalse(unsafe_caption, 'Unsafe subtitle URL was fetched')
                return io.BytesIO(json.dumps({'body': [{'from': 1.25, 'content': '公开字幕原文'}]}).encode())
            def prepare_filename(self, info):
                return info.get('_filename', self.options.get('outtmpl', '').replace('%(ext)s', 'mp4'))
        return types.SimpleNamespace(YoutubeDL=YoutubeDL)

    def test_bilibili_prefers_available_subtitles_without_running_asr(self):
        def forbidden_asr(*args):
            self.fail('Available public subtitles should be used before ASR')
        jobs = self.jobs(forbidden_asr)
        with patch.dict(sys.modules, {'yt_dlp': self.fake_ytdlp()}):
            job = self.wait(jobs, jobs.start_video('分享 BV1xx411c7mD')['id'])
        store = Store(self.tmp.name)
        try:
            doc = store.document(job['document_id'])
            self.assertEqual(doc['url'], 'https://www.bilibili.com/video/BV1xx411c7mD')
            self.assertEqual(doc['kind'], 'subtitle')
            self.assertEqual(store.segments(doc['id'])[0]['start'], 1.25)
            self.assertIn('公开字幕原文', doc['content'])
        finally:
            store.close()

    def test_bilibili_requests_and_reads_inline_subtitles_from_installed_extractor_contract(self):
        jobs = self.jobs(lambda *args: self.fail('Inline public subtitles must avoid ASR'))
        with patch.dict(sys.modules, {'yt_dlp': self.fake_ytdlp(inline=True)}):
            job = self.wait(jobs, jobs.start_video('BV1xx411c7mD')['id'])
        store = Store(self.tmp.name)
        try:
            self.assertEqual(store.segments(job['document_id'])[0]['text'], '内嵌公开字幕')
            self.assertEqual(store.segments(job['document_id'])[0]['start'], 1.25)
        finally:
            store.close()

    def test_failed_caption_fetch_tries_next_valid_inline_subtitle(self):
        base = self.fake_ytdlp().YoutubeDL
        attempts = []
        class YoutubeDL(base):
            def extract_info(self, url, download=False):
                info = super().extract_info(url, download)
                info['subtitles'] = {'zh': [
                    {'ext': 'vtt', 'url': 'https://aisubtitle.hdslb.com/unavailable.vtt'},
                    {'ext': 'srt', 'data': '1\n00:00:01,250 --> 00:00:02,000\n第二候选公开字幕\n\n'}]}
                return info
            def urlopen(self, url):
                attempts.append(url)
                raise TimeoutError('temporary subtitle CDN outage')
        jobs = self.jobs(lambda *args: self.fail('Valid second caption must avoid ASR'))
        with patch.dict(sys.modules, {'yt_dlp': types.SimpleNamespace(YoutubeDL=YoutubeDL)}):
            job = self.wait(jobs, jobs.start_video('BV1xx411c7mD')['id'])
        store = Store(self.tmp.name)
        try:
            self.assertEqual(len(attempts), 1)
            self.assertEqual(store.document(job['document_id'])['kind'], 'subtitle')
            self.assertEqual(store.segments(job['document_id'])[0]['text'], '第二候选公开字幕')
            self.assertEqual(store.segments(job['document_id'])[0]['start'], 1.25)
        finally:
            store.close()

    def test_all_caption_fetch_failures_fall_back_to_download_and_asr(self):
        self.need_ffmpeg()
        base = self.fake_ytdlp().YoutubeDL
        attempts = []
        class BrokenResponse(io.BytesIO):
            def read(self, *args):
                raise ConnectionError('subtitle response disconnected while reading')
        class YoutubeDL(base):
            def extract_info(self, url, download=False):
                info = super().extract_info(url, download)
                info['subtitles'] = {'zh': [
                    {'ext': 'vtt', 'url': 'https://aisubtitle.hdslb.com/fetch-error.vtt'},
                    {'ext': 'vtt', 'url': 'https://aisubtitle.hdslb.com/read-error.vtt'}]}
                return info
            def urlopen(self, url):
                attempts.append(url)
                if 'fetch-error' in url:
                    raise TimeoutError('temporary subtitle CDN outage')
                return BrokenResponse()
        jobs = self.jobs(lambda *args: [{'start': .8, 'text': '字幕故障后的真实音频转写'}])
        with patch.dict(sys.modules, {'yt_dlp': types.SimpleNamespace(YoutubeDL=YoutubeDL)}):
            job = self.wait(jobs, jobs.start_video('BV1xx411c7mD')['id'])
        store = Store(self.tmp.name)
        try:
            self.assertEqual(len(attempts), 2)
            self.assertEqual(store.document(job['document_id'])['kind'], 'media')
            self.assertEqual(store.segments(job['document_id'])[0]['text'], '字幕故障后的真实音频转写')
            self.assertEqual(store.segments(job['document_id'])[0]['start'], .8)
        finally:
            store.close()

    def test_local_embedded_text_subtitles_are_preferred_over_asr(self):
        self.need_ffmpeg()
        subtitle = Path(self.tmp.name) / 'captions.srt'
        subtitle.write_text('1\n00:00:00,500 --> 00:00:01,000\n容器内第一句原文\n\n'
                            '2\n00:00:01,750 --> 00:00:02,500\n容器内第二句原文\n\n', encoding='utf-8')
        video = Path(self.tmp.name) / 'embedded.mkv'
        subprocess.run([self.ffmpeg, '-v', 'error', '-i', str(self.video), '-i', str(subtitle),
                        '-map', '0', '-map', '1', '-c', 'copy', '-c:s', 'srt',
                        '-metadata:s:s:0', 'language=chi', '-avoid_negative_ts', 'disabled',
                        '-y', str(video)], check=True, capture_output=True)
        jobs = self.jobs(lambda *args: self.fail('Embedded text subtitles must avoid ASR'))
        job = self.wait(jobs, jobs.start_local(str(video))['id'])
        store = Store(self.tmp.name)
        try:
            doc = store.document(job['document_id'])
            self.assertEqual(doc['kind'], 'subtitle')
            self.assertIn('本地媒体', doc['content'])
            self.assertEqual([row['text'] for row in store.segments(doc['id'])], ['容器内第一句原文', '容器内第二句原文'])
            self.assertEqual([row['start'] for row in store.segments(doc['id'])], [.5, 1.75])
        finally:
            store.close()

    def test_public_video_normalizer_whitelists_canonical_platforms(self):
        normalize = getattr(self.media, 'normalize_video_url', None)
        self.assertTrue(callable(normalize), 'Public video URL normalizer is missing')
        cases = {
            'https://youtu.be/abcdefghijk?si=private': 'https://www.youtube.com/watch?v=abcdefghijk',
            'https://www.youtube.com/shorts/abcdefghijk': 'https://www.youtube.com/watch?v=abcdefghijk',
            'https://m.youtube.com/watch?v=abcdefghijk&list=ignored': 'https://www.youtube.com/watch?v=abcdefghijk',
            'https://www.douyin.com/video/1234567890123456789?secret=removed': 'https://www.douyin.com/video/1234567890123456789',
            'https://www.kuaishou.com/short-video/AbC123xyz?secret=removed': 'https://www.kuaishou.com/short-video/AbC123xyz',
            'BV1xx411c7mD': 'https://www.bilibili.com/video/BV1xx411c7mD',
        }
        for value, expected in cases.items():
            self.assertEqual(normalize(value), expected)
        for value in ('https://youtube.com.evil.invalid/watch?v=abcdefghijk',
                      'https://user:secret@www.youtube.com/watch?v=abcdefghijk',
                      'https://youtu.be:8443/abcdefghijk',
                      'https://www.douyin.com.evil.invalid/video/1234567890123456789',
                      'https://127.0.0.1/watch?v=abcdefghijk',
                      'http://www.youtube.com/watch?v=abcdefghijk',
                      'https://www.youtube.com/playlist?list=123',
                      'https://v.douyin.com/abc/', 'https://v.kuaishou.com/abc/'):
            with self.assertRaises(ValueError, msg=value):
                normalize(value)

    def test_youtube_uses_the_same_subtitle_first_worker_and_original_public_url(self):
        jobs = self.jobs(lambda *args: self.fail('Available subtitles must avoid ASR'))
        with patch.dict(sys.modules, {'yt_dlp': self.fake_ytdlp(inline=True)}):
            job = self.wait(jobs, jobs.start_video('https://youtu.be/abcdefghijk')['id'])
        store = Store(self.tmp.name)
        try:
            self.assertEqual(store.document(job['document_id'])['url'], 'https://www.youtube.com/watch?v=abcdefghijk')
            self.assertEqual(store.segments(job['document_id'])[0]['start'], 1.25)
        finally:
            store.close()

    def test_save_interruption_rolls_back_document_and_job_completion_together(self):
        self.need_ffmpeg()
        original = Store.add_document
        def interrupt(store, *args, **kwargs):
            callback = kwargs.get('on_saved')
            if callback:
                def fail_after_callback(doc_id):
                    callback(doc_id)
                    raise ValueError('simulated interruption during final transaction')
                kwargs['on_saved'] = fail_after_callback
                return original(store, *args, **kwargs)
            original(store, *args, **kwargs)
            raise ValueError('simulated interruption after non-atomic document save')
        jobs = self.jobs(lambda *args: [{'start': .5, 'text': '真实内容'}])
        with patch.object(Store, 'add_document', interrupt):
            job = self.wait(jobs, jobs.start_local(str(self.video), {'screenshots': True})['id'], 'failed')
        store = Store(self.tmp.name)
        try:
            self.assertEqual(store.documents(), [], 'An interrupted job left an orphan document')
            self.assertIsNone(job['document_id'])
            self.assertEqual(jobs.assets('unknown-document'), [])
        finally:
            store.close()

    def test_delete_document_removes_registered_media_before_or_after_store_deletion(self):
        self.need_ffmpeg()
        jobs = self.jobs(lambda *args: [{'start': .5, 'text': '删除测试原文'}])
        delete = getattr(jobs, 'delete_document', None)
        self.assertTrue(callable(delete), 'Managed media deletion is missing')
        unrelated = Path(self.tmp.name) / 'media' / 'unregistered.mp4'
        unrelated.write_bytes(b'not registered; must remain')
        for delete_store_first in (False, True):
            job = self.wait(jobs, jobs.start_local(str(self.video), {'screenshots': True})['id'])
            files = list((Path(self.tmp.name) / 'media' / job['id']).iterdir())
            self.assertGreater(len(files), 1)
            store = Store(self.tmp.name)
            try:
                if delete_store_first:
                    store.delete_document(job['document_id'])
                removed = delete(job['document_id'])
                self.assertEqual(removed['jobs'], 1)
                self.assertEqual(removed['files_removed'], len(files))
                if not delete_store_first:
                    store.delete_document(job['document_id'])
                self.assertTrue(all(not path.exists() for path in files))
                self.assertEqual(jobs.assets(job['document_id']), [])
                self.assertFalse(jobs.status(job['id'])['retryable'])
                self.assertEqual(jobs.status(job['id'])['stage'], 'deleted')
                with self.assertRaises(ValueError):
                    jobs.retry(job['id'])
                self.assertTrue(unrelated.exists())
            finally:
                store.close()

    def test_delete_document_refuses_registered_path_outside_owned_job_folder(self):
        self.need_ffmpeg()
        jobs = self.jobs(lambda *args: [{'start': .5, 'text': '删除测试原文'}])
        delete = getattr(jobs, 'delete_document', None)
        self.assertTrue(callable(delete), 'Managed media deletion is missing')
        job = self.wait(jobs, jobs.start_local(str(self.video))['id'])
        outside = Path(self.tmp.name) / 'private.mp4'
        outside.write_bytes(b'private media bytes')
        with sqlite3.connect(Path(self.tmp.name) / 'knowledge.sqlite3') as db:
            db.execute('UPDATE media_files SET path=? WHERE job_id=?', (str(outside), job['id']))
        db.close()
        with self.assertRaises(ValueError):
            delete(job['document_id'])
        self.assertEqual(outside.read_bytes(), b'private media bytes')

    def test_close_terminates_the_actual_owned_ffmpeg_subprocess(self):
        self.need_ffmpeg()
        jobs = self.jobs(lambda *args: self.fail('Cancelled probe must not reach ASR'))
        entered = threading.Event()
        processes = []
        real_popen = subprocess.Popen
        def slow_probe(command, **options):
            process = real_popen([sys.executable, '-c', 'import time; time.sleep(30)'], **options)
            processes.append(process)
            entered.set()
            return process
        with patch.object(self.media.subprocess, 'Popen', slow_probe):
            job = jobs.start_local(str(self.video))
            self.assertTrue(entered.wait(5))
            jobs.close()
        self.assertTrue(processes)
        self.assertIsNotNone(processes[0].poll(), 'Application close orphaned its subprocess')
        self.assertEqual(jobs.status(job['id'])['status'], 'cancelled')

    def test_bilibili_without_subtitles_downloads_and_transcribes_media(self):
        self.need_ffmpeg()
        jobs = self.jobs(lambda path, language: [{'start': 1.1, 'text': '下载音频的真实转写'}])
        with patch.dict(sys.modules, {'yt_dlp': self.fake_ytdlp(subtitles=False)}):
            job = self.wait(jobs, jobs.start_video('BV1xx411c7mD')['id'])
        store = Store(self.tmp.name)
        try:
            doc = store.document(job['document_id'])
            self.assertEqual(doc['kind'], 'media')
            self.assertIn('下载音频的真实转写', doc['content'])
            self.assertEqual(store.segments(doc['id'])[0]['start'], 1.1)
        finally:
            store.close()

    def test_untrusted_caption_url_is_never_fetched(self):
        jobs = self.jobs()
        with patch.dict(sys.modules, {'yt_dlp': self.fake_ytdlp(unsafe_caption=True)}):
            job = self.wait(jobs, jobs.start_video('BV1xx411c7mD')['id'], 'failed')
        self.assertIn('字幕', job['error'])

    def test_missing_ffmpeg_reports_retryable_dependency_error(self):
        self.need_ffmpeg()
        jobs = self.jobs(lambda *args: [{'start': .5, 'text': '真实文本'}])
        with patch.object(self.media, 'find_binary', return_value=None):
            job = self.wait(jobs, jobs.start_local(str(self.video))['id'], 'failed')
        self.assertTrue(job['retryable'])
        self.assertIn('FFmpeg', job['error'])

    def test_bundled_binary_precedes_machine_path(self):
        binary_dir = Path(self.tmp.name) / 'bin'
        binary_dir.mkdir()
        candidate = binary_dir / ('ffmpeg.exe' if sys.platform == 'win32' else 'ffmpeg')
        candidate.write_bytes(b'fixture')
        with patch.object(sys, '_MEIPASS', self.tmp.name, create=True):
            self.assertEqual(Path(self.media.find_binary('ffmpeg')), candidate)

    def test_schemeless_spoofed_bili_domain_is_rejected(self):
        for value in ('evilbilibili.com/video/BV1xx411c7mD',
                      'evil.www.bilibili.com/video/BV1xx411c7mD'):
            with self.assertRaises(ValueError, msg=value):
                self.media.normalize_bilibili_url(value)

    def test_packaged_ffmpeg_bin_directory_is_discovered(self):
        folder = Path(self.tmp.name) / 'ffmpeg_bin'
        folder.mkdir()
        binary = folder / ('ffprobe.exe' if sys.platform == 'win32' else 'ffprobe')
        binary.write_bytes(b'fixture')
        with patch.object(sys, '_MEIPASS', self.tmp.name, create=True):
            self.assertEqual(Path(self.media.find_binary('ffprobe')), binary)

    def test_disguised_remote_playlist_cannot_make_ffmpeg_network_requests(self):
        self.need_ffmpeg()
        hits = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'not a transport stream')
            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        fake_video = Path(self.tmp.name) / 'disguised.mp4'
        fake_video.write_text('#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:3\n#EXTINF:3,\nhttp://127.0.0.1:'
                              + str(server.server_port) + '/audio.ts\n#EXT-X-ENDLIST\n')
        try:
            jobs = self.jobs(lambda *args: self.fail('Network playlist must never reach ASR'))
            self.wait(jobs, jobs.start_local(str(fake_video))['id'], 'failed')
            self.assertEqual(hits, [], 'FFmpeg fetched an external URL from a disguised local media file')
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(2)


if __name__ == '__main__':
    unittest.main()
