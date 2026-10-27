import tempfile
import unittest
from unittest.mock import patch

from backend.knowledge import Knowledge
from backend.review import Review
from backend.store import Store
from tests.test_review import FixtureAI
from tests.test_mem0_engine import ModelFixture
from backend.mem0_engine import Mem0Engine


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

    def test_follow_up_history_is_carried_as_bounded_context(self):
        rounds = [{'question': f'第{i}轮问题', 'answer': f'第{i}轮回答'} for i in range(1, 6)]
        Knowledge(self.store, self.ai, None).ask('上面说的闭包生命周期，再讲一次？', self.doc['id'], history=rounds)
        conversation = self.ai.calls[-1][1]['conversation']
        self.assertEqual([turn['question'] for turn in conversation], ['第3轮问题', '第4轮问题', '第5轮问题'])
        self.assertIn('不是事实依据', self.ai.calls[-1][0])
        self.assert_current_preferences()

    def test_follow_up_history_rejects_malformed_rounds(self):
        for history in ([{'question': 1, 'answer': '回答'}], 'not a list', [{}] * 7):
            with self.subTest(history=history), self.assertRaises(ValueError):
                Knowledge(self.store, self.ai, None).ask('如何理解闭包？', self.doc['id'], history=history)
        self.assertEqual(self.ai.calls, [])

    def test_first_ask_omits_conversation_entirely(self):
        Knowledge(self.store, self.ai, None).ask('如何理解闭包？', self.doc['id'])
        self.assertNotIn('conversation', self.ai.calls[-1][1])

    def test_tutorial_reads_current_preferences_without_embedding(self):
        Knowledge(self.store, self.ai, None).tutorial(self.doc['id'])
        self.assert_current_preferences()

    def test_document_scope_keeps_answer_evidence_inside_selected_document(self):
        other = self.store.add_document('闭包补充', '闭包捕获外部变量，另一份资料的说明。' * 20)
        relation = self.store.suggest_relation(self.doc['id'], other['id'], 'supplement', '补充讲解')
        self.store.set_relation(relation['id'], 'confirmed')
        Knowledge(self.store, self.ai, None).ask('如何理解闭包？', self.doc['id'])
        self.assertTrue(all(s['document_id'] == self.doc['id'] for s in self.ai.calls[-1][1]['sources']))

    def test_quiz_reads_current_preferences_without_embedding(self):
        Review(self.store, self.ai).generate(self.doc['id'])
        self.assert_current_preferences()

    def model_with_events(self):
        self.store.add_conversation('闭包的变量何时释放？', 'UNVERIFIED_ANSWER', self.store.segments(self.doc['id']))
        provider = ModelFixture()
        provider.json = self.ai.json
        return provider

    def test_ask_recalls_history_using_real_mem0_separate_from_sources_and_preferences(self):
        provider = self.model_with_events()
        engine = Mem0Engine(self.store)
        try:
            result = Knowledge(self.store, provider, None, engine).ask('如何理解闭包？', self.doc['id'])
            self.assertGreater(result.get('learning_memory_count', 0), 0)
            payload = self.ai.calls[-1][1]
            self.assertEqual(payload['learning_memories'][0]['kind'], 'conversation')
            self.assertNotIn('UNVERIFIED_ANSWER', str(payload['learning_memories']))
            self.assert_current_preferences()
        finally:
            engine.close()

    def test_quiz_recalls_history_only_inside_selected_favorites(self):
        provider = self.model_with_events()
        self.store.add_card(self.doc['id'], self.doc['content'], self.ai.source_id)
        other = self.store.add_document('无关教程', '完全无关的内容。' * 40)
        self.store.add_conversation('无关的历史提问', 'unused', self.store.segments(other['id']))
        engine = Mem0Engine(self.store)
        try:
            quiz = Review(self.store, provider, engine).generate('__cards__')
            self.assertGreater(quiz.get('learning_memory_count', 0), 0)
            payload = self.ai.calls[-1][1]
            self.assertTrue(all(set(m['source_ids']) <= {self.ai.source_id} for m in payload['learning_memories']))
            self.assertTrue(all('answer' not in q and 'rubric' not in q for q in quiz['questions']))
            self.assert_current_preferences()
        finally:
            engine.close()

    def test_memory_failure_keeps_preferences_and_does_not_cancel_generation(self):
        provider = self.model_with_events()
        provider.fail = True
        engine = Mem0Engine(self.store)
        try:
            result = Knowledge(self.store, provider, None, engine).ask('如何理解闭包？')
            self.assertIn('学习记忆暂不可用', result['notice'])
            self.assert_current_preferences()
            quiz = Review(self.store, provider, engine).generate(self.doc['id'])
            self.assertIn('学习记忆暂不可用', quiz['memory_notice'])
            self.assert_current_preferences()
        finally:
            engine.close()

    def test_slow_learning_calls_leave_time_for_generation(self):
        provider = self.model_with_events()
        elapsed = [0.0]
        request, generate = provider.request, provider.json
        def slow_request(*args, **kwargs):
            elapsed[0] += 90
            return request(*args, **kwargs)
        def slow_generate(*args, **kwargs):
            elapsed[0] += 90
            return generate(*args, **kwargs)
        provider.request, provider.json = slow_request, slow_generate
        engine = Mem0Engine(self.store)
        try:
            with patch('time.monotonic', side_effect=lambda: elapsed[0]):
                quiz = Review(self.store, provider, engine).generate(self.doc['id'])
            self.assertLess(elapsed[0], 300, 'Optional learning memory exhausted the Electron request deadline')
            self.assertIn('学习记忆暂不可用', quiz['memory_notice'])
            self.assertEqual(len(quiz['questions']), 10)
        finally:
            engine.close()
