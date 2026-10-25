import importlib.util
import tempfile
import unittest

from backend.store import Store


class ScreenshotExportTests(unittest.TestCase):
    def test_inline_screenshots_keep_portable_sources_and_unicode_body_length(self):
        self.assertIsNotNone(importlib.util.find_spec('backend.exports'), 'Portable screenshots need an exporter')
        from backend.exports import with_embedded_frames
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                original = store.add_document('视频😀','原始讲解',url='https://www.bilibili.com/video/BV1234567890',kind='subtitle',segments=[{'text':'原始讲解','start':12.0}])
                text = with_embedded_frames(store.notebook.export_document(original['id']), [{'id':'frame','data_url':'data:image/jpeg;base64,YQ==','start':12,'caption':'截图'}])
                imported = store.add_document('复制',text)
                self.assertIn('data:image/jpeg;base64,YQ==', imported['content'])
                self.assertEqual(store.segments(imported['id'])[0]['start'],12.0)
                self.assertEqual(imported['url'], original['url'])
            finally:
                store.close()

    def test_rejects_unmanaged_or_unbounded_image_data(self):
        self.assertIsNotNone(importlib.util.find_spec('backend.exports'))
        from backend.exports import with_embedded_frames
        with self.assertRaises(ValueError):
            with_embedded_frames('note', [{'id':'x','data_url':'file:///private.jpg','start':0}])
