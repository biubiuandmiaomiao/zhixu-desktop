import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from backend.provider import Provider


class ProviderBudgetTests(unittest.TestCase):
    def test_optional_vision_uses_registered_data_images_and_text_context(self):
        class Capture(Provider):
            def request(self, endpoint, payload, embedding=False):
                self.sent = payload
                return {'choices':[{'message':{'content':'{"ok":true}'}}]}
        provider = Capture({'model':'fixture'}, 'test')
        self.assertEqual(provider.json('system', {'source':'test'}, images=['data:image/jpeg;base64,YQ==']), {'ok':True})
        content = provider.sent['messages'][1]['content']
        self.assertEqual(content[0]['type'], 'text')
        self.assertEqual(content[1]['image_url']['url'], 'data:image/jpeg;base64,YQ==')
        with self.assertRaisesRegex(ValueError, '图片'):
            provider.json('system', {}, images=['file:///C:/private.jpg'])

    def test_http_timeout_honors_short_learning_budget_and_restores_generation_budget(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                if self.path == '/embeddings':
                    time.sleep(.25)
                body = json.dumps({'data': [{'index': 0, 'embedding': [1.0, 0.1]}]}).encode()
                try:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(body)
                except OSError:
                    pass
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        provider = Provider({'base_url': f'http://127.0.0.1:{server.server_port}',
                             'embedding_model': 'fixture'}, 'test')
        try:
            self.assertTrue(callable(getattr(provider, 'budget', None)), 'Provider needs a shared time budget')
            started = time.monotonic()
            with provider.budget(.05), self.assertRaises(ValueError):
                provider.embed(['test'])
            self.assertLess(time.monotonic() - started, .2)
            self.assertEqual(provider.request('/fast', {})['data'][0]['embedding'], [1.0, 0.1])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
