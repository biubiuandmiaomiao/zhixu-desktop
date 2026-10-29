from .knowledge import Knowledge
from .provider import Provider, redact
from .review import Review
from .store import Store
from .vectors import VectorIndex
from .mem0_engine import Mem0Engine
from .media import MediaJobs
from .exports import with_embedded_frames
from .websearch import WebSearch, provider_labels


class Service:
    def __init__(self, directory):
        self.store = Store(directory)
        self.store.recover_jobs()
        self.vectors = VectorIndex(self.store)
        self.mem0 = Mem0Engine(self.store)
        self._media_api_key = ''
        self.media = MediaJobs(directory, provider_factory=lambda store: Provider(store.settings(), self._media_api_key))

    def close(self):
        self.media.close()
        self.mem0.close()
        self.vectors.close()
        self.store.close()

    def dispatch(self, action, args=None, api_key='', search_key=''):
        args = args or {}
        # Credentials stay in process memory; background jobs persist options, never keys.
        self._media_api_key = api_key
        provider = Provider(self.store.settings(), api_key)
        web = WebSearch(self.store.settings().get('web_search_provider', ''), search_key)
        knowledge = Knowledge(self.store, provider, self.vectors, self.mem0, web if web.configured else None)
        review = Review(self.store, provider, self.mem0)
        if action == 'bootstrap':
            return {'documents': [{**d, 'content': d['content'][:180], 'notebook': self.store.notebook.metadata(d['id'])} for d in self.store.documents()],
                    'cards': self.store.cards(), 'memories': self.store.memories(), 'sessions': self.store.sessions(),
                    'relations': self.store.relations(), 'settings': self.store.settings(),
                    'conversations': self.store.conversations(), 'data_directory': str(self.store.directory),
                    'jobs': self.store.rows('SELECT id,kind,status,error,created_at FROM jobs ORDER BY created_at DESC LIMIT 5'),
                    'mem0': self.mem0.status(provider), 'media_jobs': self.media.status(), 'media_active': self.media.activity()['active'],
                    'has_search_key': bool(search_key), 'web_search_providers': provider_labels(),
                    'entity_index': self.store.entity_index_counts()}
        if action == 'document':
            return {'document': self.store.document(args['id']), 'segments': self.store.segments(args['id']),
                    'relations': self.store.relations(args['id']), 'notebook': self.store.notebook.metadata(args['id']),
                    'assets': self.media.assets(args['id']), 'tutorial_attempts': self.store.tutorial_attempts(args['id'])}
        if action == 'resolve_note_link':
            return self.store.notebook.resolve_link(args['id'], args['target'])
        if action == 'note_graph':
            return self.store.notebook.graph(min(200, max(1, int(args.get('limit', 100)))))
        if action == 'note_versions':
            return self.store.notebook.versions(args['id'], preview_chars=8000)
        if action == 'restore_note_version':
            self.mem0.remove_document(args['id'])
            self.vectors.remove([s['id'] for s in self.store.segments(args['id'])])
            result = self.store.notebook.restore_version(args['id'], args['version_id'])
            self.mem0.prune()
            return result
        if action == 'toggle_note_bookmark':
            return self.store.notebook.toggle_bookmark(args['id'])
        if action == 'map_card_sources':
            return self.store.notebook.map_card_sources(args['id'], args['source_ids'])
        if action == 'export_document':
            return {'content': with_embedded_frames(self.store.notebook.export_document(args['id']), self.media.assets(args['id']))}
        # Paths arrive only through privileged native-dialog handlers, not renderer call().
        if action == 'import_vault':
            return self.store.notebook.import_vault(args['directory'])
        if action == 'export_vault':
            return self.store.notebook.export_vault(args['directory'], transform=lambda doc_id, text: with_embedded_frames(text, self.media.assets(doc_id)))
        if action == 'import_local_media':
            return self.media.start_local(args['path'], args.get('options'))
        if action == 'start_video_job':
            return self.media.start_video(args['url'], args.get('options'))
        if action == 'media_activity':
            return self.media.activity()
        if action == 'media_jobs':
            return self.media.status(args.get('id'))
        if action == 'retry_media_job':
            return self.media.retry(args['id'])
        if action == 'cancel_media_job':
            return self.media.cancel(args['id'])
        if action == 'import_text':
            return knowledge.import_text(args['title'], args['content'], args.get('url', ''), args.get('subtitle', False))
        if action == 'import_video':
            return knowledge.import_video(args['url'])
        if action == 'tutorial':
            if self.media.tutorial_running(args['id']):
                raise ValueError('此资料正在后台生成中文教程，请等待完成或先取消任务')
            images = self.media.assets(args['id']) if args.get('use_images') else []
            result = knowledge.tutorial(args['id'], args.get('style', 'tutorial'), images=images, use_images=bool(args.get('use_images')))
            self.media.mark_tutorial_completed(args['id'])
            return result
        if action == 'update_document':
            if self.store.document(args['id'])['kind'] == 'text':
                self.mem0.remove_document(args['id'])
                self.vectors.remove([s['id'] for s in self.store.segments(args['id'])])
            result = self.store.update_document(args['id'], args['title'], redact(args['content']))
            self.mem0.prune()
            return result
        if action == 'delete_document':
            ids = [s['id'] for s in self.store.segments(args['id'])]
            self.mem0.remove_document(args['id'])
            self.vectors.remove(ids)
            self.media.delete_document(args['id'])
            self.store.delete_document(args['id'])
            self.mem0.prune()
            return True
        if action == 'add_card':
            return self.store.add_card(args['document_id'], redact(args['text']), args.get('segment_id'), args.get('source_ids'))
        if action == 'delete_card':
            self.store.delete_card(args['id'])
            return True
        if action == 'save_memory':
            return self.store.save_memory(redact(args['title']), redact(args['text']), args.get('kind', 'preference'))
        if action == 'delete_memory':
            self.store.delete_memory(args['id'])
            return True
        if action == 'related':
            return knowledge.related(args['id'], args.get('use_ai', False))
        if action == 'build_entity_index':
            from .entities import build_index
            return build_index(self.store, provider, args.get('id'), limit=int(args.get('limit', 8)))
        if action == 'set_relation':
            if args['status'] != 'confirmed':
                self.mem0.remove(['relation:' + args['id']])
            self.store.set_relation(args['id'], args['status'])
            return True
        if action == 'search':
            return knowledge.search(args['query'], args.get('document_id'))
        if action == 'ask':
            return knowledge.ask(args['question'], args.get('document_id'), history=args.get('history'))
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
        if action == 'test_search':
            web = WebSearch(self.store.settings().get('web_search_provider', ''), search_key)
            if not web.configured:
                raise ValueError('请先保存联网搜索服务与搜索 API Key')
            results = web.search(str(args.get('query') or '机器学习 入门'), 3)
            return {'message': f'联网搜索可用，返回 {len(results)} 条结果',
                    'sample': [{'title': row['title'], 'url': row['url']} for row in results[:3]]}
        if action in ('build_index', 'sync_mem0'):
            return self.mem0.sync(provider)
        raise ValueError('不支持的操作')
