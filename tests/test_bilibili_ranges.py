import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.bilibili import BilibiliPublic, _TransientPublicError
from backend.ranged_media import download_budget

PRIMARY='https://a.bilivideo.com/video.mp4'
BACKUP='https://b.bilivideo.com/video.mp4'
DATA=b'abcdefghij'
class Response(io.BytesIO):
    def __init__(self,body,start=0,end=3,total=10,etag='"same"',status=206):
        super().__init__(body);self.status=status
        self.headers={'Content-Length':str(len(body)),'Content-Range':f'bytes {start}-{end}/{total}'}
        if etag is not None:self.headers['ETag']=etag

class RangeTests(unittest.TestCase):
    def test_medium_media_retains_prefix_across_short_response(self):
        # A 14.9 MB real acceptance file failed below the former16 MiB cutoff.
        # Exercise that size class without patching the production threshold.
        data = b'x' * (3 * 1024 * 1024)
        client = BilibiliPublic('https://www.bilibili.com/video/BV1AJen6SEVQ/')
        calls = []
        def serve(url, kind, timeout=20, headers=None):
            calls.append(headers or {})
            self.assertIn('Range', headers or {}, 'Known multi-chunk media must use verified ranges')
            start, end = map(int, headers['Range'].removeprefix('bytes=').split('-'))
            body = data[start:end+1]
            if len(calls) == 2:
                body = body[:20]
            response = Response(body, start, end, len(data))
            response.headers['Content-Length'] = str(end-start+1)
            return response
        with tempfile.TemporaryDirectory() as directory, patch.object(client, 'media', return_value={'url':PRIMARY,'size':len(data)}), patch.object(client, '_open', side_effect=serve):
            target = Path(directory)/'video.mp4'
            client.download(target, lambda:None, lambda value:None, len(data)+1)
            self.assertEqual(target.read_bytes(), data)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[1]['Range'], calls[2]['Range'])

    def run_transfer(self,serve,check=lambda:None,backups=None,events=None):
        client=BilibiliPublic('https://www.bilibili.com/video/BV1AJen6SEVQ/',observer=lambda e,d:events.append((e,d)) if events is not None else None)
        self.calls=[]
        def open_stream(url,kind,timeout=20,headers=None):
            self.calls.append((url,headers or {}))
            return serve(url,headers or {},len(self.calls))
        with tempfile.TemporaryDirectory() as directory,patch('backend.bilibili.RANGE_CHUNK_BYTES',4,create=True),patch('backend.bilibili.RANGE_THRESHOLD_BYTES',8,create=True),patch.object(client,'media',return_value={'url':PRIMARY,'backup_url':backups or [],'size':10}),patch.object(client,'_open',side_effect=open_stream):
            target=Path(directory)/'video.mp4';self.target=target;completed=False
            try:
                client.download(target,check,lambda v:None,100)
                completed=True
                return target.read_bytes()
            finally:
                self.assertFalse(target.with_suffix('.mp4.part').exists())
                if not completed:self.assertFalse(target.exists())

    def response(self,headers,etag='"same"'):
        value=headers['Range'].removeprefix('bytes=');start,end=map(int,value.split('-'))
        return Response(DATA[start:end+1],start,end,etag=etag)

    def test_large_file_budget_grows_but_is_always_bounded(self):
        self.assertEqual(download_budget(0),600)
        self.assertEqual(download_budget(16*1024*1024),600)
        self.assertGreater(download_budget(91426991),600)
        self.assertLessEqual(download_budget(91426991),1800)
        self.assertEqual(download_budget(1024*1024*1024),1800)

    def test_exact_ranges_reassemble_complete_file(self):
        events=[]
        self.assertEqual(self.run_transfer(lambda u,h,n:self.response(h),events=events),DATA)
        self.assertEqual([h['Range'] for u,h in self.calls],['bytes=0-3','bytes=4-7','bytes=8-9'])
        self.assertEqual(self.calls[1][1]['If-Range'],'"same"')
        self.assertEqual(events[-1][0],'download_completed')
        self.assertEqual(events[-1][1]['received_bytes'],10)

    def test_short_chunk_retries_without_losing_verified_prefix(self):
        def serve(u,h,n):
            if n==2:
                self.assertEqual(self.target.with_suffix('.mp4.part').stat().st_size,4)
                r=Response(b'e',4,7);r.headers['Content-Length']='4';return r
            return self.response(h)
        events=[]
        self.assertEqual(self.run_transfer(serve,events=events),DATA)
        failed=next(details for event,details in events if event=='download_retry')
        self.assertEqual(failed['received_bytes'],5)
        self.assertEqual(failed['committed_bytes'],4)
        self.assertEqual([h['Range'] for u,h in self.calls],['bytes=0-3','bytes=4-7','bytes=4-7','bytes=8-9'])

    def test_wrong_offset_never_commits(self):
        def serve(u,h,n):return self.response(h) if n==1 else Response(b'xxxx',0,3)
        with self.assertRaises(ValueError):self.run_transfer(serve)
        self.assertFalse(self.target.exists())

    def test_wrong_total_never_commits(self):
        with self.assertRaises(ValueError):self.run_transfer(lambda u,h,n:Response(b'abcd',0,3,total=11))
        self.assertEqual(len(self.calls),1)

    def test_declared_length_must_match_requested_range(self):
        def serve(u,h,n):
            r=self.response(h);r.headers['Content-Length']='2';return r
        with self.assertRaises(ValueError):self.run_transfer(serve)

    def test_body_overflow_never_commits(self):
        def serve(u,h,n):
            r=Response(b'abcde',0,3);r.headers['Content-Length']='4';return r
        with self.assertRaises(ValueError):self.run_transfer(serve)

    def test_changed_etag_stops_without_mixing(self):
        def changing(u,h,n):return self.response(h,etag='"same"' if h['Range']=='bytes=0-3' else '"changed"')
        with self.assertRaises(ValueError):self.run_transfer(changing)
        self.assertEqual(len(self.calls),6)

    def test_changed_representation_can_restart_safely_on_backup(self):
        def serve(u,h,n):
            if u==PRIMARY:return self.response(h,etag='"old"' if h['Range']=='bytes=0-3' else '"changed"')
            return self.response(h,etag='"new"')
        self.assertEqual(self.run_transfer(serve,backups=[BACKUP]),DATA)
        self.assertEqual(next(h['Range'] for u,h in self.calls if u==BACKUP),'bytes=0-3')

    def test_if_range_matching_206_can_omit_redundant_etag(self):
        def serve(u,h,n):
            response=self.response(h)
            if n>1:
                self.assertIn('If-Range',h)
                response.headers.pop('ETag')
            return response
        self.assertEqual(self.run_transfer(serve),DATA)

    def test_weak_etag_is_not_sent_as_if_range(self):
        self.assertEqual(self.run_transfer(lambda u,h,n:self.response(h,etag='W/"same"')),DATA)
        self.assertTrue(all('If-Range' not in h for u,h in self.calls))

    def test_absent_etag_same_uri_can_complete(self):
        self.assertEqual(self.run_transfer(lambda u,h,n:self.response(h,etag=None)),DATA)
        self.assertTrue(all('If-Range' not in h for u,h in self.calls))

    def test_switching_cdn_starts_at_zero_even_without_validator(self):
        def serve(u,h,n):
            if u==PRIMARY and h.get('Range')!='bytes=0-3':raise _TransientPublicError('connection')
            return self.response(h,etag=None)
        self.assertEqual(self.run_transfer(serve,backups=[BACKUP]),DATA)
        first_backup=next(h for u,h in self.calls if u==BACKUP)
        self.assertEqual(first_backup['Range'],'bytes=0-3')

    def test_ignored_range_discards_prefix_then_full_restart(self):
        def serve(u,h,n):
            if not h:
                r=Response(DATA,status=200);r.headers.pop('Content-Range');return r
            if n==1:return self.response(h)
            r=Response(DATA,status=200);r.headers.pop('Content-Range');return r
        self.assertEqual(self.run_transfer(serve),DATA)
        self.assertEqual(self.calls[-1][1],{})

    def test_auth_denial_is_not_retried_or_bypassed(self):
        def denied(*args):raise ValueError('HTTP 403')
        with self.assertRaisesRegex(ValueError,'403'):self.run_transfer(denied,backups=[BACKUP])
        self.assertEqual(len(self.calls),1)

    def test_all_transient_failures_are_globally_bounded(self):
        def unavailable(*args):raise _TransientPublicError('connection')
        with self.assertRaises(ValueError):self.run_transfer(unavailable,backups=[BACKUP])
        self.assertLessEqual(len(self.calls),12)

    def test_cancel_after_verified_chunk_stops_without_commit(self):
        def check():
            if hasattr(self,'target') and self.target.with_suffix('.mp4.part').exists() and self.target.with_suffix('.mp4.part').stat().st_size>=4:raise RuntimeError('cancelled')
        with self.assertRaisesRegex(RuntimeError,'cancelled'):self.run_transfer(lambda u,h,n:self.response(h),check=check)
        self.assertEqual(len(self.calls),1)

    def test_global_deadline_cannot_reset_per_segment(self):
        clock=[0]
        def serve(u,h,n):
            r=self.response(h);original=r.read1
            def read(size=-1):clock[0]=601;return original(size)
            r.read1=read;return r
        with patch('backend.bilibili.time.monotonic',side_effect=lambda:clock[0]):
            with self.assertRaises(ValueError):self.run_transfer(serve)
        self.assertEqual(len(self.calls),1)

if __name__=='__main__':unittest.main()
