import gzip
import importlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


class Response(io.BytesIO):
    def __init__(self, body, url, length=None):
        super().__init__(body)
        self.url = url
        self.headers = {'Content-Length': str(len(body) if length is None else length)}
    def geturl(self):
        return self.url


class PublicBilibiliTests(unittest.TestCase):
    def setUp(self):
        try:
            self.module = importlib.import_module('backend.bilibili')
        except ModuleNotFoundError:
            self.fail('Public Bilibili API fallback is missing when page extraction fails')
        self.requests = []
        self.caption = False
        self.preview = False
        self.media_url = 'https://upos-hz-mirrorakam.akamaized.net/public.mp4'
        outer = self
        class Opener:
            def open(self, req, timeout):
                outer.requests.append(req)
                path = urlsplit(req.full_url).path
                if path.endswith('pagelist'):
                    data = {'code':0,'data':[{'page':1,'cid':1,'part':'wrong','duration':1},{'page':12,'cid':41916106061,'part':'4-评估反射的影响','duration':497}]}
                elif path.endswith('/v2'):
                    tracks = [{'lan':'zh-CN','subtitle_url':'//aisubtitle.hdslb.com/public.json'}] if outer.caption else []
                    data = {'code':0,'data':{'subtitle':{'subtitles':tracks}}}
                elif path.endswith('playurl'):
                    data = {'code':0,'data':{'is_preview':outer.preview,'durl':[{'url':outer.media_url,'size':5,'length':496210}]}}
                elif path.endswith('public.json'):
                    data = {'body':[{'from':1.25,'content':'真实公开字幕'}]}
                elif path.endswith('public.mp4'):
                    return Response(b'video',req.full_url)
                else:raise AssertionError(req.full_url)
                return Response(gzip.compress(json.dumps(data).encode()),req.full_url)
        self.client = self.module.BilibiliPublic('https://www.bilibili.com/video/BV1AJen6SEVQ?p=12',opener=Opener())

    def test_exact_part_metadata_survives_missing_initial_state_without_login(self):
        info = self.client.info()
        self.assertEqual(info['cid'],41916106061)
        self.assertEqual(info['duration'],497)
        self.assertIn('P12',info['title'])
        self.assertIn('评估反射',info['title'])
        self.assertEqual(info['subtitles'],[])
        request = next(r for r in self.requests if urlsplit(r.full_url).path.endswith('/v2'))
        self.assertEqual(parse_qs(urlsplit(request.full_url).query)['cid'],['41916106061'])
        self.assertTrue(all(not r.has_header('Cookie') for r in self.requests))

    def test_nonexistent_part_never_falls_back_to_first_video(self):
        self.client.page = 99
        with self.assertRaisesRegex(ValueError,'分 P'):
            self.client.info()

    def test_public_caption_is_available_without_media_download(self):
        self.caption = True
        track = self.client.info()['subtitles'][0]
        text = self.client.caption(track)
        self.assertEqual(json.loads(text)['body'][0]['from'],1.25)
        self.assertFalse(any('playurl' in r.full_url for r in self.requests))

    def test_public_mp4_download_is_bounded_cancellable_and_atomically_named(self):
        self.client.info()
        checks,progress=[],[]
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'public.mp4'
            self.client.download(target,lambda:checks.append(True),lambda value:progress.append(value),100)
            self.assertEqual(target.read_bytes(),b'video')
            self.assertFalse(target.with_suffix('.mp4.part').exists())
            self.assertTrue(checks)
            self.assertEqual(progress[-1],1)
            with self.assertRaisesRegex(ValueError,'大小'):
                self.client.download(Path(directory)/'too-large.mp4',lambda:None,lambda value:None,4)

    def test_untrusted_media_urls_and_preview_are_rejected(self):
        self.client.info()
        for value in ['https://127.0.0.1/a','file:///secret','https://bilivideo.com.evil.invalid/a','https://user:pass@a.bilivideo.com/a']:
            self.media_url=value
            with self.assertRaisesRegex(ValueError,'地址'):
                self.client.media()
        self.media_url='https://a.bilivideo.com/public.mp4'
        self.preview=True
        with self.assertRaisesRegex(ValueError,'试看'):
            self.client.media()


if __name__ == '__main__':unittest.main()
