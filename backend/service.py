from .knowledge import Knowledge
from .provider import Provider, redact
from .review import Review
from .store import Store
from .vectors import VectorIndex
from .mem0_engine import Mem0Engine


class Service:
    def __init__(self, directory):
        self.store = Store(directory)
        self.store.recover_jobs()
        self.vectors = VectorIndex(self.store)
        self.mem0 = Mem0Engine(self.store)

    def close(self):
        self.mem0.close()
        self.vectors.close()
        self.store.close()

    def dispatch(self, action, args=None, api_key=''):
        args = args or {}
        provider = Provider(self.store.settings(), api_key)
        knowledge = Knowledge(self.store, provider, self.vectors, self.mem0)
        review = Review(self.store, provider)
        if action == 'bootstrap':
            return {'documents': [{**d, 'content': d['content'][:180]} for d in self.store.documents()],
                    'cards': self.store.cards(), 'memories': self.store.memories(), 'sessions': self.store.sessions(),
                    'relations': self.store.relations(), 'settings': self.store.settings(),
                    'conversations': self.store.conversations(), 'data_directory': str(self.store.directory),
                    'jobs': self.store.rows('SELECT id,kind,status,error,created_at FROM jobs ORDER BY created_at DESC LIMIT 5'),
                    'mem0': self.mem0.status(provider)}
        if action == 'document':
            return {'document': self.store.document(args['id']), 'segments': self.store.segments(args['id']), 'relations': self.store.relations(args['id'])}
        if action == 'import_text':
            return knowledge.import_text(args['title'], args['content'], args.get('url', ''), args.get('subtitle', False))
        if action == 'import_video':
            return knowledge.import_video(args['url'])
        if action == 'tutorial':
            return knowledge.tutorial(args['id'])
        if action == 'update_document':
            if self.store.document(args['id'])['kind'] == 'text':
                self.mem0.remove(['segment:' + s['id'] for s in self.store.segments(args['id'])])
                self.vectors.remove([s['id'] for s in self.store.segments(args['id'])])
            return self.store.update_document(args['id'], args['title'], redact(args['content']))
        if action == 'delete_document':
            ids = [s['id'] for s in self.store.segments(args['id'])]
            self.mem0.remove(['segment:' + i for i in ids])
            self.vectors.remove(ids)
            self.store.delete_document(args['id'])
            return True
        if action == 'add_card':
            return self.store.add_card(args['document_id'], redact(args['text']), args.get('segment_id'))
        if action == 'delete_card':
            self.store.delete_card(args['id'])
            return True
        if action == 'save_memory':
            return self.store.save_memory(redact(args['title']), redact(args['text']), args.get('kind', 'preference'))
        if action == 'delete_memory':
            self.mem0.remove(['personal:' + args['id']])
            self.store.delete_memory(args['id'])
            return True
        if action == 'related':
            return knowledge.related(args['id'], args.get('use_ai', False))
        if action == 'set_relation':
            self.store.set_relation(args['id'], args['status'])
            return True
        if action == 'search':
            return knowledge.search(args['query'], args.get('document_id'))
        if action == 'ask':
            return knowledge.ask(args['question'], args.get('document_id'))
        if action == 'generate_quiz':
            return review.generate(args.get('document_id'))
        if action == 'quiz':
            return review.get(args['id'])
        if action == 'save_draft':
            return review.draft(args['id'], args['answers'])
        if action == 'submit_quiz':
            return review.submit(args['id'], args['answers'])
        if action == 'save_settings':
            self.store.save_settings(args)
            return self.store.settings()
        if action == 'test_model':
            result = provider.json('请只返回 JSON 对象 {"ok":true}。', {'test': '连接测试'})
            if result.get('ok') is not True:
                raise ValueError('服务已响应，但未按要求返回 JSON，请确认模型支持结构化文本输出')
            return {'message': '连接成功，模型可以返回 JSON'}
        if action in ('build_index', 'sync_mem0'):
            return self.mem0.sync(provider)
        raise ValueError('不支持的操作')
