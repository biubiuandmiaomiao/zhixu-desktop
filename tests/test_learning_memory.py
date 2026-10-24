import tempfile
import unittest

from backend.mem0_engine import Mem0Engine
from backend.store import Store, now, uid
from tests.test_mem0_engine import ModelFixture


class LearningMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.engine = Mem0Engine(self.store)
        self.provider = ModelFixture()
        self.a = self.store.add_document('Closure', 'A closure captures variables. ' * 10)
        self.b = self.store.add_document('Decorator', 'A decorator wraps functions. ' * 10)
        self.sa, self.sb = [self.store.segments(d['id'])[0]['id'] for d in (self.a, self.b)]

    def tearDown(self):
        self.engine.close()
        self.store.close()
        self.tmp.cleanup()

    def seed_events(self):
        relation = self.store.suggest_relation(self.a['id'], self.b['id'], 'prerequisite',
                                              'Closure is a prerequisite for this decorator example.', [self.sa, self.sb])
        self.store.set_relation(relation['id'], 'confirmed')
        question = {'id': uid(), 'type': 'short', 'prompt': 'How does a closure keep captured variables?',
                    'source_ids': [self.sa], 'score': 4, 'feedback': '本次回答遗漏了生命周期。',
                    'answer': [], 'explanation': 'REFERENCE_ANSWER_MUST_NOT_BE_INDEXED', 'rubric': ['lifetime']}
        session = {'id': uid(), 'title': 'Closure review', 'status': 'completed', 'created_at': now(),
                   'completed_at': now(), 'questions': [question], 'answers': {question['id']: 'I think they disappear.'},
                   'sources': self.store.segments(self.a['id']), 'score': 4}
        self.store.save_session(session)
        self.store.add_conversation('When is a closure released?', 'UNVERIFIED_AI_ANSWER_MUST_NOT_BE_INDEXED',
                                    self.store.segments(self.a['id']))
        return relation, session

    def test_snapshots_include_confirmed_relation_completed_review_and_question_only(self):
        self.seed_events()
        events = [e for e in self.engine.entities().values() if e['metadata']['lane'] != 'knowledge']
        self.assertEqual({e['metadata']['lane'] for e in events}, {'relation', 'review', 'conversation'})
        self.assertEqual(len(events), 3)
        for event in events:
            self.assertTrue(event['metadata']['source_ids'])
            self.assertTrue(event['metadata']['created_at'])
            self.assertNotIn('UNVERIFIED_AI_ANSWER', event['text'])
            self.assertNotIn('REFERENCE_ANSWER', event['text'])
        review = next(e for e in events if e['metadata']['lane'] == 'review')
        self.assertIn('4/10', review['text'])
        self.assertIn('本次', review['text'])

    def test_drafts_and_unconfirmed_relations_are_not_indexed(self):
        relation, session = self.seed_events()
        session['status'] = 'draft'
        self.store.save_session(session)
        self.store.set_relation(relation['id'], 'rejected')
        events = [e for e in self.engine.entities().values() if e['metadata']['lane'] != 'knowledge']
        self.assertEqual([e['metadata']['lane'] for e in events], ['conversation'])

    def test_real_mem0_event_recall_is_lossless_and_survives_restart(self):
        self.seed_events()
        self.assertIn('learning_count', self.engine.status(self.provider))
        result = self.engine.sync(self.provider, learning_only=True)
        self.assertEqual(result['learning_count'], 3)
        self.assertEqual(self.provider.extractions, 0)
        found = self.engine.learning_context('词面不重合的学习困惑', self.provider, [self.sa, self.sb])
        self.assertEqual({e['kind'] for e in found}, {'relation', 'review', 'conversation'})
        before = {e['id'] for e in found}
        self.engine.close()
        self.engine = Mem0Engine(self.store)
        self.engine.sync(self.provider, learning_only=True)
        self.assertEqual(before, {e['id'] for e in self.engine.learning_context('closure', self.provider, [self.sa, self.sb])})

    def test_scope_is_filtered_before_top_k_and_old_questions_remain_retrievable(self):
        self.seed_events()
        for i in range(30):
            self.store.add_conversation('Unrelated decorator question ' + str(i), 'unused', self.store.segments(self.b['id']))
        self.assertIn('learning_count', self.engine.status(self.provider))
        self.engine.sync(self.provider, learning_only=True, limit=50)
        found = self.engine.learning_context('closure', self.provider, [self.sa])
        self.assertEqual({e['kind'] for e in found}, {'review', 'conversation'})
        self.assertTrue(all(set(e['source_ids']) <= {self.sa} for e in found))

    def test_pending_rejected_and_deleted_events_are_not_recalled(self):
        relation, session = self.seed_events()
        self.assertIn('learning_count', self.engine.status(self.provider))
        self.engine.sync(self.provider, learning_only=True)
        self.store.set_relation(relation['id'], 'rejected')
        # A stale or partially persisted update must not be used as complete memory.
        with self.store.db:
            self.store.db.execute("UPDATE mem0_sync SET status='pending' WHERE entity LIKE 'review:%'")
        found = self.engine.learning_context('closure', self.provider, [self.sa, self.sb])
        self.assertEqual([e['kind'] for e in found], ['conversation'])
        self.store.delete_document(self.a['id'])
        self.engine.prune()
        self.assertEqual(self.engine.learning_context('closure', self.provider, [self.sb]), [])
        self.assertEqual(self.engine.status(self.provider)['learning_count'], 0)

    def test_event_embedding_failure_stays_pending_then_retries(self):
        self.seed_events()
        self.assertIn('learning_count', self.engine.status(self.provider))
        self.engine._get(self.provider)
        self.provider.fail = True
        with self.assertRaises(ValueError):
            self.engine.sync(self.provider, learning_only=True)
        self.assertEqual(self.engine.status(self.provider)['learning_count'], 0)
        self.provider.fail = False
        self.assertEqual(self.engine.sync(self.provider, learning_only=True)['learning_count'], 3)

    def test_service_delete_clears_memories_of_entire_quiz_snapshot(self):
        from backend.service import Service
        from backend.mem0_engine import USER
        _, session = self.seed_events()
        session['sources'] += self.store.segments(self.b['id'])
        self.store.save_session(session)
        self.engine.sync(self.provider, learning_only=True)
        self.engine.close()
        service = Service(self.tmp.name)
        try:
            service.dispatch('delete_document', {'id': self.b['id']})
            _, native = service.mem0._get(self.provider)
            self.assertEqual(native.get_all(filters={'user_id': USER, 'lane': 'review'})['results'], [])
            self.assertEqual(service.mem0.status(self.provider)['conversation_count'], 1)
        finally:
            service.close()
