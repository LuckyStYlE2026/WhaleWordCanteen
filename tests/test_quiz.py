# -*- coding: utf-8 -*-
"""考试会话测试:抽题权重、熟/模糊/生分类。

最要紧的两条:
  · 权重偏向错得多的词,但"偏重"不是"只考"(否则用户看不到进步)
  · 一个词只要错过一次就归到生词(分类规则必须可解释)

以及一条回归锁:**毕业与否不影响抽题**(2026-10-12 用户反馈)——
考试是用户主动发起的检验,选了什么就考什么;以前按"毕业且没到期"
把词滤出抽题池,造成"想考自己选的词包却被告知没词可考"。
该复习什么由「开始复习」那条路管,见 test_session_plans 的说明。
"""

import random
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.interfaces import JudgeResult                     # noqa: E402
from core.models import (                                   # noqa: E402
    BUCKET_FUZZY,
    BUCKET_KNOWN,
    BUCKET_NEW,
    Grade,
    Word,
    WordState,
)
from core.packs import PACK_TYPE_EXAM                       # noqa: E402
from core.quiz import (                                     # noqa: E402
    ExamSession,
    classify,
    mistake_words,
    sampling_weight,
    weighted_sample,
)
from core.scheduler import EbbinghausScheduler                 # noqa: E402

TODAY = date(2026, 10, 12)


def make_word(word_id="w_1", word="bank", translation="银行", **state_kwargs):
    return Word(id=word_id, spelling_key=word, word=word, translation=translation,
                state=WordState(**state_kwargs))


class StubJudge:
    """假判分器:照剧本返回结果,不关心答案内容。

    用假的而不是真的 OfflineJudge,是为了让"考试流程"的测试不受
    判分算法改动的影响 —— 判分算法有自己的测试文件。
    """

    def __init__(self, script):
        """script 是 {单词: Grade} 或者一个固定的 Grade。"""
        self.script = script
        self.calls = []

    def judge(self, word, answer):
        self.calls.append((word.id, answer))
        grade = self.script.get(word.id) if isinstance(self.script, dict) else self.script
        return JudgeResult(grade=grade, score=1.0, feedback="")


# --------------------------------------------------------------------------
# 抽题
# --------------------------------------------------------------------------

class TestSamplingWeight(unittest.TestCase):

    def test_fresh_word_has_base_weight(self):
        self.assertEqual(sampling_weight(make_word()), 1.0)

    def test_wrong_answers_weigh_more_than_fuzzy_ones(self):
        """错一次加 2,模糊一次加 1 —— 错比模糊更该被重视。"""
        wrong = make_word(wrong_count=1)
        fuzzy = make_word(fuzzy_count=1)
        self.assertEqual(sampling_weight(wrong), 3.0)
        self.assertEqual(sampling_weight(fuzzy), 2.0)
        self.assertGreater(sampling_weight(wrong), sampling_weight(fuzzy))

    def test_graduated_word_keeps_its_weight(self):
        """回归锁:连续答对很多次也不该把词逐出抽题池。

        考试考的是用户挑的词包,选了什么就考什么(2026-10-12 反馈);
        "该不该复习"由「开始复习」按记忆曲线决定,不是考试的事。
        """
        word = make_word(streak_correct=99, next_review="2026-12-01")
        self.assertEqual(sampling_weight(word), 1.0)


