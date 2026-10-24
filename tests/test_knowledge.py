import unittest

from backend.knowledge import parse_subtitles, validate_bilibili_url
from backend.provider import parse_json, redact


class KnowledgeTests(unittest.TestCase):
    def test_subtitles_keep_timestamp(self):
        srt = '1\n00:01:12,500 --> 00:01:15,000\n闭包捕获变量。\n\n2\n00:02:00,000 --> 00:02:05,000\n装饰器示例。'
        result = parse_subtitles(srt)
        self.assertEqual(result[0]['start'], 72.5)
        self.assertEqual(result[1]['text'], '装饰器示例。')

    def test_rejects_non_bilibili_url(self):
        with self.assertRaises(ValueError):
            validate_bilibili_url('https://evil.invalid/video/BV12345')
        self.assertEqual(validate_bilibili_url('https://www.bilibili.com/video/BV1xx411c7mD/'), 'BV1xx411c7mD')

    def test_model_json_and_secret_redaction(self):
        self.assertEqual(parse_json('```json\n{"questions": []}\n```'), {'questions': []})
        self.assertNotIn('abcdefghijklmnop', redact('api_key=sk-abcdefghijklmnop1234567890'))


if __name__ == '__main__':
    unittest.main()
