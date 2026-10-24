import hashlib
import json


class VectorIndex:
    def __init__(self, store):
        self.store = store
        self.client = None

    def open(self):
        if self.client is None:
            from qdrant_client import QdrantClient
            self.client = QdrantClient(path=str(self.store.directory / 'vectors'))
        return self.client

    @staticmethod
    def name(settings):
        identity = [settings.get(k, '') for k in ('base_url', 'embedding_url', 'embedding_model')]
        return 'segments_' + hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:16]

    def build(self, provider):
        from qdrant_client.models import Distance, PointStruct, VectorParams
        sources = self.store.segments()
        if not sources:
            raise ValueError('请先导入资料')
        client, name = self.open(), self.name(provider.settings)
        count = 0
        for offset in range(0, len(sources), 24):
            batch = sources[offset:offset + 24]
            vectors = provider.embed([s['title'] + '\n' + s['text'] for s in batch])
            if not client.collection_exists(name):
                client.create_collection(name, vectors_config=VectorParams(size=len(vectors[0]), distance=Distance.COSINE))
            client.upsert(name, points=[PointStruct(id=s['id'], vector=v, payload={'document_id': s['document_id']}) for s, v in zip(batch, vectors)])
            count += len(batch)
        return {'indexed': count, 'message': f'已为 {count} 个片段建立本地语义索引'}

    def search(self, query, provider, document_id=None, limit=8, exclude_document_id=None):
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        client, name = self.open(), self.name(provider.settings)
        if not client.collection_exists(name):
            raise ValueError('尚未建立当前模型的语义索引，请到设置中建立索引')
        vector = provider.embed([query])[0]
        filters = Filter(must=[FieldCondition(key='document_id', match=MatchValue(value=document_id))]) if document_id else None
        if exclude_document_id:
            filters = Filter(must_not=[FieldCondition(key='document_id', match=MatchValue(value=exclude_document_id))])
        points = client.query_points(name, query=vector, query_filter=filters, limit=limit).points
        live = {s['id']: s for s in self.store.segments(document_id)}
        return [{**live[str(p.id)], 'score': p.score, 'retrieval': '语义'} for p in points if str(p.id) in live]

    def remove(self, segment_ids):
        path = self.store.directory / 'vectors'
        if not path.exists():
            return
        from qdrant_client.models import PointIdsList
        client = self.open()
        for collection in client.get_collections().collections:
            client.delete(collection.name, points_selector=PointIdsList(points=segment_ids))

    def close(self):
        if self.client:
            self.client.close()
