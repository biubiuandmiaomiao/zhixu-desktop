"""English media must produce a tutorial only after the real generation step."""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.service import Service


class TutorialAI:
    def __init__(self):
        self.calls = []
        self.failure = False
        self.entered = threading.Event()
        self.release = None

    def json(self, system, payload, images=None):
        self.calls.append((system, payload, images))
        self.entered.set()
        if self.release:
            self.release.wait(10)
        if self.failure:
            raise ValueError('测试模型暂不可用')
        source = payload['sources'][0]['id']
        return {'title': '创建工具', 'content': '# 创建工具的中文教程\n\n' +
                '函数说明告诉模型何时使用工具，实际函数由程序执行。' * 4 + f' [来源:{source}]'}


class MediaTutorialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ai = TutorialAI()
        self.provider = patch('backend.service.Provider', return_value=self.ai)
        self.provider.start()
        self.service = Service(self.temp.name)
        self.rows = [{'start': 1.25, 'text': 'The model decides when to call a function.'},
                     {'start': 8.5, 'text': 'The application executes the actual function.'}]
        self.public = patch.object(self.service.media, '_public_video',
                                   return_value=('English tool lesson', self.rows, None))
        self.public_call = self.public.start()

    def tearDown(self):
        if self.ai.release:
            self.ai.release.set()
        self.service.close()
        self.public.stop()
        self.provider.stop()
        self.temp.cleanup()

    def start(self, generate=True):
        try:
            return self.service.dispatch('start_video_job', {
                'url': 'https://www.bilibili.com/video/BV1AJen6SEVQ?p=15',
                'options': {'generate_tutorial': generate}}, api_key='test-transient-credential')
        except ValueError as exc:
            self.fail('视频导入应支持自动中文教程选项：' + str(exc))

    def wait(self, job_id, expected='completed'):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            job = self.service.media.status(job_id)
            if job['status'] in ('completed', 'failed', 'cancelled'):
                self.assertEqual(job['status'], expected, job)
                return job
            time.sleep(.02)
        self.fail('任务未完成')

    def test_video_import_generates_chinese_but_preserves_english_sources(self):
        job = self.wait(self.start()['id'])
        doc = self.service.store.document(job['document_id'])
        self.assertIn('中文教程', doc['content'])
        self.assertEqual(job['stage'], 'tutorial_completed')
        self.assertEqual([s['text'] for s in self.service.store.segments(doc['id'])],
                         [r['text'] for r in self.rows])
        self.assertEqual([s['start'] for s in self.service.store.segments(doc['id'])], [1.25, 8.5])
        self.assertEqual(len(self.service.store.documents()), 1)
        self.assertIn('中文', self.ai.calls[0][0])
        self.assertNotIn('test-transient-credential', str(job))
        self.assertNotIn(b'test-transient-credential',
                         (Path(self.temp.name) / 'knowledge.sqlite3').read_bytes())

    def test_opt_out_imports_original_text_without_calling_a_model(self):
        job = self.wait(self.start(False)['id'])
        self.assertIn(self.rows[0]['text'], self.service.store.document(job['document_id'])['content'])
        self.assertEqual(self.ai.calls, [])

    def test_generation_failure_preserves_source_and_retry_does_not_reimport(self):
        self.ai.failure = True
        failed = self.wait(self.start()['id'], 'failed')
        self.assertTrue(failed['document_id'])
        self.assertEqual(failed['stage'], 'tutorial_failed')
        self.assertIn('原文已保存', failed['error'])
        source_ids = [s['id'] for s in self.service.store.segments(failed['document_id'])]
        self.ai.failure = False
        self.service.dispatch('retry_media_job', {'id': failed['id']}, api_key='test-transient-credential')
        completed = self.wait(failed['id'])
        self.assertEqual(completed['document_id'], failed['document_id'])
        self.assertEqual(self.public_call.call_count, 1)
        self.assertEqual([s['id'] for s in self.service.store.segments(failed['document_id'])], source_ids)
        self.assertEqual(len(self.service.store.documents()), 1)
        self.assertIn('中文教程', self.service.store.document(failed['document_id'])['content'])

    def test_cancel_during_generation_does_not_save_late_model_output(self):
        self.ai.release = threading.Event()
        created = self.start()
        self.assertTrue(self.ai.entered.wait(5))
        pending = self.service.media.status(created['id'])
        self.assertEqual(pending['stage'], 'generating_tutorial')
        self.assertTrue(pending['document_id'])
        self.service.media.cancel(created['id'])
        self.ai.release.set()
        deadline = time.monotonic() + 5
        while self.service.media._current and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertEqual(self.service.media.status(created['id'])['status'], 'cancelled')
        self.assertNotIn('中文教程', self.service.store.document(pending['document_id'])['content'])

    def test_background_result_does_not_overwrite_edits_made_while_waiting(self):
        self.ai.release = threading.Event()
        created = self.start()
        self.assertTrue(self.ai.entered.wait(5))
        pending = self.service.media.status(created['id'])
        edited = '这是用户在后台生成期间保存的编辑，必须保留。'
        self.service.dispatch('update_document', {'id': pending['document_id'],
                              'title': '我的编辑', 'content': edited})
        self.ai.release.set()
        failed = self.wait(created['id'], 'failed')
        self.assertIn('已更新', failed['error'])
        self.assertEqual(self.service.store.document(pending['document_id'])['content'], edited)

    def test_manual_generation_marks_an_existing_raw_import_as_tutorial(self):
        original = self.wait(self.start(False)['id'])
        self.service.dispatch('tutorial', {'id': original['document_id']}, api_key='test-transient-credential')
        self.assertEqual(self.service.media.status(original['id'])['stage'], 'tutorial_completed')

