"""Portable Markdown retains its source map and bounded managed screenshots."""
import json
import math
import re
from markdown_it import MarkdownIt

from .notebook import PORTABLE_MARKER, Notebook, without_code

MAX_PORTABLE_BODY_CHARS = 2_000_000


def _asset_image_plan(content, assets, embed):
    if len(content) > MAX_PORTABLE_BODY_CHARS:
        raise ValueError('笔记超过导入大小限制，请分开导出')
    registered = {str(a['id']): a for a in assets if a.get('id')}
    masked = without_code(content)
    lines = masked.splitlines(keepends=True)
    for token in MarkdownIt('commonmark').parse(content):
        if token.type in ('code_block', 'fence', 'html_block') and token.map:
            for index in range(*token.map):
                lines[index] = re.sub(r'[^\r\n]', ' ', lines[index])
    masked = ''.join(lines)
    pattern = r'''(?<!\\)!\[(?:\\.|[^\]\\\n])*\]\([ \t]*(?P<angle><)?(?P<url>(?:frame|zhixu-asset):(?P<id>[A-Za-z0-9-]+))(?(angle)>)(?:[ \t]+(?:"(?:\\.|[^"\n])*"|'(?:\\.|[^'\n])*'|\([^\)\n]*\)))?[ \t]*\)'''
    matches = list(re.finditer(pattern, masked))
    used, edits = set(), []
    projected = len(content)
    for match in matches:
        identity = match['id']
        if identity not in registered:
            raise ValueError('教程引用了未提供的截图，已取消保存或导出')
        replacement = registered[identity]['data_url'] if embed else 'zhixu-asset:' + identity
        start, end = match.span('url')
        projected += len(replacement) - (end - start)
        edits.append((start, end, replacement))
        used.add(identity)
    return edits, used, projected


def _apply_image_plan(content, edits):
    parts, offset = [], 0
    for start, end, replacement in edits:
        parts.extend((content[offset:start], replacement))
        offset = end
    parts.append(content[offset:])
    return ''.join(parts)


def rewrite_asset_images(content, assets, embed=False):
    """Resolve registered inline image destinations; code stays literal."""
    edits, used, projected = _asset_image_plan(content, assets, embed)
    if projected > MAX_PORTABLE_BODY_CHARS:
        raise ValueError('图片使笔记超过导入大小限制，请分开导出')
    return _apply_image_plan(content, edits), used


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
        frames.append((str(image.get('id', '')), f'![视频截图 {timecode}](', data))
    marker = markdown.rfind('\n\n' + PORTABLE_MARKER)
    if marker < 0 or not markdown.endswith('\n-->\n'):
        raise ValueError('缺少可携带的原文映射，未导出图片')
    body = markdown[:marker]
    metadata = json.loads(markdown[marker + 2 + len(PORTABLE_MARKER):-5])
    edits, used, projected = _asset_image_plan(body, assets, embed=True)
    remaining = [(prefix, data) for identity, prefix, data in frames if identity not in used]
    gallery_size = (len('\n\n## 视频截图\n\n') + sum(len(prefix) + len(data) + 1 for prefix, data in remaining)
                    + 2 * (len(remaining) - 1)) if remaining else 0
    if projected + gallery_size > MAX_PORTABLE_BODY_CHARS:
        raise ValueError('图片使笔记超过导入大小限制，请分开导出')
    body = _apply_image_plan(body, edits)
    if used and 'links' in metadata:
        parsed = Notebook.parsed_links(body)
        if len(parsed) != len(metadata['links']):
            raise ValueError('图片导出后的笔记链接无法校验')
        for binding, (position, target, _, kind) in zip(metadata['links'], parsed):
            if binding['target'] != target or binding['kind'] != kind:
                raise ValueError('图片导出后的笔记链接无法校验')
            binding['position'] = position
    if remaining:
        body += '\n\n## 视频截图\n\n' + '\n\n'.join(prefix + data + ')' for prefix, data in remaining)
    metadata['body_length'] = len(body)
    encoded = json.dumps(metadata, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e')
    return body + '\n\n' + PORTABLE_MARKER + encoded + '\n-->\n'
