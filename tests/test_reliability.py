import tempfile
import unittest

from backend.store import Store
from backend.review import Review, ReviewError
from backend.knowledge import Knowledge
from backend.provider import Provider
from backend.vectors import VectorIndex
from tests.test_review import FixtureAI


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_text_edit_refreshes_search_and_invalidates_old_quiz(self):
        doc = self.store.add_document('变量', '闭包保存外层变量。' * 40)
        ai = FixtureAI(self.store.segments(doc['id'])[0]['id'])
        Review(self.store, ai).generate()
        self.store.update_document(doc['id'], '类与继承', '继承允许子类复用父类的方法。' * 30)
        self.assertEqual(self.store.search('闭包'), [])
        self.assertEqual(self.store.search('继承')[0]['document_id'], doc['id'])
        self.assertEqual(self.store.sessions(), [])

    def test_invalid_option_returns_validation_error(self):
        review = Review(self.store, None)
        questions = FixtureAI('source').json('questions', {})
        questions['questions'][0]['options'][0]['id'] = None
        with self.assertRaises(ReviewError):
            review.validate(questions, {'source'}, set())

    def test_new_session_draft_is_restored_after_database_reopen(self):
        doc = self.store.add_document('闭包教程', '闭包保存外层变量。' * 40)
        ai = FixtureAI(self.store.segments(doc['id'])[0]['id'])
        review = Review(self.store, ai)
        quiz = review.generate()
        first = next(q for q in quiz['questions'] if q['type'] == 'single')
        review.draft(quiz['id'], {first['id']: ['A']})
        self.store.close()
        self.store = Store(self.tmp.name)
        self.assertEqual(Review(self.store, ai).get(quiz['id'])['answers'][first['id']], ['A'])

    def test_local_vectors_roundtrip_and_remove(self):
        doc = self.store.add_document('闭包', '闭包捕获外部变量。')
        class Embed:
            settings = {'embedding_model': 'fixture-only'}
            def embed(self, texts):
                return [[1., .5, .2] for _ in texts]
        index = VectorIndex(self.store)
        try:
            self.assertEqual(index.build(Embed())['indexed'], 1)
            found = index.search('闭包', Embed())
            self.assertEqual(found[0]['document_id'], doc['id'])
            index.remove([found[0]['id']])
            self.assertEqual(index.search('闭包', Embed()), [])
        finally:
            index.close()

    def test_no_credentials_does_not_make_network_call(self):
        provider = Provider({'base_url': 'https://example.invalid/v1', 'model': 'fixture'})
        with self.assertRaisesRegex(ValueError, 'API Key'):
            provider.json('system', {})

    def test_forged_citations_are_not_saved(self):
        self.store.add_document('闭包', '闭包捕获变量')
        class Fake:
            settings = {}
            api_key = ''
            def json(self, *args):
                return {'answer': '错误引用', 'source_ids': ['does-not-exist']}
        with self.assertRaisesRegex(ValueError, '引用'):
            Knowledge(self.store, Fake(), None).ask('闭包')
        self.assertEqual(self.store.conversations(), [])

    def test_favorites_scope_uses_only_saved_excerpts(self):
        doc = self.store.add_document('闭包', '闭包捕获变量。其他不希望出题的内容。' * 30)
        segment = self.store.segments(doc['id'])[0]
        self.store.add_card(doc['id'], '闭包捕获变量。', segment['id'])
        sources = self.store.sample_sources('__cards__')
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]['text'], '闭包捕获变量。')

    def test_delete_clears_unused_sampled_source_from_quiz_snapshot(self):
        used = self.store.add_document('闭包教程', '闭包保存外层变量。' * 40)
        unused = self.store.add_document('其他笔记', '这是不应该在删除后继续保留的资料。' * 20)
        review = Review(self.store, FixtureAI(self.store.segments(used['id'])[0]['id']))
        quiz = review.generate()
        self.assertTrue(any(s['document_id'] == unused['id'] for s in quiz['sources']))
        self.store.delete_document(unused['id'])
        self.assertEqual(self.store.sessions(), [])

    def test_long_tutorial_does_not_hide_other_related_documents(self):
        a = self.store.add_document('Closure decorators variables functions', 'Closure decorators variables functions. ' * 260)
        b = self.store.add_document('Decorators tutorial', ('decorators use closure variables functions. ' + 'other ' * 70) * 20)
        provider = Provider({})
        related = Knowledge(self.store, provider, None).related(a['id'])
        self.assertTrue(any(b['id'] in (r['a'], r['b']) for r in related))

    def test_delete_only_removes_conversations_using_that_source(self):
        a = self.store.add_document('闭包', '闭包保存变量')
        b = self.store.add_document('继承', '继承复用父类')
        self.store.add_conversation('闭包问题', '闭包回答', self.store.segments(a['id']))
        self.store.add_conversation('继承问题', '继承回答', self.store.segments(b['id']))
        self.store.delete_document(a['id'])
        self.assertEqual([c['question'] for c in self.store.conversations()], ['继承问题'])

    def test_inline_citation_must_match_displayed_source_numbers(self):
        doc = self.store.add_document('闭包', '闭包捕获变量')
        source_id = self.store.segments(doc['id'])[0]['id']
        class Fake:
            settings = {}
            api_key = ''
            def json(self, *args):
                return {'answer': '闭包捕获外部变量。[99]', 'source_ids': [source_id]}
        with self.assertRaisesRegex(ValueError, '引用'):
            Knowledge(self.store, Fake(), None).ask('闭包')
        self.assertEqual(self.store.conversations(), [])
