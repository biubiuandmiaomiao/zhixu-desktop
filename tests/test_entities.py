import json
import tempfile
import unittest

from backend.entities import (_validate_entities, build_index, describe, entity_similarity,
                              extract_entities, index_document, normalize_entity, normalize_entity_kind,
                              shared_entities, temporal_weight)
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
        self.assertGreater(relation['score'], 0)
        self.assertEqual(relation['proof'], len(relation['entities']))
        self.assertEqual(relation['top_entity'], relation['entities'][0]['name'])
        self.assertEqual({row['side'] for row in relation['evidence']}, {'a', 'b'})
        self.assertTrue(all(row['quote'] for row in relation['evidence']))
        # No LLM call was made: entity relations are deterministic.
        self.assertEqual(knowledge.provider.calls, [])

    def test_relation_strength_refines_instead_of_regressing(self):
        a = add_doc_with_entities(self.store, 'A', '闭包与装饰器。', ['闭包', '装饰器'])
        b = add_doc_with_entities(self.store, 'B', '闭包与装饰器。', ['闭包', '装饰器'])
        first = self.store.suggest_relation(a['id'], b['id'], 'shared', '初次', score=1.2, proof=2, top_entity='闭包')
        second = self.store.suggest_relation(a['id'], b['id'], 'shared', '再次', score=3.4, proof=3, top_entity='装饰器')
        self.assertEqual(first['id'], second['id'])
        relation = next(row for row in self.store.relations(a['id']) if row['id'] == first['id'])
        self.assertEqual(relation['score'], 3.4)
        self.assertEqual(relation['proof'], 3)
        self.assertEqual(relation['top_entity'], '装饰器')

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

    def test_causal_and_contrast_relations_keep_direction(self):
        a = add_doc_with_entities(self.store, 'Z 原因', '闭包导致作用域捕获。', ['闭包'])
        b = add_doc_with_entities(self.store, 'A 结果', '作用域捕获带来内存占用。', ['内存占用'])
        relation = self.store.suggest_relation(a['id'], b['id'], 'causes', 'A 的机制导致 B 的现象')
        self.assertEqual((relation['a'], relation['b']), (a['id'], b['id']))
        contrast = self.store.suggest_relation(a['id'], b['id'], 'contrast', '两种取舍')
        self.assertEqual((contrast['a'], contrast['b']), (a['id'], b['id']))
        shared = self.store.suggest_relation(a['id'], b['id'], 'shared', '同概念')
        self.assertEqual((shared['a'], shared['b']), tuple(sorted((a['id'], b['id']))))
        with self.assertRaisesRegex(ValueError, '关系'):
            self.store.suggest_relation(a['id'], b['id'], 'related_to', '未定义类型')

    def test_hub_entity_needs_higher_similarity_to_merge(self):
        hub_doc = self.store.add_document('中枢文档', 'DeepSeek-V3 与很多概念一起出现。')
        segment = self.store.segments(hub_doc['id'])[0]
        hub_id = self.store.upsert_entity('DeepSeek-V3', 'product')
        self.store.add_entity_mention(hub_id, hub_doc['id'], segment['id'], 'DeepSeek-V3')
        for index in range(10):
            partner_id = self.store.upsert_entity(f'伙伴概念{index}', 'concept')
            self.store.add_entity_mention(partner_id, hub_doc['id'], segment['id'], '伙伴')
        self.assertGreaterEqual(self.store.entity_partner_count(hub_id), 10)
        merged = self.store.upsert_entity('DeepSeek V3', 'product')
        self.assertNotEqual(merged, hub_id)

    def test_force_rebuild_reindexes_an_already_indexed_document(self):
        document = self.store.add_document('智能体', '评估不足会导致智能体反复犯错。')
        provider = FakeProvider(answer={'entities': [
            {'name': '评估', 'type': 'concept', 'quote': '评估不足'},
            {'name': '智能体', 'type': 'concept', 'quote': '智能体反复犯错'},
        ], 'links': [{'from': '评估', 'to': '智能体', 'kind': 'causes', 'quote': '评估不足会导致智能体反复犯错'}]})
        build_index(self.store, provider, document['id'])
        ids = [row['entity_id'] for row in self.store.document_entities(document['id'])]
        self.assertEqual(len(self.store.entity_links_between(ids)), 1)
        build_index(self.store, provider, document['id'], force=True)
        self.assertEqual(len(provider.calls), 2)
        ids = [row['entity_id'] for row in self.store.document_entities(document['id'])]
        # Replacing mentions/links must not duplicate rows.
        self.assertEqual(len(self.store.entity_links_between(ids)), 1)
        self.assertEqual(len(self.store.document_entities(document['id'])), 2)

    def test_indexed_document_drops_stale_keyword_suggestions(self):
        a = add_doc_with_entities(self.store, '闭包教程', '闭包捕获外部变量。', ['闭包'])
        b = add_doc_with_entities(self.store, '装饰器教程', '装饰器本质是闭包。', ['闭包'])
        add_doc_with_entities(self.store, 'C 无关1', '篮球。', ['篮球'])
        add_doc_with_entities(self.store, 'D 无关2', '投资。', ['投资'])
        stale = self.store.suggest_relation(a['id'], b['id'], 'shared', '关键词候选：共同出现 这些、可以。（旧逻辑）')
        keep = self.store.suggest_relation(a['id'], b['id'], 'supplement', '关键词召回 + AI 建议：有实质补充')
        self.store.set_relation(keep['id'], 'confirmed')
        Knowledge(self.store, FakeProvider(), None).related(a['id'], use_ai=False)
        remaining = self.store.relations(a['id'])
        ids = {row['id'] for row in remaining}
        # The stale suggestion is either deleted or upgraded in place: no keyword text
        # survives once real entity evidence exists.
        self.assertFalse([row for row in remaining if str(row['reason']).startswith('关键词候选')])
        self.assertIn(keep['id'], ids)

    def test_causal_links_are_validated_and_persisted(self):
        document = self.store.add_document('智能体', '评估不足会导致智能体反复犯错。')
        provider = FakeProvider(answer={'entities': [
            {'name': '评估', 'type': 'concept', 'quote': '评估不足'},
            {'name': '智能体', 'type': 'concept', 'quote': '智能体反复犯错'},
        ], 'links': [
            {'from': '评估', 'to': '智能体', 'kind': 'causes', 'quote': '评估不足会导致智能体反复犯错'},
            {'from': '评估', 'to': '智能体', 'kind': '猜测', 'quote': '评估不足会导致智能体反复犯错'},
            {'from': '评估', 'to': '不存在', 'kind': 'causes', 'quote': '评估不足会导致智能体反复犯错'},
            {'from': '评估', 'to': '智能体', 'kind': 'enables', 'quote': '原文没有这句'},
        ]})
        # extract_entities returns the validated links, index_document persists them.
        extracted = extract_entities(provider, document['title'], document['content'])
        self.assertEqual(len(extracted['links']), 1)
        index_document(self.store, provider, document)
        links = self.store.entity_links_between([row['entity_id'] for row in self.store.document_entities(document['id'])])
        self.assertEqual([(link['kind'], link['a_name'], link['b_name']) for link in links],
                         [('causes', '评估', '智能体')])
        self.assertIn('会导致', links[0]['quote'])

    def test_temporal_weight_follows_the_24_hour_window(self):
        a = add_doc_with_entities(self.store, 'A', '闭包捕获外部变量。', ['闭包'])
        b = add_doc_with_entities(self.store, 'B', '闭包决定作用域。', ['闭包'])
        entity_id = self.store.document_entities(a['id'])[0]['entity_id']
        with self.store.db:
            self.store.db.execute("UPDATE documents SET created_at=? WHERE id=?", ('2026-10-30T10:00:00+00:00', a['id']))
            self.store.db.execute("UPDATE documents SET created_at=? WHERE id=?", ('2026-10-30T12:00:00+00:00', b['id']))
        weight = temporal_weight(self.store, [entity_id], a['id'], b['id'])
        self.assertAlmostEqual(weight, 1 - 2 / 24, places=3)
        with self.store.db:
            self.store.db.execute("UPDATE documents SET created_at=? WHERE id=?", ('2026-11-05T10:00:00+00:00', b['id']))
        self.assertEqual(temporal_weight(self.store, [entity_id], a['id'], b['id']), 0.0)

    def test_related_prefers_an_extracted_causal_link(self):
        a = add_doc_with_entities(self.store, 'A 原因', '评估不足会导致智能体反复犯错。', ['评估', '智能体'])
        b = add_doc_with_entities(self.store, 'B 结果', '智能体的评估循环需要人工检查。', ['智能体'])
        # Two more notes so 智能体 is a meaningful (not ubiquitous) shared entity.
        add_doc_with_entities(self.store, 'C 无关1', '篮球比赛。', ['篮球'])
        add_doc_with_entities(self.store, 'D 无关2', '投资建议。', ['投资'])
        entities = {row['name']: row['entity_id'] for row in self.store.document_entities(a['id'])}
        self.store.add_entity_link(entities['评估'], entities['智能体'], 'causes',
                                   '评估不足会导致智能体反复犯错', a['id'],
                                   self.store.segments(a['id'])[0]['id'])
        relationships = Knowledge(self.store, FakeProvider(), None).related(a['id'], use_ai=False)
        relation = next(row for row in relationships if {row['a'], row['b']} == {a['id'], b['id']})
        self.assertEqual(relation['kind'], 'causes')
        self.assertIn('实体因果', relation['reason'])
        # Direction is preserved: the cause document stays first.
        self.assertEqual((relation['a'], relation['b']), (a['id'], b['id']))
        self.assertGreater(relation['score'], 0)


if __name__ == '__main__':
    unittest.main()
