"""Private stdin/stdout protocol; never listens on a network port."""
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.provider import redact
from backend.service import Service


def main():
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    data_dir = os.environ.get('ZHIXU_DATA_DIR')
    if not data_dir:
        raise RuntimeError('缺少应用数据目录')
    service = Service(data_dir)
    print(json.dumps({'ready': True}), flush=True)
    try:
        for line in sys.stdin:
            request_id = None
            try:
                request = json.loads(line)
                request_id = request.get('id')
                value = service.dispatch(request['action'], request.get('args'), request.get('api_key', ''))
                output = {'id': request_id, 'result': value}
            except Exception as exc:
                # Protocol errors never expose credentials; tutorial drafts are retained separately after redaction.
                message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else '操作失败，请重试；已保存的资料仍保留在本地'
                output = {'id': request_id, 'error': redact(message)}
            print(json.dumps(output, ensure_ascii=False), flush=True)
    finally:
        service.close()


if __name__ == '__main__':
    main()
