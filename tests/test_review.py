import copy
import tempfile
import unittest
from collections import Counter

from backend.store import Store
from backend.review import Review, ReviewError


class FixtureAI:
    def __init__(self, source_id):
        self.source_id = source_id
        self.invalid = None
        self.fail_grade = False

    def json(self, system, payload):
        if 'grades' in system:
            if self.fail_grade:
                raise RuntimeError('评分服务暂不可用')
            return {'grades': [{'question_id': q['id'], 'score': 7, 'feedback': '解释了闭包，需要补充生命周期。'}
                               for q in payload['answers']]}
        questions = []
        for i, kind in enumerate(['single'] * 4 + ['multiple'] * 3 + ['short'] * 3):
            questions.append({'type': kind, 'prompt': f'请分析闭包的第 {i + 1} 个使用场景？',
                              'options': [] if kind == 'short' else [
                                  {'id': c, 'text': f'{c}选项说明'} for c in 'ABCD'],
                              'answer': [] if kind == 'short' else (['A', 'B'] if kind == 'multiple' else ['A']),
                              'rubric': ['捕获变量', '生命周期'] if kind == 'short' else [],
                              'explanation': '闭包捕获外部变量，须考虑变量生命周期。',
                              'source_ids': [self.source_id]})
        if self.invalid == 'source':
            questions[0]['source_ids'] = ['unknown']
        if self.invalid == 'count':
            questions.pop()
        if self.invalid == 'duplicate':
            questions[1]['prompt'] = questions[0]['prompt']
        return {'questions': questions}


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.doc = self.store.add_document('闭包教程', '闭包捕获外层函数变量，返回的函数依然可以使用变量。装饰器包装函数，实现日志、重试等能力。' * 15)
        self.ai = FixtureAI(self.store.segments(self.doc['id'])[0]['id'])
        self.review = Review(self.store, self.ai)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_ten_mixed_questions_hide_answers_and_persist(self):
        session = self.review.generate()
        self.assertEqual(Counter(q['type'] for q in session['questions']), {'single': 4, 'multiple': 3, 'short': 3})
        for q in session['questions']:
            self.assertNotIn('answer', q)
            self.assertNotIn('rubric', q)
            self.assertNotIn('explanation', q)
        self.assertEqual(self.review.get(session['id'])['questions'], session['questions'])

    def test_invalid_generation_does_not_save_partial_session(self):
        for failure in ['source', 'count', 'duplicate']:
            with self.subTest(failure=failure):
                self.ai.invalid = failure
                with self.assertRaises(ReviewError):
                    self.review.generate()
                self.assertEqual(self.store.sessions(), [])

    def test_objective_exact_match_short_rubric_and_idempotency(self):
        session = self.review.generate()
        answers = {q['id']: ('闭包保存外部变量' if q['type'] == 'short' else ['A']) for q in session['questions']}
        result = self.review.submit(session['id'], answers)
        self.assertEqual(result['score'], 61)  # 4*10 + 3*0 + 3*7
        self.assertEqual(self.review.submit(session['id'], {})['score'], 61)
        self.assertIn('explanation', result['questions'][0])
        self.assertEqual(len(self.store.sessions()), 1)

    def test_grading_failure_keeps_draft_and_can_retry(self):
        session = self.review.generate()
        answers = {q['id']: ('闭包保存变量' if q['type'] == 'short' else ['A']) for q in session['questions']}
        self.ai.fail_grade = True
        with self.assertRaises(RuntimeError):
            self.review.submit(session['id'], answers)
        recovered = self.review.get(session['id'])
        self.assertEqual(recovered['status'], 'draft')
        self.assertEqual(recovered['answers'], answers)
        self.ai.fail_grade = False
        self.assertEqual(self.review.submit(session['id'], answers)['status'], 'completed')

    def test_recent_duplicate_questions_rejected(self):
        self.review.generate()
        with self.assertRaises(ReviewError):
            self.review.generate()

    def test_deleting_source_removes_related_quiz(self):
        session = self.review.generate()
        self.store.delete_document(self.doc['id'])
        self.assertEqual(self.store.sessions(), [])


if __name__ == '__main__':
    unittest.main()
