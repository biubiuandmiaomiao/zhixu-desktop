"""Typed generation evidence and deterministic Markdown rendering.

The model chooses evidence; this module never guesses replacements for unknown IDs.
"""
import math
import re

from markdown_it import MarkdownIt


class TutorialProtocolError(ValueError):
    def __init__(self, code, message, section=None):
        super().__init__(message)
        self.errors = [{'code': code, 'message': message, **({'section': section} if section else {})}]


def evidence_payload(sources, images):
    return ([{**s, 'ref': f'S{i}'} for i, s in enumerate(sources, 1)],
            [{'frame_id': f'F{i}', 'asset_url': 'zhixu-asset:' + image['id'],
              'start': image['start']} for i, image in enumerate(images or [], 1)])


def _clock(seconds):
    value = max(0, int(seconds))
    return f'{value // 3600:02}:{value // 60 % 60:02}:{value % 60:02}' if value >= 3600 else f'{value // 60:02}:{value % 60:02}'


def render_tutorial(result, sources, images):
    # Legacy persisted/provider adapters still receive the original strict validator.
    if 'sections' not in result:
        return result
    sections = result['sections']
    if not isinstance(sections, list) or not 1 <= len(sections) <= 80:
        raise TutorialProtocolError('invalid_sections', '教程 sections 必须为 1 到 80 个分节')
    source_map = {s['id']: s for s in sources}
    source_map.update({f'S{i}': s for i, s in enumerate(sources, 1)})
    frame_map = {image['id']: image for image in images or []}
    frame_map.update({f'F{i}': image for i, image in enumerate(images or [], 1)})
    parts = []
    for index, section in enumerate(sections, 1):
        if not isinstance(section, dict):
            raise TutorialProtocolError('invalid_section', '教程分节必须为对象', index)
        heading, body = section.get('heading', ''), section.get('content')
        if not isinstance(heading, str) or len(heading) > 200 or not isinstance(body, str) or not body.strip():
            raise TutorialProtocolError('invalid_section_content', '分节须有非空正文和有效标题', index)
        refs, frames = section.get('source_ids', []), section.get('frame_ids', [])
        if not isinstance(refs, list) or len(refs) > 200 or not all(isinstance(r, str) for r in refs):
            raise TutorialProtocolError('invalid_source_fields', 'source_ids 必须是原文引用标识字符串数组', index)
        if not isinstance(frames, list) or len(frames) > 6 or not all(isinstance(f, str) for f in frames):
            raise TutorialProtocolError('invalid_frame_fields', 'frame_ids 必须是至多六个截图标识字符串数组', index)
        supplement = section.get('supplement', False)
        if not isinstance(supplement, bool):
            raise TutorialProtocolError('invalid_supplement', 'supplement 必须为布尔值', index)
        if not refs and not supplement:
            raise TutorialProtocolError('missing_section_sources', '事实分节缺少原文来源，请填写 source_ids；仅 AI 补充可为空', index)
        resolved = []
        for ref in refs:
            ref = ref.strip()
            match = re.fullmatch(r'(.+?)\s+@([0-9]+(?:\.[0-9]+)?)', ref)
            if match:
                source = source_map.get(match[1])
                if source is None or source.get('start') is None or not math.isclose(float(match[2]), source['start'], abs_tol=.001):
                    raise TutorialProtocolError('source_time_mismatch', '引用后的时间点与真实原文不一致：' + ref, index)
                ref = match[1]
            if ref in frame_map:
                raise TutorialProtocolError('frame_used_as_source', '截图标识不能作为原文来源：' + ref, index)
            if ref not in source_map:
                raise TutorialProtocolError('unknown_source_handle', '原文来源不存在：' + ref, index)
            source = source_map[ref]
            if source not in resolved:
                resolved.append(source)
        chosen_frames = []
        for ref in frames:
            if ref not in frame_map:
                raise TutorialProtocolError('unknown_frame_handle', '截图标识不存在：' + ref, index)
            frame = frame_map[ref]
            if frame not in chosen_frames:
                chosen_frames.append(frame)
        # Source/image syntax is generated here, never accepted as free-form model markup.
        prose = []
        for block in MarkdownIt('commonmark').parse(body):
            if block.type == 'html_block' and re.search(r'<\s*(?:img|picture|video|source|svg|iframe|object|embed)\b', block.content, re.I):
                raise TutorialProtocolError('inline_evidence_markup', '正文不能嵌入未提供图片或媒体，请使用 frame_ids', index)
            for token in block.children or []:
                media_html = token.type == 'html_inline' and re.search(r'<\s*(?:img|picture|video|source|svg|iframe|object|embed)\b', token.content, re.I)
                if token.type == 'image' or media_html or (token.type == 'text' and re.search(r'\[来源:[^\]]+\]', token.content)):
                    raise TutorialProtocolError('inline_evidence_markup', '正文不要手写来源或图片标记，请使用 source_ids 和 frame_ids 字段', index)
                if token.type == 'text':
                    prose.append(token.content)
        if not re.search(r'[\u3400-\u9fff]', '\n'.join(prose)):
            raise TutorialProtocolError('missing_chinese_prose', '每个教程分节须有可见中文讲解，标题或代码不能替代正文', index)
        if heading.strip():
            plain_heading = re.sub(r'([\\`*_{}\[\]()#+.!<>|~\-])', r'\\\1', heading.strip().replace('\n', ' '))
            parts.append('## ' + plain_heading)
        if supplement:
            parts.append('> AI 补充，需核对')
        parts.append(body.strip())
        if resolved:
            parts.append(' '.join('[来源:' + s['id'] + ']' +
                         (f'（{_clock(s["start"])}）' if s.get('start') is not None else '') for s in resolved))
        parts.extend('![视频画面 ' + _clock(f['start']) + '](zhixu-asset:' + f['id'] + ')' for f in chosen_frames)
    content = '\n\n'.join(parts)
    if len(content) > 2_000_000:
        raise TutorialProtocolError('oversized_tutorial', '教程正文过长，请分章节处理')
    return {'title': result.get('title', ''), 'content': content}
