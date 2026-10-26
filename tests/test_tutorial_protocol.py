import json
import tempfile
import unittest
from types import SimpleNamespace

from backend.knowledge import Knowledge, _tutorial_evidence
from backend.store import Store


class TutorialProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.doc = self.store.add_document('计划', '模型负责生成计划，应用负责执行计划。', segments=[
            {'text': '模型负责生成计划，应用负责执行计划。', 'start': 12.5},
            {'text': '将计划转为结构化数据，可以检查每步的工具和参数。', 'start': 30.0}])
        self.sources = self.store.segments(self.doc['id'])
        self.frames = [{'id':'actual-frame-id','start':12.5,'data_url':'data:image/jpeg;base64,YQ=='}]

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def section(self, **changes):
        return {'heading':'概述','content':'模型生成计划，程序执行工具；可通过结构化数据检查工具和参数。' * 3,
                'source_ids':['S1'], 'frame_ids':['F1'], **changes}

    def run_model(self, results):
        calls = []
        def respond(system, payload, **kwargs):
            calls.append(payload)
            return results[min(len(calls)-1, len(results)-1)]
        result = Knowledge(self.store, SimpleNamespace(json=respond), None).tutorial(
            self.doc['id'], images=self.frames, use_images=True)
        return result, calls

    def test_program_renders_source_and_frame_fields_without_model_uuid_copying(self):
        result, calls = self.run_model([{'sections':[self.section()]}])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['sources'][0]['ref'], 'S1')
        self.assertEqual(calls[0]['frames'][0]['frame_id'], 'F1')
        self.assertIn(f'[来源:{self.sources[0]["id"]}]', result['content'])
        self.assertIn('00:12', result['content'])
        self.assertIn('(zhixu-asset:actual-frame-id)', result['content'])
        self.assertEqual(_tutorial_evidence(result['content'])[0], [self.sources[0]['id']])
        record = self.store.tutorial_attempts(self.doc['id'])[0]
        self.assertEqual(record['raw_result']['sections'][0]['source_ids'], ['S1'])

    def test_frame_handle_cannot_become_source_even_if_frame_exists(self):
        with self.assertRaisesRegex(ValueError, '截图|原文'):
            self.run_model([{'sections':[self.section(source_ids=['F1'])]}])
        self.assertEqual(self.store.document(self.doc['id'])['content'], self.doc['content'])

    def test_verified_timestamp_suffix_is_separated_without_changing_evidence(self):
        result, calls = self.run_model([{'sections':[self.section(source_ids=['S1 @12.5'])]}])
        self.assertEqual(len(calls), 1)
        self.assertEqual(_tutorial_evidence(result['content'])[0], [self.sources[0]['id']])

    def test_wrong_timestamp_or_unknown_handle_is_not_silently_bound(self):
        for ref in ['S1 @99', 'S999', self.frames[0]['id']]:
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                self.run_model([{'sections':[self.section(source_ids=[ref])]}])
        self.assertEqual(self.store.document(self.doc['id'])['content'], self.doc['content'])

    def test_each_factual_section_requires_evidence(self):
        with self.assertRaisesRegex(ValueError, '来源|引用|原文'):
            self.run_model([{'sections':[self.section(), self.section(source_ids=[])]}])

    def test_supplement_is_explicitly_labeled_and_does_not_replace_source_section(self):
        result, _ = self.run_model([{'sections':[self.section(), self.section(source_ids=[], frame_ids=[], supplement=True)]}])
        self.assertIn('AI 补充，需核对', result['content'])

    def test_invalid_structured_draft_is_retained_and_repaired_once(self):
        bad = {'sections':[self.section(source_ids=['F1'])]}
        good = {'sections':[self.section(source_ids=['S2'])]}
        result, calls = self.run_model([bad, good])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]['draft'], bad)
        records = self.store.tutorial_attempts(self.doc['id'])
        self.assertEqual(records[1]['raw_result'], bad)
        self.assertEqual(records[1]['errors'][0]['code'], 'frame_used_as_source')
        self.assertEqual(_tutorial_evidence(result['content'])[0], [self.sources[1]['id']])

    def test_english_structured_body_remains_rejected(self):
        with self.assertRaisesRegex(ValueError, '中文'):
            self.run_model([{'sections':[self.section(heading='Overview',content='The model produces a plan; the application executes it. ' * 4)]}])

    def test_chinese_heading_does_not_disguise_english_only_body(self):
        with self.assertRaisesRegex(ValueError, '中文'):
            self.run_model([{'sections':[self.section(content='The model produces a plan; the application executes it. ' * 4)]}])

    def test_heading_is_plain_text_not_an_image_or_extra_citation(self):
        from markdown_it import MarkdownIt
        result, _ = self.run_model([{'sections':[self.section(
            heading='![伪造截图](data:image/png;base64,YQ==) [来源:unknown]', frame_ids=[])]}])
        images = [t for b in MarkdownIt().parse(result['content']) for t in b.children or [] if t.type == 'image']
        self.assertEqual(images, [])
        self.assertEqual(_tutorial_evidence(result['content'])[0], [self.sources[0]['id']])

    def test_html_image_in_body_cannot_bypass_managed_frame_fields(self):
        with self.assertRaisesRegex(ValueError, '图片|截图'):
            self.run_model([{'sections':[self.section(content='这是中文讲解。' * 12 + '<img src="data:image/png;base64,YQ==">')]}])
