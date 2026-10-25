import hashlib
import tempfile
import unittest
import os
from unittest.mock import patch
from pathlib import Path

from backend.mem0_engine import Mem0Engine
from backend.provider import Provider
from backend.store import Store


class ModelFixture(Provider):
    """Only external models are substituted; mem0 and its databases are real."""
    def __init__(self):
        super().__init__({'base_url': 'http://127.0.0.1:1/v1', 'model': 'fixture-llm', 'embedding_model': 'fixture-embedding'}, 'test-key')
        self.extractions = 0
        self.fail = False

    def request(self, endpoint, payload, embedding=False):
        if self.fail:
            raise ValueError('模拟模型暂时不可用')
        if embedding:
            return {'data': [{'index': i, 'embedding': [1., float('closure' in t.lower()), float('decorator' in t.lower()), .1]}
                             for i, t in enumerate(payload['input'])]}
        self.extractions += 1
        raw = payload['messages'][-1]['content']
        fact = 'A decorator wraps a function and can use a closure.' if 'decorator' in raw.lower() else 'A closure captures outer function variables.'
        import json
        return {'choices': [{'message': {'content': json.dumps({'memory': [{'text': fact}]})}}]}


class RealMem0Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.engine = Mem0Engine(self.store)
        self.provider = ModelFixture()

    def tearDown(self):
        self.engine.close()
        self.store.close()
        self.tmp.cleanup()

    def add_sources(self):
        a = self.store.add_document('Closure basics', 'A closure captures outer function variables. ' * 5)
        b = self.store.add_document('Decorator tutorial', 'A decorator wraps a function and can use a closure. ' * 5)
        return a, b

    def test_actual_upstream_source_matches_downloaded_copy(self):
        import mem0.memory.main
        upstream = Path(__file__).resolve().parents[1] / 'vendor/mem0/mem0/memory/main.py'
        installed = Path(mem0.memory.main.__file__)
        self.assertEqual(hashlib.sha256(upstream.read_bytes()).digest(), hashlib.sha256(installed.read_bytes()).digest())

    def test_extraction_cross_tutorial_search_and_provenance(self):
        a, b = self.add_sources()
        result = self.engine.sync(self.provider)
        self.assertEqual(result['knowledge_count'], 2)
        self.assertEqual(self.provider.extractions, 2)
        found = self.engine.recall('closure decorator', self.provider, exclude_document_id=a['id'])
        self.assertTrue(found)
        self.assertEqual(found[0]['document_id'], b['id'])
        self.assertEqual(found[0]['retrieval'], 'mem0')
        self.assertTrue(found[0]['facts'])
        self.assertIn(found[0]['id'], {s['id'] for s in self.store.segments(b['id'])})

    def test_restart_and_repeat_sync_do_not_extract_again(self):
        self.add_sources()
        self.engine.sync(self.provider)
        self.engine.close()
        self.engine = Mem0Engine(self.store)
        self.provider.extractions = 0
        self.engine.sync(self.provider)
        self.assertEqual(self.provider.extractions, 0)
        self.assertEqual(self.engine.status(self.provider)['knowledge_count'], 2)

    def test_deleted_and_edited_sources_are_not_recalled(self):
        a, b = self.add_sources()
        self.engine.sync(self.provider)
        self.store.delete_document(b['id'])
        self.engine.prune()
        found = self.engine.recall('decorator', self.provider)
        self.assertTrue(all(s['document_id'] != b['id'] for s in found))
        self.assertEqual(self.engine.status(self.provider)['knowledge_count'], 1)

    def test_preferences_are_not_vector_sync_entities(self):
        self.store.save_memory('讲解偏好', '先给例子')
        self.assertEqual(self.engine.entities(), {})
        self.assertEqual(self.engine.status(self.provider)['pending'], 0)

    def test_native_adapter_does_not_construct_unused_sdk_proxy_clients(self):
        self.add_sources()
        with patch.dict(os.environ, {'NO_PROXY': '[::1]', 'no_proxy': '[::1]'}):
            self.assertEqual(self.engine.sync(self.provider)['knowledge_count'], 2)
            self.assertEqual(os.environ['NO_PROXY'], '[::1]')

    def test_upgrade_removes_legacy_personal_vectors_but_keeps_preferences(self):
        from backend.mem0_engine import USER, digest
        preference = self.store.save_memory('讲解偏好', '先给例子')
        name, native = self.engine._get(self.provider)
        key = 'personal:' + preference['id']
        added = native.add('先给例子', user_id=USER, agent_id=key,
                           metadata={'lane': 'personal', 'workspace': 'default'}, infer=False)
        with self.store.db:
            self.store.db.execute('INSERT INTO mem0_sync VALUES(?,?,?,?,?)', (name, key, digest(preference), 'done', 'old'))
            for item in added['results']:
                self.store.db.execute('INSERT INTO mem0_links VALUES(?,?,?)', (name, key, item['id']))
        self.engine.close()
        self.engine = Mem0Engine(self.store)
        _, reopened = self.engine._get(self.provider)
        self.assertEqual(reopened.get_all(filters={'user_id': USER, 'agent_id': key})['results'], [])
        self.assertEqual(reopened.db.connection.execute('SELECT COUNT(*) FROM history').fetchone()[0], 0)
        self.assertEqual(len(self.store.memories()), 1)

    def test_failed_model_is_retryable(self):
        self.add_sources()
        self.provider.fail = True
        with self.assertRaises(Exception):
            self.engine.sync(self.provider)
        self.provider.fail = False
        result = self.engine.sync(self.provider)
        self.assertEqual(result['knowledge_count'], 2)

    def test_requires_embedding_instead_of_mocking_semantic_memory(self):
        self.provider.settings['embedding_model'] = ''
        with self.assertRaisesRegex(ValueError, 'Embedding'):
            self.engine.sync(self.provider)

    def test_semantic_recall_works_without_keyword_overlap(self):
        from backend.knowledge import Knowledge
        self.add_sources()
        self.engine.sync(self.provider)
        self.assertEqual(self.store.search('捕获环境的包装器'), [])
        found = Knowledge(self.store, self.provider, None, self.engine).search('捕获环境的包装器')
        self.assertTrue(found['results'])
        self.assertEqual(found['results'][0]['retrieval'], 'mem0')

    def test_changing_embedding_model_has_separate_namespace(self):
        self.add_sources()
        self.engine.sync(self.provider)
        self.provider.settings['embedding_model'] = 'another-model'
        status = self.engine.status(self.provider)
        self.assertEqual(status['knowledge_count'], 0)
        self.assertEqual(status['pending'], 2)
        self.engine.sync(self.provider)
        self.assertEqual(self.engine.status(self.provider)['knowledge_count'], 2)

    def test_fact_embedding_failure_is_not_reported_as_success(self):
        self.store.add_document('Closure basics', 'A closure captures outer function variables. ' * 5)
        original = self.provider.request
        def fail_fact(endpoint, payload, embedding=False):
            if embedding and any(t == 'A closure captures outer function variables.' for t in payload['input']):
                raise ValueError('模拟事实向量化失败')
            return original(endpoint, payload, embedding)
        self.provider.request = fail_fact
        with self.assertRaises(Exception):
            self.engine.sync(self.provider)
        self.assertEqual(self.engine.status(self.provider)['pending'], 1)
        self.provider.request = original
        self.assertEqual(self.engine.sync(self.provider)['knowledge_count'], 1)

    def test_delete_purges_native_messages_and_fact_history(self):
        doc = self.store.add_document('Closure basics', 'A closure captures outer function variables. ' * 5)
        self.engine.sync(self.provider)
        native = next(iter(self.engine.instances.values()))
        self.assertGreater(native.db.connection.execute('SELECT COUNT(*) FROM messages').fetchone()[0], 0)
        self.engine.remove(['segment:' + s['id'] for s in self.store.segments(doc['id'])])
        self.store.delete_document(doc['id'])
        self.assertEqual(native.db.connection.execute('SELECT COUNT(*) FROM messages').fetchone()[0], 0)
        self.assertEqual(native.db.connection.execute('SELECT COUNT(*) FROM history').fetchone()[0], 0)

    def test_ai_association_keeps_keyword_fallback_without_embedding(self):
        from backend.knowledge import Knowledge
        a, _ = self.add_sources()
        self.provider.settings['embedding_model'] = ''
        self.provider.json = lambda *args: {'related': True, 'kind': 'shared', 'reason': '两份资料都涉及 closure'}
        result = Knowledge(self.store, self.provider, None, self.engine).related(a['id'], use_ai=True)
        self.assertTrue(result)
        self.assertIn('关键词', result[0]['reason'])
