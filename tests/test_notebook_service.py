import tempfile
import unittest

from backend.service import Service
from backend.knowledge import Knowledge
from tests.test_generation_context import RecordingAI


class NotebookServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = Service(self.temp.name)
        self.target = self.service.dispatch('import_text', {'title':'目标笔记','content':'# 机制\n闭包捕获变量。 #python/closure'})
        self.source = self.service.dispatch('import_text', {'title':'入口笔记','content':'[[目标笔记#机制]]'})

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def test_document_exposes_real_notebook_context_and_resolved_links(self):
        detail = self.service.dispatch('document', {'id':self.target['id']})
        self.assertIn('notebook', detail)
        self.assertEqual(detail['notebook']['backlinks'][0]['document_id'], self.source['id'])
        resolved = self.service.dispatch('resolve_note_link', {'id':self.source['id'],'target':'目标笔记#机制'})
        self.assertEqual(resolved['document_id'], self.target['id'])

    def test_tutorial_accepts_bounded_style_options_and_keeps_citations(self):
        ai = RecordingAI(self.service.store.segments(self.target['id'])[0]['id'])
        knowledge = Knowledge(self.service.store,ai,None)
        knowledge.tutorial(self.target['id'], style='summary')
        self.assertEqual(ai.calls[-1][1]['style'], 'summary')
        with self.assertRaisesRegex(ValueError, '风格'):
            knowledge.tutorial(self.target['id'], style='arbitrary prompt override')

    def test_native_file_import_accepts_portable_lf_text_saved_as_windows_crlf(self):
        original=self.service.dispatch('import_text',{'title':'Windows 往返','content':'# 中文🙂\n\n[[目标笔记#机制]]\n\n正文。\n\n'})
        portable=self.service.dispatch('export_document',{'id':original['id']})['content']
        copied=self.service.dispatch('import_text',{'title':'复制','content':portable.replace('\n','\r\n')})
        self.assertEqual(copied['content'],original['content'])
        self.assertEqual(self.service.store.segments(copied['id'])[0]['text'],self.service.store.segments(original['id'])[0]['text'])

    def test_correctly_counted_original_crlf_body_remains_byte_exact(self):
        original=self.service.dispatch('import_text',{'title':'原始换行','content':'第一行\r\n第二行\r\n'})
        portable=self.service.dispatch('export_document',{'id':original['id']})['content']
        copied=self.service.dispatch('import_text',{'title':'复制','content':portable})
        self.assertEqual(copied['content'],original['content'])

    def test_malformed_repeated_cr_transport_is_rejected_without_recursive_retry(self):
        portable=self.service.dispatch('export_document',{'id':self.target['id']})['content']
        with self.assertRaisesRegex(ValueError,'元数据'):
            self.service.dispatch('import_text',{'title':'无效换行','content':portable.replace('\n','\r'*1100+'\n',1)})

    def test_tutorial_resolves_known_frame_image_links_without_relaxing_citations(self):
        source_id=self.service.store.segments(self.target['id'])[0]['id']
        class ImageAI:
            def json(inner,system,payload,images=None):
                return {'content':'这是有出处的图文讲解。'*5+f'[来源:{source_id}]\n\n![原始画面](frame:known-frame)'}
        result=Knowledge(self.service.store,ImageAI(),None).tutorial(self.target['id'],images=[{'id':'known-frame','start':0,'data_url':'data:image/jpeg;base64,YQ=='}],use_images=True)
        self.assertIn('](zhixu-asset:known-frame)',result['content'])
        self.assertNotIn('](frame:',result['content'])

    def test_tutorial_rejects_unknown_frame_before_replacing_saved_body(self):
        source_id=self.service.store.segments(self.target['id'])[0]['id']
        before=self.service.store.document(self.target['id'])['content']
        class ImageAI:
            def json(inner,system,payload,images=None):
                return {'content':'这是有出处的图文讲解。'*5+f'[来源:{source_id}]\n\n![不存在](frame:unknown-frame)'}
        with self.assertRaisesRegex(ValueError,'截图'):
            Knowledge(self.service.store,ImageAI(),None).tutorial(self.target['id'],images=[{'id':'known-frame','start':0,'data_url':'data:image/jpeg;base64,YQ=='}],use_images=True)
        self.assertEqual(self.service.store.document(self.target['id'])['content'],before)
