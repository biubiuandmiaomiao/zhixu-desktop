import tempfile
import unittest
from types import SimpleNamespace

from backend.knowledge import Knowledge
from backend.store import Store


class TutorialValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.doc = self.store.add_document('English original', 'The model requests a function; the application runs it. ' * 8)
        self.source_id = self.store.segments(self.doc['id'])[0]['id']

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def generate(self, content):
        ai = SimpleNamespace(json=lambda *args, **kwargs: {'content': content})
        return Knowledge(self.store, ai, None).tutorial(self.doc['id'])

    def test_english_response_with_valid_citation_does_not_replace_original(self):
        content = '# Function calling\n\n' + 'The application executes the function requested by the model. ' * 3
        with self.assertRaisesRegex(ValueError, '中文'):
            self.generate(content + f'[来源:{self.source_id}]')
        self.assertEqual(self.store.document(self.doc['id'])['content'], self.doc['content'])

    def test_code_comments_and_image_alt_text_are_not_chinese_explanation(self):
        content = ('# Functions\n\nThe application executes the requested function.\n\n'
                   '```python\n# 中文注释不能替代中文讲解\nprint("中文示例")\n```\n\n'
                   '<!-- 隐藏的中文说明 -->\n\n![中文图注](https://example.invalid/image.png)\n\n')
        with self.assertRaisesRegex(ValueError, '中文'):
            self.generate(content + f'[来源:{self.source_id}]')
        self.assertEqual(self.store.document(self.doc['id'])['content'], self.doc['content'])

    def test_only_citations_in_comments_code_or_image_labels_are_rejected(self):
        citation = f'[来源:{self.source_id}]'
        for hidden in ('<!-- ' + citation + ' -->', '`' + citation + '`',
                       '```md\n' + citation + '\n```',
                       '    ' + citation,
                       '![' + citation + '](https://example.invalid/image.png)',
                       '\\' + citation):
            with self.subTest(hidden=hidden), self.assertRaisesRegex(ValueError, '引用|来源'):
                self.generate('这是有明确中文讲解的教程，必须提供可见的原文依据。' * 3 + '\n\n' + hidden)
            self.assertEqual(self.store.document(self.doc['id'])['content'], self.doc['content'])

    def test_visible_citation_and_chinese_explanation_allow_literal_code_examples(self):
        content = ('## 使用说明\n\n函数执行由程序负责。' + f'[来源:{self.source_id}]\n\n' +
                   '```python\n' + 'print("English code and sample output")\n' * 30 +
                   '# [来源:invalid-example]\n```\n\n<!-- [来源:invalid-hidden] -->')
        result = self.generate(content)
        self.assertEqual(result['content'], content)
        self.assertEqual(self.store.segments(self.doc['id'])[0]['id'], self.source_id)

    def test_wikilinks_and_bare_urls_do_not_count_as_visible_source_buttons(self):
        citation = f'[来源:{self.source_id}]'
        for hidden in ('[' + citation + ']', 'https://example.invalid/' + citation,
                       'www.example.invalid/' + citation, 'ftp://example.invalid/' + citation):
            with self.subTest(hidden=hidden), self.assertRaisesRegex(ValueError, '引用|来源'):
                self.generate('这是中文讲解，但笔记链接和网页地址不应冒充可用的原文引用。' * 3 + '\n\n' + hidden)
            self.assertEqual(self.store.document(self.doc['id'])['content'], self.doc['content'])

    def test_visible_citations_after_links_code_and_newlines_remain_valid(self):
        citation = f'[来源:{self.source_id}]'
        for prefix in ('[链接](https://example.invalid)', '`https://example.invalid`',
                       'See https://example.invalid.\n'):
            with self.subTest(prefix=prefix):
                content = '这是正常的中文讲解，链接或代码之后的原文引用仍然有效。' * 3 + '\n\n' + prefix + citation
                self.assertEqual(self.generate(content)['content'], content)
