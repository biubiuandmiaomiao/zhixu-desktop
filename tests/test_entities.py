import json
import tempfile
import unittest

from backend.entities import (_validate_entities, build_index, describe, entity_similarity,
                              index_document, normalize_entity, normalize_entity_kind, shared_entities)
from backend.knowledge import Knowledge
from backend.store import Store


class FakeProvider:
    settings = {'model': 'fixture'}
    api_key = 'fixture'

    def __init__(self, entities=None, answer=None):
        self.entities = entities or []
        self.answer = answer
        self.calls = []

    def json(self, system, payload):
        self.calls.append((system, payload))
        if self.answer is not None:
            return self.answer
        return {'entities': self.entities}


def add_doc_with_entities(store, title, text, entities, segment_text=None):
    document = store.add_document(title, text)
    segment = store.segments(document['id'])[0]
    for entity in entities:
        entity_id = store.upsert_entity(entity, 'concept')
        store.add_entity_mention(entity_id, document['id'], segment['id'], text[:80])
    return document


class NormalizationTests(unittest.TestCase):
    def test_whitespace_and_display_form(self):
        self.assertEqual(normalize_entity('  闭包    Closure  '), '闭包 Closure')
        self.assertEqual(normalize_entity('`闭包`'), '闭包')
        self.assertEqual(normalize_entity('   '), '')
        self.assertEqual(normalize_entity('！？。'), '')
        self.assertEqual(normalize_entity('x' * 100), '')
        self.assertEqual(normalize_entity_kind('unknown-kind'), 'concept')
        self.assertEqual(normalize_entity_kind('person'), 'person')

    def test_quote_must_appear_in_the_source(self):
        kept = _validate_entities([
            {'name': '闭包', 'type': 'concept', 'quote': '闭包捕获外部变量'},
            {'name': '幻觉实体', 'type': 'concept', 'quote': '原文里根本没有这句'},
            {'name': '没有引用', 'type': 'concept'},
            {'name': '闭包', 'type': 'concept', 'quote': '闭包捕获外部变量'},
        ], '闭包捕获外部变量，返回函数后仍保留引用。')
        self.assertEqual([entity['name'] for entity in kept], ['闭包'])

    def test_alias_resolution_returns_one_canonical_entity(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            first = store.upsert_entity('闭包', 'concept', ['closure'])
            second = store.upsert_entity('Closure', 'concept')
            third = store.upsert_entity('闭包 ', 'tech')
            self.assertEqual(len({first, second, third}), 1)
            store.close()

    def test_similarity_merges_spelling_variants_but_not_different_entities(self):
        self.assertEqual(entity_similarity('DeepSeek', 'deepseek'), 1.0)
        self.assertGreaterEqual(entity_similarity('DeepSeek-V3', 'DeepSeek V3'), 0.72)
        self.assertLess(entity_similarity('闭包', '闭包捕获外部变量'), 0.72)
        # Different surnames must never merge: tokens disagree, digits conflict.
        self.assertEqual(entity_similarity('John Smith', 'Jane Smith'), 0.0)
        self.assertEqual(entity_similarity('GPT-4', 'GPT-5'), 0.0)

    def test_upsert_merges_near_identical_spelling_into_one_entity_with_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            first = store.upsert_entity('DeepSeek-V3', 'product')
            second = store.upsert_entity('DeepSeek V3', 'product')
            self.assertEqual(first, second)
            self.assertEqual(len(store.rows('SELECT * FROM entities')), 1)
            self.assertEqual(len(store.rows('SELECT * FROM entity_aliases')), 1)
            store.close()


class SharedEntityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_rare_shared_entity_links_documents_and_common_one_does_not(self):
        a = add_doc_with_entities(self.store, '闭包教程', '闭包捕获外部变量。', ['闭包', '学习'])
        b = add_doc_with_entities(self.store, '装饰器教程', '装饰器依赖闭包。', ['闭包', '学习'])
        c = add_doc_with_entities(self.store, '无关教程', '篮球比赛。', ['学习'])
        candidates = shared_entities(self.store, a['id'])
        by_doc = {row['document_id']: row for row in candidates}
        # 闭包 appears in 2 of 3 documents -> real signal; 学习 appears in all 3 -> no signal.
        self.assertIn(b['id'], by_doc)
        self.assertNotIn(c['id'], by_doc)
        names = [entity['name'] for entity in by_doc[b['id']]['entities']]
        self.assertEqual(names, ['闭包'])

    def test_related_uses_entities_and_records_evidence_and_entities(self):
        a = add_doc_with_entities(self.store, '闭包教程', '闭包捕获外部变量。装饰器使用闭包。', ['闭包', '装饰器'])
        b = add_doc_with_entities(self.store, '装饰器教程', '装饰器本质是闭包。', ['装饰器'])
        self.store.add_document('篮球', '完全无关的体育内容。')
        knowledge = Knowledge(self.store, FakeProvider(), None)
        relations = knowledge.related(a['id'], use_ai=False)
        self.assertTrue(relations)
        relation = next(row for row in relations if {row['a'], row['b']} == {a['id'], b['id']})
        self.assertIn('共同实体', relation['reason'])
        self.assertTrue(relation['entities'])
        self.assertEqual(len(relation['evidence']), 2)
        # No LLM call was made: entity relations are deterministic.
        self.assertEqual(knowledge.provider.calls, [])

    def test_build_index_is_bounded_and_reports_counts(self):
        documents = [self.store.add_document(f'资料 {i}', '闭包捕获外部变量。') for i in range(3)]
        provider = FakeProvider([{'name': '闭包', 'type': 'concept', 'quote': '闭包捕获外部变量'}])
        result = build_index(self.store, provider, limit=2)
        self.assertEqual(len(result['documents']), 2)
        self.assertEqual(result['entities'], 2)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(len(self.store.entity_index_counts()), 2)

    def test_index_document_drops_entities_without_locatable_evidence(self):
        document = self.store.add_document('闭包', '闭包捕获外部变量，返回函数后仍保留引用。')
        provider = FakeProvider([{'name': '闭包', 'type': 'concept', 'quote': '闭包捕获外部变量'},
                                 {'name': '虚构', 'type': 'concept', 'quote': '不存在的句子'}])
        count = index_document(self.store, provider, document)
        self.assertEqual(count, 1)
        self.assertEqual([row['name'] for row in self.store.document_entities(document['id'])], ['闭包'])

    def test_question_naming_an_entity_pulls_evidence_from_other_notes(self):
        a = add_doc_with_entities(self.store, '闭包教程', '闭包捕获外部变量，需要关注生命周期。', ['闭包'])
        b = add_doc_with_entities(self.store, '装饰器教程', '装饰器本质是闭包，闭包决定作用域。', ['闭包'])
        provider = FakeProvider()
        captured = {}

        def fake_json(system, payload):
            captured.update(payload)
            return {'answer': '闭包捕获外部变量。[1]', 'source_ids': [payload['sources'][0]['id']]}
        provider.json = fake_json
        questions = {}
        Knowledge(self.store, provider, None).ask('闭包的作用域是怎么决定的？', a['id'])
        document_ids = {source['document_id'] for source in captured['sources']}
        self.assertIn(b['id'], document_ids)
        relation_sources = [source for source in captured['sources'] if source.get('retrieval') == '实体关联']
        self.assertTrue(relation_sources)

    def test_confirmed_relation_brings_other_notes_evidence_into_answers(self):
        a = add_doc_with_entities(self.store, '闭包教程', '闭包捕获外部变量。装饰器使用闭包。', ['闭包'])
        b = add_doc_with_entities(self.store, '装饰器教程', '装饰器本质是闭包，闭包决定作用域。', ['闭包'])
        relation = self.store.suggest_relation(a['id'], b['id'], 'shared', '共同实体：闭包')
        entity_id = self.store.document_entities(a['id'])[0]['entity_id']
        self.store.set_relation_entities(relation['id'], [entity_id])
        self.store.set_relation(relation['id'], 'confirmed')
        provider = FakeProvider(answer={'answer': '闭包捕获外部变量。[1]', 'source_ids': []})
        captured = {}

        def fake_json(system, payload):
            captured.update(payload)
            return {'answer': '闭包捕获外部变量。[1]', 'source_ids': [payload['sources'][0]['id']]}
        provider.json = fake_json
        result = Knowledge(self.store, provider, None).ask('闭包是什么？', a['id'])
        document_ids = {source['document_id'] for source in captured['sources']}
        self.assertIn(b['id'], document_ids)
        self.assertTrue(result['citations'])


if __name__ == '__main__':
    unittest.main()
