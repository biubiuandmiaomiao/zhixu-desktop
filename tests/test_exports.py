import importlib.util
import tempfile
import unittest

from backend.store import Store


class ScreenshotExportTests(unittest.TestCase):
    def test_reference_images_resolve_known_frames_and_reject_unknown_frames(self):
        from backend.exports import rewrite_asset_images
        for usage in ('![截图][picture]', '![picture][]', '![picture]'):
            with self.subTest(usage=usage):
                content = usage + '\n\n[picture]: <frame:known> "画面"'
                resolved, used = rewrite_asset_images(content, [{'id': 'known'}])
                self.assertEqual(used, {'known'})
                self.assertIn('[picture]: <zhixu-asset:known>', resolved)
                with self.assertRaisesRegex(ValueError, '截图'):
                    rewrite_asset_images(usage + '\n\n[picture]: zhixu-asset:unknown', [{'id': 'known'}])

    def test_reference_image_export_embeds_definition_once_without_extra_gallery(self):
        from backend.exports import with_embedded_frames
        from backend.notebook import Notebook
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                note = store.add_document('引用式图片', '![画面][shot]\n\n![重用][shot]\n\n[shot]: zhixu-asset:known')
                exported = with_embedded_frames(store.notebook.export_document(note['id']),
                                               [{'id': 'known', 'start': 0, 'data_url': 'data:image/jpeg;base64,YQ=='}])
                body = Notebook.decode_portable(exported)['content']
                self.assertIn('[shot]: data:image/jpeg;base64,YQ==', body)
                self.assertEqual(body.count('data:image/jpeg;base64,'), 1)
                self.assertNotIn('## 视频截图', body)
            finally:
                store.close()

    def test_reference_label_with_escaped_bracket_does_not_get_rewritten(self):
        from backend.exports import rewrite_asset_images
        from markdown_it import MarkdownIt
        content = '![x][a\\]: frame:known x]\n\n[a\\]: frame:known x]: frame:known'
        result, used = rewrite_asset_images(content, [{'id': 'known'}])
        self.assertIn('[a\\]: frame:known x]: zhixu-asset:known', result)
        images = [child.attrGet('src') for token in MarkdownIt('commonmark').parse(result)
                  for child in token.children or [] if child.type == 'image']
        self.assertEqual(images, ['zhixu-asset:known'])
        self.assertEqual(used, {'known'})

    def test_container_reference_definitions_keep_their_prefixes(self):
        from backend.exports import rewrite_asset_images
        for content in ('> ![x][shot]\n>\n> [shot]: frame:known',
                        '![x][shot]\n\n> [shot]: frame:known',
                        '![x][shot]\n\n- [shot]: frame:known'):
            with self.subTest(content=content):
                result, used = rewrite_asset_images(content, [{'id': 'known'}])
                self.assertEqual(used, {'known'})
                self.assertEqual(result, content.replace('frame:known', 'zhixu-asset:known'))

    def test_unsupported_real_inline_image_spans_are_rejected_instead_of_silently_skipped(self):
        from backend.exports import rewrite_asset_images
        for content in (r'\\![图](frame:known)', '![图中 [子标签] 说明](frame:known)'):
            with self.subTest(content=content), self.assertRaisesRegex(ValueError, '截图|格式'):
                rewrite_asset_images(content, [{'id': 'known'}])

    def test_repeated_image_expansion_and_remaining_gallery_obey_body_budget(self):
        from unittest.mock import patch
        import backend.exports as exports
        assets=[{'id':'known','start':0,'data_url':'data:image/jpeg;base64,'+'A'*100}]
        with patch.object(exports,'MAX_PORTABLE_BODY_CHARS',512,create=True):
            with self.assertRaisesRegex(ValueError,'大小|超过'):
                exports.rewrite_asset_images('![图](frame:known)\n'*8,assets,embed=True)
            with tempfile.TemporaryDirectory() as directory:
                store=Store(directory)
                try:
                    note=store.add_document('预算','x'*480)
                    with self.assertRaisesRegex(ValueError,'大小|超过'):
                        exports.with_embedded_frames(store.notebook.export_document(note['id']),assets)
                finally:store.close()

    def test_frame_syntax_in_code_stays_literal_while_real_images_are_resolved(self):
        from backend.exports import rewrite_asset_images
        content='```md\n![示例](frame:not-real)\n```\n`![示例](frame:not-real)`\n\n![实际](frame:known)'
        result,used=rewrite_asset_images(content,[{'id':'known'}])
        self.assertEqual(used,{'known'})
        self.assertEqual(result.count('frame:not-real'),2)
        self.assertIn('![实际](zhixu-asset:known)',result)

    def test_image_titles_and_angle_destinations_resolve_and_reject_unknown_ids(self):
        from backend.exports import rewrite_asset_images
        for template in ('![图]({uri} "说明")','![图](<{uri}>)',"![图](<{uri}> '说明')"):
            resolved,used=rewrite_asset_images(template.format(uri='frame:known'),[{'id':'known'}])
            self.assertEqual(used,{'known'})
            self.assertIn('zhixu-asset:known',resolved)
            with self.assertRaisesRegex(ValueError,'截图'):
                rewrite_asset_images(template.format(uri='frame:unknown'),[{'id':'known'}])

    def test_indented_and_escaped_code_examples_are_ignored_but_list_images_resolve(self):
        from backend.exports import rewrite_asset_images
        content='    ![代码](frame:unknown)\n\n\\![转义](frame:unknown)\n\n- 列表\n\n    ![实际](frame:known)'
        resolved,used=rewrite_asset_images(content,[{'id':'known'}])
        self.assertEqual(used,{'known'})
        self.assertEqual(resolved.count('frame:unknown'),2)
        self.assertIn('![实际](zhixu-asset:known)',resolved)

    def test_inline_managed_image_is_embedded_once_and_link_bindings_follow_new_positions(self):
        from backend.exports import with_embedded_frames
        from backend.notebook import Notebook
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            try:
                target=store.add_document('Target','旧目标')
                note=store.add_document('图片笔记','![图](zhixu-asset:frame-one)\n\n[[Target]]')
                store.delete_document(target['id'])
                store.add_document('Target','无关的新目标')
                text=with_embedded_frames(store.notebook.export_document(note['id']),[{'id':'frame-one','start':1,'data_url':'data:image/jpeg;base64,YQ=='}])
                decoded=Notebook.decode_portable(text)
                self.assertNotIn('zhixu-asset:',decoded['content'])
                self.assertEqual(decoded['content'].count('data:image/jpeg;base64,'),1)
                self.assertEqual(decoded['links'][0]['position'],decoded['content'].index('[[Target]]'))
                copied=store.add_document('复制',text)
                self.assertEqual(store.notebook.resolve_link(copied['id'],'Target')['reason'],'deleted')
            finally:store.close()

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
