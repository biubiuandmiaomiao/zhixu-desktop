import tempfile
import unittest

from backend.knowledge import Knowledge
from backend.review import Review
from backend.store import Store
from tests.test_review import FixtureAI


class RecordingAI(FixtureAI):
    settings = {}
    api_key = ''

    def __init__(self, source_id):
        super().__init__(source_id)
        self.calls = []

    def json(self, system, payload):
        self.calls.append((system, payload))
        if '中文 Markdown 教程' in system:
            return {'content': '闭包捕获外部变量，需要结合生命周期理解。' * 4 + f'[来源:{self.source_id}]'}
        if 'source_ids' in system and 'questions' not in system:
            return {'answer': '闭包捕获外部变量。[1]', 'source_ids': [self.source_id]}
        return super().json(system, payload)


class GenerationContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.doc = self.store.add_document('闭包', '闭包捕获外部变量，返回函数后仍保留引用，需要关注生命周期。' * 12)
        self.ai = RecordingAI(self.store.segments(self.doc['id'])[0]['id'])
        self.old = self.store.save_memory('讲解偏好', '先讲理论')
        self.current = self.store.save_memory('讲解偏好', '先给例子')

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def assert_current_preferences(self):
        preferences = self.ai.calls[-1][1].get('preferences', [])
        self.assertEqual([p['id'] for p in preferences], [self.current['id']])
        self.assertEqual(preferences[0]['text'], '先给例子')

    def test_ask_reads_current_preferences_without_embedding(self):
        Knowledge(self.store, self.ai, None).ask('如何理解闭包？')
        self.assert_current_preferences()

    def test_tutorial_reads_current_preferences_without_embedding(self):
        Knowledge(self.store, self.ai, None).tutorial(self.doc['id'])
        self.assert_current_preferences()

    def test_quiz_reads_current_preferences_without_embedding(self):
        Review(self.store, self.ai).generate(self.doc['id'])
        self.assert_current_preferences()
