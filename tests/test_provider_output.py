import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from backend.provider import Provider, parse_json


class OutputTests(unittest.TestCase):
    def provider(self,content,finish="stop",base="https://tokenhub.tencentmaas.com/v1"):
        class Capture(Provider):
            def request(self,endpoint,payload):
                self.payload=payload
                return {"choices":[{"message":{"content":content},"finish_reason":finish}]}
        return Capture({"base_url":base,"model":"deepseek-v4.1-flash"},"fixture")

    def test_tokenhub_does_not_send_rejected_json_mode_but_keeps_explicit_budget(self):
        # Live evidence: with response_format json_object a real ask payload is
        # rejected by TokenHub (HTTP 400, code 400006, "当前模型不支持请求的
        # response_format") while a tiny probe still returns 200. The prompt plus
        # parse_json must carry JSON compliance instead of that flag.
        p=self.provider('{"title":"ok"}');p.json("Return JSON",{})
        self.assertNotIn("response_format",p.payload)
        self.assertGreaterEqual(p.payload.get("max_tokens",0),16000)

    def test_malformed_json_retains_raw_text_and_exact_parse_location(self):
        p=self.provider('{"title":"unterminated')
        with self.assertRaises(ValueError) as caught:p.json("Return JSON",{})
        err=caught.exception
        self.assertEqual(getattr(err,"raw_result",{}).get("response_text"),'{"title":"unterminated')
        self.assertEqual(err.errors[0]["code"],"malformed_json")
        self.assertGreater(err.errors[0]["column"],0)

    def test_object_wrapped_in_prose_is_still_accepted(self):
        self.assertEqual(parse_json('好的，结果如下：\n{"title": "ok", "count": 2}\n希望有帮助'),
                         {"title":"ok","count":2})
        self.assertEqual(parse_json('note {not json} then {"real": true}'), {"real":True})
        with self.assertRaisesRegex(ValueError,'JSON'):
            parse_json('完全没有 JSON 的一段说明')

    def test_provider_rejection_reason_reaches_the_user(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                body = json.dumps({'error': {'code': '400006',
                                             'message_zh': '当前模型不支持请求的 response_format 或输出格式'}},
                                  ensure_ascii=False).encode('utf-8')
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        provider = Provider({'base_url': f'http://127.0.0.1:{server.server_port}', 'model': 'fixture'}, 'test')
        try:
            with self.assertRaises(ValueError) as caught:
                provider.json('system', {})
            message = str(caught.exception)
            self.assertIn('HTTP 400', message)
            self.assertIn('400006', message)
            self.assertIn('response_format', message)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_length_finish_never_accepts_a_valid_but_incomplete_object(self):
        p=self.provider('{"title":"ok"}',"length")
        with self.assertRaises(ValueError) as caught:p.json("Return JSON",{})
        self.assertEqual(caught.exception.errors[0]["code"],"output_truncated")
        self.assertEqual(caught.exception.raw_result["finish_reason"],"length")

    def test_other_providers_keep_compatible_request_fields(self):
        p=self.provider('{"title":"ok"}',base="https://example.com/v1");p.json("Return JSON",{})
        self.assertNotIn("response_format",p.payload)
        self.assertNotIn("max_tokens",p.payload)

if __name__=="__main__":unittest.main()
