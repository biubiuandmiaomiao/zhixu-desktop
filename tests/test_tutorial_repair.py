import json
import tempfile
import unittest

from backend.knowledge import Knowledge
from backend.store import Store
from backend.provider import AIResponseError, AIRequestError


class TutorialRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.doc = self.store.add_document('工具执行', '工具由应用执行，模型负责提出调用请求。' * 10)
        self.sid = self.store.segments(self.doc['id'])[0]['id']
        self.bad = '# 工具执行\n\n' + '应用负责执行工具，模型提供调用参数。' * 4 + '[来源:invented]'
        self.good = self.bad.replace('invented', self.sid)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def provider(self, responses):
        owner = self
        class AI:
            def __init__(self):
                self.calls = []
            def json(self, system, payload, **kwargs):
                self.calls.append(payload)
                if len(self.calls) == 2:
                    saved = owner.store.tutorial_attempts(owner.doc['id'])
                    owner.assertEqual(saved[0]['content'], owner.bad)
                    owner.assertEqual(saved[0]['errors'][0]['invalid_ids'], ['invented'])
                response = responses[len(self.calls) - 1]
                if isinstance(response, Exception):
                    raise response
                return {'content': response}
        return AI()

    def test_malformed_response_is_retained_before_one_bounded_repair(self):
        owner = self
        raw = '{"sections":[{"content":"中文草稿 sk-abcdefghijklmnopqrstuv'
        class AI:
            calls = 0
            def json(self, system, payload, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise AIResponseError(raw, 'length')
                records = owner.store.tutorial_attempts(owner.doc['id'])
                owner.assertEqual(records[0]['errors'][0]['code'], 'output_truncated')
                owner.assertIn('中文草稿', records[0]['content'])
                owner.assertNotIn('sk-abcdefghijklmnopqrstuv', str(records))
                return {'content': owner.good}
        ai=AI()
        result=Knowledge(self.store,ai,None).tutorial(self.doc['id'])
        self.assertEqual(result['content'],self.good)
        records=self.store.tutorial_attempts(self.doc['id'])
        self.assertEqual([r['status'] for r in records],['saved','validation_failed'])
        self.assertEqual(records[1]['raw_result']['finish_reason'],'length')
        self.assertEqual(ai.calls,2)

    def test_initial_transport_exhaustion_is_saved_without_content_repair(self):
        error = AIRequestError('AI 服务连接失败', [{'attempt': 3, 'reason': 'connection_reset'}])
        ai = self.provider([error])
        with self.assertRaisesRegex(ValueError, '连接失败'):
            Knowledge(self.store, ai, None).tutorial(self.doc['id'])
        records = self.store.tutorial_attempts(self.doc['id'])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['status'], 'request_failed')
        self.assertEqual(records[0]['raw_result']['transport_attempts'][0]['reason'], 'connection_reset')
        self.assertEqual(len(ai.calls), 1)
        self.assertEqual(self.store.document(self.doc['id'])['content'], self.doc['content'])

    def test_two_malformed_results_stop_and_preserve_original(self):
        class AI:
            calls = 0
            def json(self, *args, **kwargs):
                self.calls += 1
                raise AIResponseError('{"broken":"中文草稿', 'stop')
        ai=AI()
        with self.assertRaisesRegex(ValueError,'JSON'):
            Knowledge(self.store,ai,None).tutorial(self.doc['id'])
        self.assertEqual(ai.calls,2)
        records=self.store.tutorial_attempts(self.doc['id'])
        self.assertEqual(len(records),2)
        self.assertTrue(all(r['errors'][0]['code']=='malformed_json' for r in records))
        self.assertEqual(self.store.document(self.doc['id'])['content'],self.doc['content'])

    def test_invalid_reference_is_retained_then_repaired_and_revalidated(self):
        ai = self.provider([self.bad, self.good])
        result = Knowledge(self.store, ai, None).tutorial(self.doc['id'])
        self.assertEqual(result['content'], self.good)
        self.assertEqual(ai.calls[1]['draft']['content'], self.bad)
        self.assertEqual(ai.calls[1]['validation_errors'][0]['code'], 'invalid_source_ids')
        self.assertEqual(ai.calls[1]['sources'][0]['id'], self.sid)
        records = self.store.tutorial_attempts(self.doc['id'])
        self.assertEqual([r['status'] for r in records], ['saved', 'validation_failed'])
        self.assertEqual(records[0]['run_id'], records[1]['run_id'])
        self.assertEqual(self.store.segments(self.doc['id'])[0]['id'], self.sid)

    def test_second_invalid_result_stops_and_preserves_both_drafts(self):
        ai = self.provider([self.bad, self.bad.replace('invented', 'also-invalid')])
        with self.assertRaisesRegex(ValueError, 'also-invalid'):
            Knowledge(self.store, ai, None).tutorial(self.doc['id'])
        self.assertEqual(len(ai.calls), 2)
        self.assertEqual(len(self.store.tutorial_attempts(self.doc['id'])), 2)
        self.assertEqual(self.store.document(self.doc['id'])['content'], self.doc['content'])

    def test_repair_network_failure_keeps_original_and_error_without_credentials(self):
        ai = self.provider([self.bad, ValueError('服务错误 sk-abcdefghijklmnopqrstuv')])
        with self.assertRaisesRegex(ValueError, '修正'):
            Knowledge(self.store, ai, None).tutorial(self.doc['id'])
        records = self.store.tutorial_attempts(self.doc['id'])
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]['status'], 'repair_failed')
        self.assertNotIn('sk-abcdefghijklmnopqrstuv', json.dumps(records))
        self.assertEqual(records[1]['content'], self.bad)

    def test_missing_visible_reference_has_specific_error_and_is_repairable(self):
        self.bad = self.bad.replace('[来源:invented]', '')
        ai = self.provider([self.bad, self.good])
        # This case has a different diagnostic than invalid IDs.
        original = ai.json
        def respond(system, payload, **kwargs):
            if ai.calls:
                self.assertEqual(payload['validation_errors'][0]['code'], 'missing_source_citations')
                return {'content': self.good}
            return original(system, payload, **kwargs)
        ai.json = respond
        Knowledge(self.store, ai, None).tutorial(self.doc['id'])
        self.assertEqual(self.store.tutorial_attempts(self.doc['id'])[1]['errors'][0]['code'], 'missing_source_citations')

    def test_validated_repair_still_cannot_overwrite_user_edit(self):
        ai = self.provider([self.bad, self.good])
        original = ai.json
        def respond(system, payload, **kwargs):
            result = original(system, payload, **kwargs)
            if len(ai.calls) == 2:
                self.store.update_document(self.doc['id'], '编辑', '用户编辑内容')
            return result
        ai.json = respond
        with self.assertRaisesRegex(ValueError, '已更新'):
            Knowledge(self.store, ai, None).tutorial(self.doc['id'])
        self.assertEqual(self.store.document(self.doc['id'])['content'], '用户编辑内容')
        self.assertEqual(self.store.tutorial_attempts(self.doc['id'])[0]['status'], 'save_failed')

    def test_deleted_document_removes_retained_drafts(self):
        ai = self.provider([self.bad, self.bad])
        with self.assertRaises(ValueError):
            Knowledge(self.store, ai, None).tutorial(self.doc['id'])
        self.store.delete_document(self.doc['id'])
        self.assertEqual(self.store.rows('SELECT * FROM tutorial_attempts'), [])

    def test_error_redaction_preserves_valid_structured_json(self):
        ai = self.provider([self.bad, ValueError('token=private-value password=private-password')])
        with self.assertRaises(ValueError):
            Knowledge(self.store, ai, None).tutorial(self.doc['id'])
        records = self.store.tutorial_attempts(self.doc['id'])
        self.assertEqual(records[0]['errors'][0]['code'], 'repair_request_failed')
        self.assertNotIn('private-value', str(records))

    def test_cancelled_generation_keeps_draft_without_starting_repair(self):
        ai = self.provider([self.bad, self.good])
        def check():
            if ai.calls:
                raise ValueError('任务已取消')
        with self.assertRaisesRegex(ValueError, '取消'):
            Knowledge(self.store, ai, None).tutorial(self.doc['id'], check_generation=check)
        self.assertEqual(len(ai.calls), 1)
        self.assertEqual(self.store.tutorial_attempts(self.doc['id'])[0]['content'], self.bad)
