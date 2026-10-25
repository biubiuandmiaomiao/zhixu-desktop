import json
import tempfile
import unittest
from pathlib import Path

from backend.store import Store


class NotebookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'data')

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def notebook(self):
        self.assertTrue(hasattr(self.store, 'notebook'), 'Store must expose notebook services')
        return self.store.notebook

    def test_formatted_selection_maps_to_original_evidence(self):
        doc = self.store.add_document('格式', '**闭包**捕获外部变量。' * 40)
        card = self.store.add_card(doc['id'], '闭包捕获外部变量。' * 20)
        self.assertTrue(card.get('source_ids'), 'Rendered selections need original segment IDs')
        sources = self.store.sample_sources('__cards__')
        self.assertTrue(sources)
        self.assertIn('**闭包**', sources[0]['text'])
        self.assertFalse(card['stale'])

    def test_selection_across_chunks_maps_both_original_segments(self):
        text = 'a' * 880 + '闭包捕获变量并跨过分段边界。' * 8 + 'z' * 100
        doc = self.store.add_document('跨段', text)
        card = self.store.add_card(doc['id'], text[880:980])
        self.assertEqual(len(card.get('source_ids', [])), 2)

    def test_paraphrase_requires_explicit_owned_sources(self):
        doc = self.store.add_document('原文', '闭包保留变量。' * 40)
        segment = self.store.segments(doc['id'])[0]
        other = self.store.add_document('另一份', '其他原文。')
        self.assertTrue(hasattr(self.store, 'notebook'), 'Explicit card evidence is missing')
        with self.assertRaisesRegex(ValueError, '来源'):
            self.store.add_card(doc['id'], '变量背包', source_ids=[self.store.segments(other['id'])[0]['id']])
        card = self.store.add_card(doc['id'], '闭包就像变量背包。', source_ids=[segment['id']])
        sampled = self.store.sample_sources('__cards__')
        self.assertEqual(sampled[0]['text'], segment['text'])
        self.assertNotIn('变量背包', sampled[0]['text'])
        self.assertEqual(card['source_ids'], [segment['id']])

    def test_unmapped_favorite_is_explicit_and_blocks_silent_review_omission(self):
        doc = self.store.add_document('原文', '闭包保留变量。' * 40)
        card = self.store.add_card(doc['id'], '没有对应原文的改写。')
        self.assertTrue(card.get('unmapped'), 'Unmapped excerpts must be explicit')
        with self.assertRaisesRegex(ValueError, '收藏.*来源'):
            self.store.sample_sources('__cards__')

    def test_source_edit_keeps_immutable_card_evidence_without_searching_it(self):
        doc = self.store.add_document('旧文', '闭包保留变量。' * 40)
        segment = self.store.segments(doc['id'])[0]
        self.store.add_card(doc['id'], '闭包保留变量。', segment['id'])
        self.store.update_document(doc['id'], '新文', '继承复用父类。' * 40)
        card = self.store.cards()[0]
        self.assertTrue(card.get('stale'), 'Stale cards must not look current')
        self.assertEqual(card['source_snapshots'][0]['text'], segment['text'])
        self.assertEqual(self.store.search('闭包'), [])
        with self.assertRaisesRegex(ValueError, '收藏.*来源'):
            self.store.sample_sources('__cards__')

    def test_portable_markdown_roundtrip_remaps_original_sources(self):
        notebook = self.notebook()
        raw = '闭包保留外层变量。' * 40
        doc = self.store.add_document('视频教程', raw, 'https://www.bilibili.com/video/BV1xx411c7mD/',
                                      kind='subtitle', segments=[{'text': raw, 'start': 72.5}])
        old_id = self.store.segments(doc['id'])[0]['id']
        body = '---\ntags: [python, 学习/闭包]\n---\n# 教程\n解释。 [来源:' + old_id + ']'
        self.store.update_document(doc['id'], doc['title'], body, preserve_sources=True)
        exported = notebook.export_document(doc['id'])
        imported = self.store.add_document('文件名', exported)
        new_id = self.store.segments(imported['id'])[0]['id']
        self.assertNotEqual(imported['id'], doc['id'])
        self.assertNotEqual(new_id, old_id)
        self.assertIn('[来源:' + new_id + ']', imported['content'])
        self.assertNotIn('[来源:' + old_id + ']', imported['content'])
        self.assertEqual(imported['url'], doc['url'])
        self.assertEqual(imported['kind'], 'subtitle')
        self.assertEqual(self.store.segments(imported['id'])[0]['start'], 72.5)
        self.assertEqual(self.store.segments(imported['id'])[0]['text'], raw)
        self.assertEqual(notebook.metadata(imported['id'])['tags'], ['python', '学习/闭包'])

    def test_malformed_portable_metadata_does_not_import_unbounded_or_invalid_sources(self):
        notebook = self.notebook()
        doc = self.store.add_document('正常', '正文')
        exported = notebook.export_document(doc['id'])
        corrupted = exported.replace('"start": null', '"start": -4')
        self.assertNotEqual(corrupted, exported)
        with self.assertRaisesRegex(ValueError, '来源|元数据'):
            self.store.add_document('坏文件', corrupted)

    def test_tags_wikilinks_markdown_links_backlinks_ignore_code(self):
        notebook = self.notebook()
        target = self.store.add_document('目标', '# 章节\n证据')
        source = self.store.add_document('来源',
            '---\ntags:\n  - python\n  - 学习/闭包\n---\n'
            '[[目标#章节|别名]] 与 [更多](目标.md#章节) #笔记\n'
            '`[[代码目标]] #代码`\n```md\n[[忽略]] #忽略\n```')
        meta = notebook.metadata(source['id'])
        self.assertEqual(meta['tags'], ['python', '学习/闭包', '笔记'])
        self.assertEqual([row['document_id'] for row in meta['outgoing']], [target['id'], target['id']])
        self.assertEqual({row['kind'] for row in meta['outgoing']}, {'wiki', 'markdown'})
        self.assertEqual(meta['outgoing'][0]['heading'], '章节')
        self.assertEqual(len(notebook.metadata(target['id'])['backlinks']), 2)

    def test_ambiguous_target_is_explicit_and_relative_path_has_priority(self):
        notebook = self.notebook()
        root = Path(self.tmp.name) / 'vault'
        (root / 'one').mkdir(parents=True)
        (root / 'two').mkdir()
        (root / 'one' / 'Target.md').write_text('one', encoding='utf8')
        (root / 'two' / 'Target.md').write_text('two', encoding='utf8')
        (root / 'one' / 'Start.md').write_text('[[Target]]', encoding='utf8')
        notebook.import_vault(root)
        source = next(d for d in self.store.documents() if d['title'] == 'Start')
        resolved = notebook.resolve_link(source['id'], 'Target')
        self.assertFalse(resolved['unresolved'])
        self.assertEqual(notebook.metadata(resolved['document_id'])['path'], 'one/Target.md')
        global_source = self.store.add_document('Root', '[[Target]]')
        ambiguous = notebook.resolve_link(global_source['id'], 'Target')
        self.assertTrue(ambiguous['unresolved'])
        self.assertEqual(ambiguous['reason'], 'ambiguous')
        self.assertEqual(len(ambiguous['candidates']), 2)

    def test_rename_keeps_target_identity_and_delete_does_not_rebind(self):
        notebook = self.notebook()
        target = self.store.add_document('旧标题', '正文')
        source = self.store.add_document('来源', '[[旧标题]]')
        self.store.update_document(target['id'], '新标题', '新正文')
        self.assertEqual(notebook.resolve_link(source['id'], '旧标题')['document_id'], target['id'])
        self.store.delete_document(target['id'])
        self.store.add_document('旧标题', '重名的新笔记')
        result = notebook.resolve_link(source['id'], '旧标题')
        self.assertTrue(result['unresolved'])
        self.assertEqual(result['reason'], 'deleted')

    def test_edit_refreshes_outgoing_backlinks_and_tags(self):
        notebook = self.notebook()
        a = self.store.add_document('甲', '正文')
        b = self.store.add_document('乙', '正文')
        source = self.store.add_document('来源', '[[甲]] #旧标签')
        self.store.update_document(source['id'], '来源', '[[乙]] #新标签')
        self.assertEqual(notebook.metadata(a['id'])['backlinks'], [])
        self.assertEqual(len(notebook.metadata(b['id'])['backlinks']), 1)
        self.assertEqual(notebook.metadata(source['id'])['tags'], ['新标签'])

    def test_bookmark_and_metadata_persist_on_restart(self):
        notebook = self.notebook()
        doc = self.store.add_document('笔记', '正文 #标签')
        self.assertTrue(notebook.toggle_bookmark(doc['id'])['bookmarked'])
        self.store.close()
        self.store = Store(Path(self.tmp.name) / 'data')
        self.assertTrue(self.store.notebook.metadata(doc['id'])['bookmarked'])
        self.assertFalse(self.store.notebook.toggle_bookmark(doc['id'])['bookmarked'])

    def test_graph_distinguishes_links_from_confirmed_relations_and_bounds_nodes(self):
        notebook = self.notebook()
        a = self.store.add_document('甲', '[[乙]]')
        b = self.store.add_document('乙', '原文')
        c = self.store.add_document('丙', '原文')
        confirmed = self.store.suggest_relation(a['id'], b['id'], 'shared', '同概念')
        self.store.set_relation(confirmed['id'], 'confirmed')
        self.store.suggest_relation(a['id'], c['id'], 'difference', '未确认')
        graph = notebook.graph()
        self.assertEqual({edge['kind'] for edge in graph['edges']}, {'wiki', 'relation'})
        self.assertEqual(len(graph['edges']), 2)
        self.assertEqual(len(notebook.graph(limit=1)['nodes']), 1)
        self.assertTrue(notebook.graph(limit=1)['truncated'])
        with self.assertRaises(ValueError):
            notebook.graph(limit=201)

    def test_version_restore_records_new_revision_and_restores_original_sources(self):
        notebook = self.notebook()
        doc = self.store.add_document('第一版', '闭包原文。' * 40)
        first = notebook.versions(doc['id'])[0]
        self.store.update_document(doc['id'], '第二版', '继承原文。' * 40)
        restored = notebook.restore_version(doc['id'], first['id'])
        self.assertEqual(restored['title'], '第一版')
        self.assertEqual(restored['content'], doc['content'])
        self.assertEqual(len(notebook.versions(doc['id'])), 3)
        self.assertEqual(self.store.search('继承'), [])
        self.assertEqual(self.store.search('闭包')[0]['document_id'], doc['id'])
        self.assertEqual(notebook.versions(doc['id'])[0]['reason'], 'restore')

    def test_vault_roundtrip_preserves_relative_paths_and_refuses_symlink_traversal(self):
        notebook = self.notebook()
        root = Path(self.tmp.name) / 'vault'
        (root / 'course').mkdir(parents=True)
        (root / 'course' / 'Start.md').write_text('[[../Target#标题]] #学习', encoding='utf8')
        (root / 'Target.md').write_text('# 标题\n知识', encoding='utf8')
        result = notebook.import_vault(root)
        self.assertEqual(result['imported'], 2)
        start = next(d for d in self.store.documents() if d['title'] == 'Start')
        target = next(d for d in self.store.documents() if d['title'] == 'Target')
        self.assertEqual(notebook.resolve_link(start['id'], '../Target#标题')['document_id'], target['id'])
        destination = Path(self.tmp.name) / 'export'
        notebook.export_vault(destination)
        self.assertTrue((destination / 'course' / 'Start.md').is_file())
        self.assertTrue((destination / 'Target.md').is_file())
        outside = Path(self.tmp.name) / 'outside'
        outside.mkdir()
        (outside / 'Private.md').write_text('不允许遍历', encoding='utf8')
        try:
            (root / 'linked').symlink_to(outside, target_is_directory=True)
        except OSError:
            return
        imported = notebook.import_vault(root)
        self.assertFalse(any(d['title'] == 'Private' for d in imported['documents']))

    def test_export_never_overwrites_existing_changed_files(self):
        notebook = self.notebook()
        self.store.add_document('笔记', '正文')
        destination = Path(self.tmp.name) / 'export'
        destination.mkdir()
        (destination / '笔记.md').write_text('用户现有文件', encoding='utf8')
        notebook.export_vault(destination)
        self.assertEqual((destination / '笔记.md').read_text(encoding='utf8'), '用户现有文件')
        self.assertEqual(len(list(destination.glob('*.md'))), 2)

    def test_search_combines_nested_tag_path_file_and_free_text(self):
        self.notebook()
        wanted = self.store.add_document('闭包教程', '闭包捕获外部变量。', source_path='course/python/closure.md')
        self.store.update_document(wanted['id'], wanted['title'], wanted['content'] + ' #学习/Python')
        self.store.add_document('其他课程', '闭包只在其他课程提到。 #学习/Python', source_path='other/closure.md')
        self.store.add_document('闭包教程', '闭包未打学习标签。', source_path='course/python/untagged.md')
        rows = self.store.search('tag:学习 path:course file:closure 闭包')
        self.assertEqual({r['document_id'] for r in rows}, {wanted['id']})
        self.assertEqual(rows[0]['title'], wanted['title'])
        self.assertEqual(self.store.search('tag:学习/Python path:course')[0]['document_id'], wanted['id'])
        self.assertEqual(self.store.search('tag:不存在'), [])

    def test_search_treats_filter_wildcards_literally(self):
        self.notebook()
        self.store.add_document('标签', '有标签的正文。 #学习/Python')
        self.assertEqual(self.store.search('tag:%'), [])
        self.assertEqual(self.store.search('file:%'), [])

    def test_reassign_stale_card_requires_current_owned_original_evidence(self):
        notebook = self.notebook()
        self.assertTrue(hasattr(notebook, 'map_card_sources'), 'Cards need an explicit source repair action')
        doc = self.store.add_document('笔记', '旧原文。' * 100)
        card = self.store.add_card(doc['id'], '旧原文。' * 10)
        self.store.update_document(doc['id'], '笔记', '新的原始资料。' * 100)
        self.assertTrue(self.store.cards()[0]['stale'])
        other = self.store.add_document('其他资料', '其他原文。')
        with self.assertRaisesRegex(ValueError, '来源'):
            notebook.map_card_sources(card['id'], [self.store.segments(other['id'])[0]['id']])
        with self.assertRaisesRegex(ValueError, '来源'):
            notebook.map_card_sources(card['id'], [])
        current = self.store.segments(doc['id'])[0]
        mapped = notebook.map_card_sources(card['id'], [current['id']])
        self.assertFalse(mapped['stale'])
        self.assertFalse(mapped['unmapped'])
        self.assertEqual(mapped['text'], card['text'])
        self.assertEqual(self.store.sample_sources('__cards__')[0]['text'], current['text'])

    def test_unclosed_fenced_code_and_escaped_wikilinks_are_not_real_links(self):
        notebook = self.notebook()
        self.store.add_document('目标', '正文')
        doc = self.store.add_document('代码示例', '\\[[目标]]\n```md\n[[目标]] #代码标签')
        self.assertEqual(notebook.metadata(doc['id'])['outgoing'], [])
        self.assertEqual(notebook.metadata(doc['id'])['tags'], [])

    def test_saved_callback_commits_media_state_with_document_or_rolls_back_both(self):
        self.notebook()
        self.assertIn('on_saved', __import__('inspect').signature(self.store.add_document).parameters,
                      'Media state must be saved in the same document transaction')
        job_id = self.store.job('media', {'source': 'synthetic'})

        def failing(doc_id):
            self.assertEqual(self.store.document(doc_id)['title'], '失败媒体')
            self.assertTrue(self.store.notebook.versions(doc_id))
            self.store.db.execute("UPDATE jobs SET status='completed' WHERE id=?", (job_id,))
            raise ValueError('模拟保存失败')

        with self.assertRaisesRegex(ValueError, '模拟保存失败'):
            self.store.add_document('失败媒体', '媒体来源', on_saved=failing)
        self.assertEqual(self.store.documents(), [])
        self.assertEqual(self.store.rows('SELECT * FROM segments'), [])
        self.assertEqual(self.store.rows('SELECT * FROM note_meta'), [])
        self.assertEqual(self.store.rows('SELECT * FROM document_versions'), [])
        self.assertEqual(self.store.rows('SELECT status FROM jobs WHERE id=?', (job_id,))[0]['status'], 'running')

        doc = self.store.add_document('成功媒体', '媒体来源',
            on_saved=lambda doc_id: self.store.db.execute("UPDATE jobs SET status='completed',payload=? WHERE id=?", (json.dumps({'document_id': doc_id}), job_id)))
        self.assertEqual(json.loads(self.store.rows('SELECT payload FROM jobs WHERE id=?', (job_id,))[0]['payload'])['document_id'], doc['id'])
        self.assertEqual(self.store.rows('SELECT status FROM jobs WHERE id=?', (job_id,))[0]['status'], 'completed')

    def test_portable_export_preserves_exact_body_trailing_whitespace(self):
        notebook = self.notebook()
        body = '# 原样正文\n\n有意保留末尾换行。  \n\n\n'
        doc = self.store.add_document('原样', body)
        copied = self.store.add_document('复制', notebook.export_document(doc['id']))
        self.assertEqual(copied['content'], body)

    def test_baseline_database_upgrade_preserves_document_and_card_identity(self):
        notebook = self.notebook()
        doc = self.store.add_document('旧资料', '闭包保留变量。 #旧标签')
        segment = self.store.segments(doc['id'])[0]
        card = self.store.add_card(doc['id'], '闭包保留变量。', segment['id'])
        # These are the only new tables; removing them recreates the baseline
        # schema without touching the original documents/cards/search records.
        for table in ('note_links', 'note_tags', 'note_aliases', 'note_meta', 'document_versions', 'card_provenance'):
            self.store.db.execute('DROP TABLE ' + table)
        self.store.db.commit()
        self.store.close()
        self.store = Store(Path(self.tmp.name) / 'data')
        self.assertEqual(self.store.document(doc['id'])['content'], doc['content'])
        self.assertEqual(self.store.cards()[0]['id'], card['id'])
        self.assertEqual(self.store.cards()[0]['source_ids'], [segment['id']])
        self.assertFalse(self.store.cards()[0]['stale'])
        self.assertEqual(self.store.notebook.metadata(doc['id'])['tags'], ['旧标签'])
        self.assertEqual(len(self.store.notebook.versions(doc['id'])), 1)

    def test_vault_export_collision_rewrites_links_to_the_exported_note(self):
        notebook = self.notebook()
        self.store.add_document('Target', '真实目标原文')
        self.store.add_document('Source', '[[Target#标题|显示名]]\n`[[Target]]`')
        destination = Path(self.tmp.name) / 'colliding-export'
        destination.mkdir()
        (destination / 'Target.md').write_text('用户无关的现有文件', encoding='utf8')
        exported = notebook.export_vault(destination)
        self.assertEqual(exported['exported'], 2)
        self.assertIn('[[Target-', (destination / 'Source.md').read_text(encoding='utf8'))
        other = Store(Path(self.tmp.name) / 'second-data')
        try:
            other.notebook.import_vault(destination)
            source = next(d for d in other.documents() if d['title'] == 'Source')
            link = other.notebook.metadata(source['id'])['outgoing'][0]
            target = other.document(link['document_id'])
            self.assertEqual(target['content'], '真实目标原文')
            self.assertIn('`[[Target]]`', source['content'])
            self.assertEqual(link['heading'], '标题')
        finally:
            other.close()

    def test_vault_export_transform_keeps_portable_provenance_and_planned_paths(self):
        from backend.exports import with_embedded_frames
        notebook = self.notebook()
        self.assertIn('transform', __import__('inspect').signature(notebook.export_vault).parameters,
                      'Managed screenshots need a bounded export transform')
        doc = self.store.add_document('视频', '字幕原文', 'https://www.bilibili.com/video/BV1xx411c7mD/',
                                      kind='subtitle', segments=[{'text': '字幕原文', 'start': 12.5}])
        destination = Path(self.tmp.name) / 'transformed-vault'
        destination.mkdir()
        (destination / '视频.md').write_text('已有用户文件', encoding='utf8')
        calls = []

        def transform(doc_id, text):
            calls.append(doc_id)
            return with_embedded_frames(text, [{'data_url': 'data:image/jpeg;base64,YWJj', 'start': 12.5}])

        result = notebook.export_vault(destination, transform=transform)
        self.assertEqual(calls, [doc['id']])
        self.assertEqual(result['exported'], 1)
        self.assertEqual((destination / '视频.md').read_text(encoding='utf8'), '已有用户文件')
        output = (destination / result['documents'][0]['path']).read_text(encoding='utf8')
        self.assertIn('![视频截图 00:12](data:image/jpeg;base64,YWJj)', output)
        copied = self.store.add_document('复制', output)
        self.assertEqual(copied['url'], doc['url'])
        self.assertEqual(self.store.segments(copied['id'])[0]['start'], 12.5)
        self.assertIn('## 视频截图', copied['content'])

    def test_vault_export_transform_failure_skips_only_that_document(self):
        notebook = self.notebook()
        self.assertIn('transform', __import__('inspect').signature(notebook.export_vault).parameters,
                      'Transform errors must be isolated to a skipped note')
        broken = self.store.add_document('失败', '仍保留的原文')
        self.store.add_document('成功', '正常原文')

        def transform(doc_id, text):
            if doc_id == broken['id']:
                raise RuntimeError('合成图片失败')
            return text

        destination = Path(self.tmp.name) / 'transform-error'
        result = notebook.export_vault(destination, transform=transform)
        self.assertEqual(result['exported'], 1)
        self.assertEqual(len(result['skipped']), 1)
        self.assertIn('合成图片失败', result['skipped'][0]['reason'])
        self.assertFalse((destination / '失败.md').exists())
        self.assertTrue((destination / '成功.md').is_file())

    def test_import_cohort_prefers_its_target_without_changing_existing_bindings(self):
        notebook = self.notebook()
        existing = self.store.add_document('Target', '现有用户资料')
        previous = self.store.add_document('Existing source', '[[Target]]')
        vault = Path(self.tmp.name) / 'cohort'
        vault.mkdir()
        (vault / 'A.md').write_text('[[Target]]', encoding='utf8')
        (vault / 'Target.md').write_text('本次导入目标', encoding='utf8')
        imported = notebook.import_vault(vault)['documents']
        source = next(d for d in imported if d['title'] == 'A')
        target = next(d for d in imported if d['title'] == 'Target')
        self.assertEqual(notebook.resolve_link(source['id'], 'Target')['document_id'], target['id'])
        self.assertEqual(notebook.resolve_link(previous['id'], 'Target')['document_id'], existing['id'])

    def test_version_restore_keeps_deleted_target_identity(self):
        notebook = self.notebook()
        old_target = self.store.add_document('B', '原目标')
        source = self.store.add_document('A', '[[B]]')
        version = notebook.versions(source['id'])[0]
        self.store.update_document(source['id'], 'A', '已移除链接')
        self.store.delete_document(old_target['id'])
        self.store.add_document('B', '无关的新资料')
        notebook.restore_version(source['id'], version['id'])
        resolved = notebook.resolve_link(source['id'], 'B')
        self.assertTrue(resolved['unresolved'])
        self.assertEqual(resolved['reason'], 'deleted')

    def test_portable_deleted_binding_never_retargets_same_named_note(self):
        notebook = self.notebook()
        target = self.store.add_document('B', '原目标')
        source = self.store.add_document('A', '[[B]]')
        self.store.delete_document(target['id'])
        exported = notebook.export_document(source['id'])
        other = Store(Path(self.tmp.name) / 'portable-deleted')
        try:
            other.add_document('B', '无关的现有资料')
            copied = other.add_document('A', exported)
            resolved = other.notebook.resolve_link(copied['id'], 'B')
            self.assertTrue(resolved['unresolved'])
            self.assertEqual(resolved['reason'], 'deleted')
        finally:
            other.close()

    def test_portable_live_binding_requires_exact_identity_or_same_import_cohort(self):
        notebook = self.notebook()
        target = self.store.add_document('Target', '权威目标')
        source = self.store.add_document('A', '[[Target]]')
        exported_source = notebook.export_document(source['id'])
        # An exact surviving UUID is safe in the same store.
        copied = self.store.add_document('A copy', exported_source)
        self.assertEqual(notebook.resolve_link(copied['id'], 'Target')['document_id'], target['id'])
        other = Store(Path(self.tmp.name) / 'portable-cohort')
        try:
            unrelated = other.add_document('Target', '无关目标')
            copied_alone = other.add_document('A alone', exported_source)
            self.assertTrue(other.notebook.resolve_link(copied_alone['id'], 'Target')['unresolved'])
            vault = Path(self.tmp.name) / 'portable-cohort-vault'
            vault.mkdir()
            (vault / 'A.md').write_text(exported_source, encoding='utf8')
            (vault / 'Target.md').write_text(notebook.export_document(target['id']), encoding='utf8')
            imported = other.notebook.import_vault(vault)['documents']
            imported_a = next(d for d in imported if d['title'] == 'A')
            imported_target = next(d for d in imported if d['title'] == 'Target')
            self.assertNotEqual(imported_target['id'], unrelated['id'])
            self.assertEqual(other.notebook.resolve_link(imported_a['id'], 'Target')['document_id'], imported_target['id'])
            self.assertTrue(other.notebook.resolve_link(copied_alone['id'], 'Target')['unresolved'])
        finally:
            other.close()

    def test_previously_unresolved_version_learns_its_first_binding(self):
        notebook = self.notebook()
        source = self.store.add_document('A', '[[B]]')
        version = notebook.versions(source['id'])[0]
        self.assertTrue(notebook.resolve_link(source['id'], 'B')['unresolved'])
        target = self.store.add_document('B', '首次目标')
        self.assertEqual(notebook.resolve_link(source['id'], 'B')['document_id'], target['id'])
        self.store.update_document(source['id'], 'A', '移除链接')
        self.store.delete_document(target['id'])
        self.store.add_document('B', '后来无关的同名目标')
        notebook.restore_version(source['id'], version['id'])
        self.assertTrue(notebook.resolve_link(source['id'], 'B')['unresolved'])

    def test_legacy_version_without_binding_snapshot_stays_explicitly_unresolved(self):
        notebook = self.notebook()
        self.assertIn('links', {r['name'] for r in self.store.rows('PRAGMA table_info(document_versions)')},
                      'Versions need an additive historical link snapshot')
        target = self.store.add_document('B', '旧目标')
        source = self.store.add_document('A', '[[B]]')
        old_version = notebook.versions(source['id'])[0]
        self.store.update_document(source['id'], 'A', '当前正文没有链接')
        self.store.delete_document(target['id'])
        self.store.db.execute('ALTER TABLE document_versions DROP COLUMN links')
        self.store.db.execute('ALTER TABLE note_links DROP COLUMN binding_state')
        self.store.db.commit()
        self.store.close()
        self.store = Store(Path(self.tmp.name) / 'data')
        self.store.add_document('B', '新同名资料')
        self.store.notebook.restore_version(source['id'], old_version['id'])
        result = self.store.notebook.resolve_link(source['id'], 'B')
        self.assertTrue(result['unresolved'])
        self.assertEqual(result['reason'], 'history_unknown')
        unbound = self.store.add_document('New', '[[Future]]')
        future = self.store.add_document('Future', '新建目标')
        self.assertEqual(self.store.notebook.resolve_link(unbound['id'], 'Future')['document_id'], future['id'])

    def test_large_chinese_portable_file_roundtrip_uses_shared_24mb_limit(self):
        notebook = self.notebook()
        body = '学' * 1_350_000
        doc = self.store.add_document('大笔记', body)
        destination = Path(self.tmp.name) / 'large-export'
        exported = notebook.export_vault(destination)
        output = destination / exported['documents'][0]['path']
        self.assertGreater(output.stat().st_size, 8_000_000)
        self.assertLess(output.stat().st_size, 24_000_000)
        other = Store(Path(self.tmp.name) / 'large-import')
        try:
            result = other.notebook.import_vault(destination)
            self.assertEqual(result['imported'], 1, result['skipped'])
            self.assertEqual(result['documents'][0]['content'], body)
        finally:
            other.close()

    def test_version_previews_are_bounded_in_sql_without_loading_source_blobs(self):
        notebook = self.notebook()
        self.assertIn('preview_chars', __import__('inspect').signature(notebook.versions).parameters,
                      'Version list needs a bounded SQL preview')
        doc = self.store.add_document('版本', '旧正文' * 10000)
        self.store.update_document(doc['id'], '版本', '新正文' * 10000)
        queries = []
        self.store.db.set_trace_callback(queries.append)
        try:
            previews = notebook.versions(doc['id'], preview_chars=128)
        finally:
            self.store.db.set_trace_callback(None)
        self.assertEqual(len(previews), 2)
        self.assertTrue(all(len(v['content']) == 128 and v['preview_truncated'] and v['full_length'] == 30000 for v in previews))
        selected = [q.lower() for q in queries if 'from document_versions' in q.lower()]
        self.assertTrue(selected)
        self.assertTrue(all('substr(content' in q and 'sources' not in q and 'select *' not in q for q in selected))
        self.assertEqual(len(notebook.versions(doc['id'])[0]['content']), 30000)

    def test_single_portable_note_remaps_its_self_heading_binding(self):
        notebook = self.notebook()
        original = self.store.add_document('Self', '# Section\n[[#Section]]')
        copied = self.store.add_document('copy', notebook.export_document(original['id']))
        self.assertEqual(notebook.resolve_link(copied['id'], '#Section')['document_id'], copied['id'])

    def test_ambiguous_imported_identity_is_excluded_from_graph_and_backlinks(self):
        notebook = self.notebook()
        original = self.store.add_document('Target', '原目标')
        source = self.store.add_document('A', '[[Target]]')
        vault = Path(self.tmp.name) / 'ambiguous-identities'
        vault.mkdir()
        (vault / 'A.md').write_text(notebook.export_document(source['id']), encoding='utf8')
        portable_target = notebook.export_document(original['id'])
        (vault / 'One.md').write_text(portable_target, encoding='utf8')
        (vault / 'Two.md').write_text(portable_target, encoding='utf8')
        imported = notebook.import_vault(vault)['documents']
        copied_a = next(d for d in imported if d['title'] == 'A')
        self.assertTrue(notebook.resolve_link(copied_a['id'], 'Target')['unresolved'])
        self.assertFalse(any(edge['source'] == copied_a['id'] for edge in notebook.graph()['edges']))
        self.assertFalse(any(link['document_id'] == copied_a['id'] for link in notebook.metadata(original['id'])['backlinks']))

    def test_portable_roundtrip_accepts_10001_admitted_caption_rows(self):
        notebook = self.notebook()
        captions = [{'text': f'字幕行 {i}', 'start': float(i)} for i in range(10001)]
        original = self.store.add_document('长字幕', '已导入的字幕资料', kind='subtitle', segments=captions)
        exported = notebook.export_document(original['id'])
        try:
            copied = self.store.add_document('复制', exported)
        except ValueError as exc:
            self.fail(f'An admitted caption document must import its own portable export: {exc}')
        sources = self.store.segments(copied['id'])
        self.assertEqual(len(sources), 10001)
        self.assertEqual(sources[-1]['text'], captions[-1]['text'])
        self.assertEqual(sources[-1]['start'], captions[-1]['start'])


if __name__ == '__main__':
    unittest.main()