class TestWeightedSample(unittest.TestCase):

    def test_size_zero_returns_nothing(self):
        self.assertEqual(weighted_sample([make_word()], 0), [])

    def test_pool_smaller_than_request_returns_everything(self):
        """新用户词很少,不该因为"凑不齐 20 个"就考不了试。"""
        pool = [make_word("w_%d" % i, "w%d" % i) for i in range(3)]
        self.assertEqual(len(weighted_sample(pool, 20)), 3)

    def test_sample_has_no_duplicates(self):
        pool = [make_word("w_%d" % i, "w%d" % i) for i in range(10)]
        chosen = weighted_sample(pool, 5, rng=random.Random(1))
        self.assertEqual(len(chosen), 5)
        self.assertEqual(len({word.id for word in chosen}), 5, "抽样结果不该有重复")

    def test_graduated_words_are_still_sampled(self):
        """回归锁:全"毕业"的池子也照样出题,不再返回空。"""
        pool = [make_word("w_1", "a", streak_correct=99),
                make_word("w_2", "b", streak_correct=99)]
        chosen = weighted_sample(pool, 5, rng=random.Random(1))
        self.assertEqual(sorted(word.id for word in chosen), ["w_1", "w_2"])

    def test_weak_words_dominate_the_pool(self):
        """抽 200 次单抽,常错的词应该明显更常被抽到。

        这是"错题本加权"这个设计存在的意义 —— 如果权重不生效,
        考试就只是在随机重复,对用户没有帮助。
        """
        weak = make_word("w_weak", "weak", wrong_count=5)   # 权重 11
        fresh = make_word("w_fresh", "fresh")               # 权重 1
        rng = random.Random(20261012)
        picks = [weighted_sample([weak, fresh], 1, rng=rng)[0].id
                 for _ in range(200)]
        self.assertGreater(picks.count("w_weak"), 140,
                           "常错词应该占绝大多数,实际 %d/200" % picks.count("w_weak"))


class TestMistakeBook(unittest.TestCase):

    def test_mistake_is_derived_not_stored(self):
        index = {
            "w_1": make_word("w_1", "a", wrong_count=2),                       # 错两次
            "w_2": make_word("w_2", "b", wrong_count=1, streak_correct=2),     # 错过但又答对两次
            "w_3": make_word("w_3", "c", wrong_count=1, streak_correct=0),     # 错过还没扳回来
            "w_4": make_word("w_4", "d"),
        }
        self.assertEqual([w.id for w in mistake_words(index)], ["w_1", "w_3"])


# --------------------------------------------------------------------------
# 分类
# --------------------------------------------------------------------------

class TestClassify(unittest.TestCase):

    def test_each_grade_maps_to_its_bucket(self):
        self.assertEqual(classify(Grade.CORRECT), BUCKET_KNOWN)
        self.assertEqual(classify(Grade.FUZZY), BUCKET_FUZZY)
        self.assertEqual(classify(Grade.WRONG), BUCKET_NEW)

    def test_unanswered_counts_as_new(self):
        self.assertEqual(classify(None), BUCKET_NEW)


# --------------------------------------------------------------------------
# 考试会话
# --------------------------------------------------------------------------

