"""Explicit live-model acceptance check. Credentials arrive over stdin, never in artifacts."""
import hashlib
import json
import re
import sqlite3
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.knowledge import Knowledge, _tutorial_evidence
from backend.provider import Provider
from backend.service import Service
from backend.store import Store

root = Path(__file__).resolve().parents[1]
key = json.loads(sys.stdin.readline())['api_key']
document_id = '86d3fcd5-b4fd-4209-ae7c-b14c62f44258'
service = Service(root / 'data')
report = {'document_id': document_id, 'fault_injection': None}


def digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class ObservedProvider(Provider):
    def json(self, system, payload, images=None):
        print(json.dumps({'event': 'model_request', 'repair': 'draft' in payload,
                          'sources': len(payload['sources']), 'frames': len(payload['frames'])}), flush=True)
        started = time.monotonic()
        value = super().json(system, payload, images=images)
        print(json.dumps({'event': 'model_response', 'seconds': round(time.monotonic() - started, 1),
                          'content_chars': len(value.get('content', ''))}), flush=True)
        return value


try:
    before = service.store.segments(document_id)
    assets = service.media.assets(document_id)
    original = service.store.document(document_id)
    report.update(source_count=len(before), frame_count=len(assets), sources_sha256=digest(before))
    provider = ObservedProvider(service.store.settings(), key)
    result = Knowledge(service.store, provider, None).tutorial(document_id, images=assets, use_images=True)
    service.media.mark_tutorial_completed(document_id)
    records = service.store.tutorial_attempts(document_id)
    run_id = records[0]['run_id']
    run_records = [r for r in records if r['run_id'] == run_id]
    cited, _ = _tutorial_evidence(result['content'])
    assert cited and set(cited) <= {s['id'] for s in before}
    assert digest(service.store.segments(document_id)) == digest(before)
    assert len(service.media.assets(document_id)) == len(assets)
    report['natural_run'] = {'run_id': run_id, 'attempts': len(run_records),
                             'statuses': [r['status'] for r in run_records],
                             'errors': [r['errors'] for r in run_records],
                             'citations': len(cited), 'unique_citations': len(set(cited)),
                             'content_chars': len(result['content'])}
    # If this run needed no repair, exercise a real repair call on an isolated DB copy.
    if len(run_records) == 1:
        with tempfile.TemporaryDirectory(prefix='zhixu-p19-repair-') as folder:
            with closing(sqlite3.connect(Path(folder) / 'knowledge.sqlite3')) as target:
                service.store.db.backup(target)
            isolated = Store(folder)
            try:
                class InjectOneBadReference(ObservedProvider):
                    def json(self, system, payload, images=None):
                        if 'draft' not in payload:
                            # Reuse the real P19 model result; only one citation is deliberately corrupted.
                            return {**result, 'content': result['content'].replace(
                                f'[来源:{cited[0]}]', '[来源:acceptance-test-invalid-id]', 1)}
                        return super().json(system, payload, images=images)
                repaired = Knowledge(isolated, InjectOneBadReference(service.store.settings(), key), None).tutorial(
                    document_id, images=assets, use_images=True)
                attempts = isolated.tutorial_attempts(document_id)
                assert attempts[0]['status'] == 'saved' and attempts[1]['status'] == 'validation_failed'
                repaired_citations, _ = _tutorial_evidence(repaired['content'])
                assert set(repaired_citations) <= {s['id'] for s in before}
                report['fault_injection'] = {'isolated': True, 'errors': attempts[1]['errors'],
                                             'final_status': attempts[0]['status'], 'citations': len(repaired_citations)}
            finally:
                isolated.close()
    export = service.dispatch('export_document', {'id': document_id}, api_key=key)
    out = root / 'data' / 'exports' / 'P19-evals-中文教程-引用校验通过.md'
    out.write_text(export['content'], encoding='utf-8')
    report.update(success=True, export=str(out), original_content_sha256=digest(original['content']))
finally:
    service.close()
    target = root / 'artifacts' / 'p19-citation-repair-validation.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False), flush=True)
