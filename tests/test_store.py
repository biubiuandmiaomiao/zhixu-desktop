import tempfile
import unittest

from backend.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_chinese_search_survives_restart(self):
        doc = self.store.add_document('Python 闭包', '闭包能够捕获外层函数的变量。\n\n装饰器可以使用闭包。')
        self.store.close()
        self.store = Store(self.tmp.name)
        self.assertEqual(self.store.search('闭包')[0]['document_id'], doc['id'])

    def test_delete_cascades_segments_and_bookmarks(self):
        doc = self.store.add_document('闭包', '闭包保存变量。')
        seg = self.store.segments(doc['id'])[0]
        self.store.add_card(doc['id'], '闭包保存变量。', seg['id'])
        self.store.delete_document(doc['id'])
        self.assertEqual(self.store.search('闭包'), [])
        self.assertEqual(self.store.cards(), [])

    def test_preference_update_supersedes_old_memory(self):
        old = self.store.save_memory('讲解风格', '先讲理论')
        new = self.store.save_memory('讲解风格', '先给例子')
        active = self.store.memories()
        self.assertEqual([m['id'] for m in active], [new['id']])
        self.assertEqual(self.store.memories(include_inactive=True)[1]['id'], old['id'])

    def test_scope_does_not_leak(self):
        self.store.add_document('私有闭包', '闭包私有资料', workspace='other')
        self.assertEqual(self.store.search('闭包'), [])

    def test_rejected_relation_is_preserved(self):
        a = self.store.add_document('函数闭包', '函数闭包可以保存外部变量。')
        b = self.store.add_document('装饰器闭包', '装饰器通过函数闭包保存变量。')
        relation = self.store.suggest_relation(a['id'], b['id'], 'shared', '都解释函数闭包')
        self.store.set_relation(relation['id'], 'rejected')
        same = self.store.suggest_relation(a['id'], b['id'], 'shared', '新的理由')
        self.assertEqual(same['status'], 'rejected')


if __name__ == '__main__':
    unittest.main()