class TestExamSession(unittest.TestCase):

    def setUp(self):
        self.scheduler = EbbinghausScheduler()

    def make_session(self, words, script):
        return ExamSession(words, StubJudge(script), self.scheduler, TODAY)

    def test_answers_advance_and_finish(self):
        words = [make_word("w_1", "a"), make_word("w_2", "b")]
        session = self.make_session(words, Grade.CORRECT)

        self.assertEqual(session.current.id, "w_1")
        self.assertFalse(session.is_finished)

        session.submit("银行")
        self.assertEqual(session.current.id, "w_2")
        session.submit("银行")

        self.assertTrue(session.is_finished)
        self.assertIsNone(session.current)

    def test_submitting_after_the_end_returns_none(self):
        """界面可能在最后一题后多触发一次,那不该是个错误。"""
        session = self.make_session([make_word()], Grade.CORRECT)
        session.submit("银行")
        self.assertIsNone(session.submit("银行"))

    def test_state_is_updated_immediately(self):
        """答完立刻推进复习状态 —— 用户中途关窗口,答过的题不该白答。"""
        word = make_word()
        session = self.make_session([word], Grade.CORRECT)
        session.submit("银行")

        self.assertEqual(word.state.box, 1)
        self.assertEqual(word.state.interval_days, 1)
        self.assertEqual(word.state.correct_count, 1)

    def test_wrong_answer_schedules_tomorrow(self):
        word = make_word()
        session = self.make_session([word], Grade.WRONG)
        session.submit("完全无关")

        self.assertEqual(word.state.wrong_count, 1)
        self.assertEqual(word.state.next_review, "2026-10-13")

    def test_score_is_correct_over_answered(self):
        """正确率 = 完全答对的题数 ÷ 答题总数。

        模糊计入分母但不计入分子:它不是一次完整的成功。
        把模糊从分母里摘出去会让数字虚高,那是在骗自己。
        """
        words = [make_word("w_1", "a"), make_word("w_2", "b"), make_word("w_3", "c")]
        session = self.make_session(words, {"w_1": Grade.CORRECT,
                                            "w_2": Grade.FUZZY,
                                            "w_3": Grade.CORRECT})
        for _ in range(3):
            session.submit("x")
        self.assertAlmostEqual(session.score(), 2.0 / 3.0)

    def test_score_with_no_answers_is_zero_not_a_crash(self):
        session = self.make_session([make_word()], Grade.CORRECT)
        self.assertEqual(session.score(), 0.0)

    def test_buckets_reflect_worst_result_per_word(self):
        """一个词只要错过一次就算生词 —— 哪怕后来又答对了。

        同一个词在考试里出现两次是可能的(调用方传了重复的词),
        所以分桶必须看"最差的一次",而不是最后一次。
        """
        word = make_word()
        script = {"w_1": Grade.WRONG}
        session = ExamSession([word, word], StubJudge(script), self.scheduler, TODAY)

        session.submit("错")
        script["w_1"] = Grade.CORRECT
        session.submit("对")

        known, fuzzy, new = session.buckets()
        self.assertEqual((known, fuzzy, new), ([], [], ["w_1"]))

    def test_buckets_are_written_back_to_the_word(self):
        """bucket 是"最近一次考试分到哪一档",供界面展示。"""
        word = make_word()
        session = self.make_session([word], Grade.FUZZY)
        session.submit("沾边")
        session.buckets()
        self.assertEqual(word.state.bucket, BUCKET_FUZZY)

    def test_summary_collects_wrong_ids(self):
        words = [make_word("w_1", "a"), make_word("w_2", "b")]
        session = self.make_session(words, {"w_1": Grade.CORRECT, "w_2": Grade.WRONG})
        session.submit("x")
        session.submit("y")

        summary = session.summary()
        self.assertEqual(summary.known, ["w_1"])
        self.assertEqual(summary.newly, ["w_2"])
        self.assertEqual(summary.wrong_ids, ["w_2"])
        self.assertEqual(summary.taken_at, "2026-10-12")

    def test_build_pack_is_an_exam_pack_with_the_snapshot(self):
        index = {"w_1": make_word("w_1", "a")}
        session = self.make_session([index["w_1"]], Grade.CORRECT)
        session.submit("x")

        pack = session.build_pack(index, "pack_20261012_001")
        self.assertEqual(pack.pack_type, PACK_TYPE_EXAM)
        self.assertEqual(pack.word_ids, ["w_1"])
        self.assertEqual(pack.exam.known, ["w_1"])
        self.assertEqual(pack.created_at, "2026-10-12")
        self.assertEqual(pack.word_count, 1)

    def test_pack_mistakes_are_rebuilt_not_copied(self):
        """mistakes 只是缓存,必须按当前真实状态重算,不能留旧值。"""
        word = make_word("w_1", "a", wrong_count=3)
        index = {"w_1": word}
        session = self.make_session([word], Grade.CORRECT)
        session.submit("x")

        self.assertEqual(session.build_pack(index, "pack_1").mistakes, ["w_1"])

        word.state.wrong_count = 0
        word.state.streak_correct = 5
        self.assertEqual(session.build_pack(index, "pack_1").mistakes, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
