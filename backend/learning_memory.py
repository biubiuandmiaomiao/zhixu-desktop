"""Rebuildable observations of learning events, never independent factual evidence."""
from .provider import redact


LANES = ('relation', 'review', 'conversation')
RELATION_NAMES = {'shared': '共同知识', 'prerequisite': 'A 是 B 的前置知识',
                  'supplement': '互补资料', 'difference': '差异或冲突'}


def learning_entities(store):
    segments = {s['id']: s for s in store.segments()}
    result = {}

    def add(key, lane, text, source_ids, created_at):
        ids = list(dict.fromkeys(source_ids))
        if not ids or any(i not in segments for i in ids):
            return
        result[key] = {'text': redact(text), 'metadata': {
            'lane': lane, 'workspace': 'default', 'entity_id': key,
            'source_ids': ids, 'document_ids': sorted({segments[i]['document_id'] for i in ids}),
            'created_at': created_at}}

    for relation in store.relations():
        ids = [e['id'] for e in relation['evidence']]
        docs = {segments[i]['document_id'] for i in ids if i in segments}
        if relation['status'] != 'confirmed' or not {relation['a'], relation['b']} <= docs:
            continue
        add('relation:' + relation['id'], 'relation',
            f"用户已确认的资料关系（记录时间 {relation['created_at']}）：\n"
            f"A：{relation['a_title']}\nB：{relation['b_title']}\n"
            f"关系：{RELATION_NAMES[relation['kind']]}\n原因：{relation['reason'][:2000]}", ids, relation['created_at'])

    for session in store.sessions(raw=True):
        if session['status'] != 'completed':
            continue
        date = session.get('completed_at') or session['created_at']
        for question in session['questions']:
            score = question.get('score')
            if type(score) is not int or not 0 <= score <= 10:
                continue
            answer = session.get('answers', {}).get(question['id'], '')
            if isinstance(answer, list):
                answer = '、'.join(answer)
            add('review:' + session['id'] + ':' + question['id'], 'review',
                f"本次练习观察（{date}），不是长期掌握程度判断。\n"
                f"题目：{question['prompt'][:1000]}\n本次作答：{str(answer)[:600]}\n"
                f"本次得分：{score}/10\n本次评分反馈：{question.get('feedback', '')[:1000]}",
                question['source_ids'], date)

    for conversation in store.conversations(limit=None):
        add('conversation:' + conversation['id'], 'conversation',
            f"历史提问（{conversation['created_at']}）：{conversation['question'][:2000]}\n"
            '仅记录曾提出的问题，不据此推断用户能力；历史 AI 回答不作为知识依据。',
            [c['id'] for c in conversation['citations']], conversation['created_at'])
    return result


def generation_learning_context(engine, query, provider, source_ids):
    if engine is None or not engine.configured(provider) or not source_ids:
        return [], ''
    if not learning_entities(engine.store):
        return [], ''
    notice = ''
    try:
        with provider.budget(20):
            status = engine.sync(provider, learning_only=True)
        if status['learning_pending']:
            notice = f"还有 {status['learning_pending']} 项学习记录待同步，可到设置继续同步。"
    except Exception:
        notice = '学习记忆暂不可用，本次仍可按原文和当前偏好生成。'
    try:
        with provider.budget(10):
            return engine.learning_context(query, provider, source_ids), notice
    except Exception:
        return [], '学习记忆暂不可用，本次仍可按原文和当前偏好生成。'
