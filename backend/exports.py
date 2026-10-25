"""Portable Markdown retains its source map and bounded managed screenshots."""
import json
import math
import re

from .notebook import PORTABLE_MARKER


def with_embedded_frames(markdown, assets):
    if not assets:
        return markdown
    if len(assets) > 6:
        raise ValueError('单次导出最多包含六张图片')
    frames = []
    for image in assets:
        data = image.get('data_url', '')
        start = image.get('start', 0)
        if (not isinstance(data, str) or len(data) > 2_000_000
                or not re.fullmatch(r'data:image/(?:jpeg|png|webp);base64,[A-Za-z0-9+/=]+', data)
                or not isinstance(start, (int, float)) or not math.isfinite(start) or start < 0):
            raise ValueError('图片必须来自受管理的本地截图')
        timecode = f'{int(start // 60):02}:{int(start % 60):02}'
        frames.append(f'![视频截图 {timecode}]({data})')
    marker = markdown.rfind('\n\n' + PORTABLE_MARKER)
    if marker < 0 or not markdown.endswith('\n-->\n'):
        raise ValueError('缺少可携带的原文映射，未导出图片')
    body = markdown[:marker]
    metadata = json.loads(markdown[marker + 2 + len(PORTABLE_MARKER):-5])
    body += '\n\n## 视频截图\n\n' + '\n\n'.join(frames)
    if len(body) > 2_000_000:
        raise ValueError('图片使笔记超过导入大小限制，请分开导出')
    metadata['body_length'] = len(body)
    encoded = json.dumps(metadata, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e')
    return body + '\n\n' + PORTABLE_MARKER + encoded + '\n-->\n'
