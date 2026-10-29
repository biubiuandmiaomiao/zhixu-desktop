"""Entity layer: canonical names, mentions, and entity-based document relations.

A relation between two notes is only interesting when both mention the same
concrete thing (a person, product, method, concept), not when their text shares a
filler bigram. This module extracts entities once per document, resolves them to
canonical rows, and scores cross-document candidates by shared-entity IDF so that
ubiquitous words lose automatically.

Canonical merging is deterministic (trigram Jaccard + token compatibility +
sequence ratio), the same shape Hindsight uses; no LLM decides whether two names
are the same entity.
"""
import difflib
import math
import re

ENTITY_KINDS = {
    'person': '人物',
    'org': '组织',
    'product': '产品',
    'work': '作品',
    'place': '地点',
    'tech': '技术',
    'concept': '概念',
}
DEFAULT_KIND = 'concept'
MAX_ENTITY_CHARS = 64
MAX_ENTITIES_PER_DOCUMENT = 60
# A shared entity must carry some IDF weight, and an entity that appears in most
# documents is a stopword in disguise (it cannot make two notes related).
SHARED_WEIGHT_THRESHOLD = 0.35

_WHITESPACE = re.compile(r'\s+')
_PUNCT_ONLY = re.compile(r'^[\W_]+$')


def normalize_entity(name):
    """Display form: whitespace collapsed, trimmed, length-capped, non-blank."""
    if not isinstance(name, str):
        return ''
    text = _WHITESPACE.sub(' ', name).strip().strip('`"\'“”‘’')
    if not text or len(text) > MAX_ENTITY_CHARS or _PUNCT_ONLY.fullmatch(text):
        return ''
    return text


def normalize_entity_kind(kind):
    return kind if kind in ENTITY_KINDS else DEFAULT_KIND


TRIGRAM_GATE = 0.3
MERGE_THRESHOLD = 0.72
_TOKEN_SPLIT = re.compile(r'[\s\-_/·.]+')


def _trigrams(name):
    """pg_trgm-compatible trigram set: two spaces of padding per name."""
    padded = '  ' + name.lower() + '  '
    return {padded[index:index + 3] for index in range(len(padded) - 2)}


def _tokens_compatible(short, long):
    """Every token of the shorter name must exist (or nearly exist) in the longer."""
    short_tokens = [token for token in _TOKEN_SPLIT.split(short.lower()) if token]
    long_tokens = [token for token in _TOKEN_SPLIT.split(long.lower()) if token]
    if not short_tokens or not long_tokens:
        return False
    digits_short = set(re.findall(r'\d+', short))
    digits_long = set(re.findall(r'\d+', long))
    if digits_short and digits_long and digits_short != digits_long:
        return False
    for token in short_tokens:
        if any(token == other or token in other for other in long_tokens):
            continue
        if any(difflib.SequenceMatcher(None, token, other).ratio() >= 0.6 for other in long_tokens):
            continue
        return False
    return True


def entity_similarity(left, right):
    """Deterministic 0..1 similarity for two display names."""
    if not left or not right:
        return 0.0
    if left.lower() == right.lower():
        return 1.0
    bigrams_left, bigrams_right = _trigrams(left), _trigrams(right)
    union = bigrams_left | bigrams_right
    jaccard = len(bigrams_left & bigrams_right) / len(union) if union else 0.0
    if jaccard < TRIGRAM_GATE:
        return 0.0
    short, long = sorted((left, right), key=len)
    if not _tokens_compatible(short, long):
        return 0.0
    ratio = difflib.SequenceMatcher(None, left.lower(), right.lower()).ratio()
    return round(0.6 * ratio + 0.4 * jaccard, 6)


def find_similar_entity(store, name, kind):
    """Existing canonical entity close enough to reuse, ignoring cross-kind mixes."""
    best, best_score = None, MERGE_THRESHOLD
    for row in store.rows('SELECT id,name,kind FROM entities'):
        if row['kind'] != kind and DEFAULT_KIND not in (row['kind'], kind):
            continue
        score = entity_similarity(name, row['name'])
        if score >= best_score:
            best, best_score = row, score
    return best


def _clean_alias(value):
    text = normalize_entity(value)
    return text if text else ''


def _validate_entities(raw, content):
    """Keep only entities whose quote really occurs in the document text.

    Extraction can invent plausible-but-absent entities; requiring the quoted
    evidence to appear in the source is the same fail-closed rule used elsewhere.
    """
    if not isinstance(raw, list):
        return []
    haystack = _WHITESPACE.sub(' ', content or '')
    kept, seen = [], set()
    for item in raw[:MAX_ENTITIES_PER_DOCUMENT * 2]:
        if not isinstance(item, dict):
            continue
        name = normalize_entity(item.get('name'))
        if not name:
            continue
        quote = _WHITESPACE.sub(' ', str(item.get('quote') or '')).strip()
        if not quote or len(quote) > 200 or quote not in haystack:
            continue
        norm = name.lower()
        if norm in seen:
            continue
        seen.add(norm)
        aliases = []
        for alias in item.get('aliases') or []:
            cleaned = _clean_alias(alias)
            if cleaned and cleaned.lower() != norm:
                aliases.append(cleaned)
        kept.append({'name': name, 'kind': normalize_entity_kind(item.get('type')),
                     'aliases': aliases[:4], 'quote': quote})
        if len(kept) >= MAX_ENTITIES_PER_DOCUMENT:
            break
    return kept


EXTRACTION_PROMPT = '''从这段学习资料中抽取用于"跨资料实体关联"的实体：既包括具体的人名、机构、产品、作品、地点，也包括这份资料真正在讲的技术与核心概念。
只依据给定原文，不要补充原文没有的信息。实体不是关键词：不要输出"这些""可以""问题""资料"这类泛词，也不要输出整句或代码片段。
同一个事物在不同语言/简称下的写法必须放进 aliases（例如 name="评估" aliases=["evals","evaluation"]；name="吴恩达" aliases=["Andrew Ng"]），否则跨资料关联会断掉。
entity 类型只能是：person（人物）、org（组织）、product（产品/软件）、work（作品/视频/书）、place（地点）、tech（技术/方法/框架）、concept（概念/术语）。
每份资料抽取 8-20 个最值得跨资料连接的实体，宁少勿滥；每个实体给出原文中连续出现的一句 quote 作为依据（不超过 60 字），quote 必须逐字出现在原文中。
返回 {"entities":[{"name":"评估","type":"concept","aliases":["evals","evaluation"],"quote":"评估是构建智能体工作流时用来持续改进系统的手段"}]}，没有可抽取的实体时返回 {"entities":[]}。'''


def extract_entities(provider, title, content):
    """One LLM call per document; returns validated entities."""
    text = (content or '').strip()
    if not text:
        return []
    payload = {'title': title, 'text': text[:8000]}
    result = provider.json(EXTRACTION_PROMPT, payload)
    return _validate_entities(result.get('entities'), text)


def index_document(store, provider, document, replace=True):
    """Extract, resolve and persist one document's entities and mentions."""
    entities = extract_entities(provider, document['title'], document['content'])
    if not entities:
        return 0
    segments = store.segments(document['id'])
    sentence_to_segment = [(s['id'], _WHITESPACE.sub(' ', s['text'])) for s in segments]
    if replace:
        with store.db:
            store.db.execute('DELETE FROM entity_mentions WHERE document_id=?', (document['id'],))
    stored = 0
    for entity in entities:
        entity_id = store.upsert_entity(entity['name'], entity['kind'], entity['aliases'])
        segment_id = None
        for candidate_id, candidate_text in sentence_to_segment:
            if entity['quote'] and entity['quote'] in candidate_text:
                segment_id = candidate_id
                break
        if segment_id is None and sentence_to_segment:
            # Attribute to the segment sharing the most characters with the quote so
            # the evidence stays clickable instead of becoming document-level only.
            quote = entity['quote']
            best = max(sentence_to_segment, key=lambda pair: len(set(quote) & set(pair[1])))
            if len(set(quote) & set(best[1])) >= 4:
                segment_id = best[0]
        if segment_id is None:
            continue
        store.add_entity_mention(entity_id, document['id'], segment_id, entity['quote'])
        stored += 1
    return stored


def build_index(store, provider, document_id=None, limit=8, progress=None):
    """Index documents that have no entities yet (or exactly one document)."""
    indexed = store.entity_index_counts()
    if document_id:
        documents = [store.document(document_id)]
    else:
        documents = [d for d in store.documents() if not indexed.get(d['id'])]
    documents = documents[:limit]
    done, total_entities = [], 0
    for position, document in enumerate(documents, start=1):
        if progress:
            progress(position, len(documents), document['title'])
        count = index_document(store, provider, document)
        done.append({'document_id': document['id'], 'title': document['title'], 'entities': count})
        total_entities += count
    return {'documents': done, 'entities': total_entities,
            'remaining': max(0, len([d for d in store.documents() if not store.entity_index_counts().get(d['id'])]) if not document_id else 0)}


def shared_entities(store, document_id):
    """Other documents that share canonical entities with this one, IDF-weighted."""
    counts = store.entity_document_counts()
    total_documents = max(1, len(store.documents()))
    own = {}
    for row in store.document_entity_mentions(document_id):
        own.setdefault(row['entity_id'], {'name': row['name'], 'kind': row['kind'],
                                          'count': 0, 'segment_id': row['segment_id'], 'quote': row['quote']})
        own[row['entity_id']]['count'] += 1
    if not own:
        return []
    total_weight = {}
    per_doc = {}
    for entity_id, info in own.items():
        documents_for_entity = store.rows(
            'SELECT document_id,COUNT(*) AS mentions FROM entity_mentions WHERE entity_id=? AND document_id<>? GROUP BY document_id',
            (entity_id, document_id))
        if not documents_for_entity:
            continue
        df = counts.get(entity_id, 1)
        if df > max(2, total_documents // 2):
            continue
        # Entities present in most documents carry little signal; rare shared
        # entities carry the relation.
        weight = math.log((total_documents + 1) / (df + 0.5))
        if weight <= 0:
            continue
        for row in documents_for_entity:
            per_doc.setdefault(row['document_id'], {'weight': 0.0, 'entities': []})
            per_doc[row['document_id']]['weight'] += weight
            per_doc[row['document_id']]['entities'].append(
                {'id': entity_id, 'name': info['name'], 'kind': info['kind'],
                 'doc_mentions': info['count'], 'other_mentions': row['mentions'], 'weight': round(weight, 2),
                 'segment_id': info['segment_id'], 'quote': info['quote']})
    ranked = sorted(per_doc.items(), key=lambda item: -item[1]['weight'])
    return [{'document_id': other_id, 'weight': round(value['weight'], 2),
             'entities': sorted(value['entities'], key=lambda e: -e['weight'])}
            for other_id, value in ranked if value['weight'] >= SHARED_WEIGHT_THRESHOLD]


def describe(shared):
    parts = [f"{entity['name']}（{entity['kind']}）" for entity in shared[:4]]
    return '共同实体：' + '、'.join(parts)
