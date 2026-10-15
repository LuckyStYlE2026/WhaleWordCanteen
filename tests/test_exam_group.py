# -*- coding: utf-8 -*-
"""考试结果包:**一个单词表恰好三个固定包**,跨场次累加,不随日期增长。

对应 user 2026-10-14 要求的三件事:

    每个单词表拥有 3 个考试词包,每一次考过的词都进入"掌握,模糊,错题"
    名称:"sample考试·掌握" "sample考试·模糊" "sample考试·错题"
    记忆曲线:剔除单词表和考试结果包,否则每个包都要重复复习,会堆积

⚠️ 这一组测试锁了一个**静默**出错的坑:档位名的翻译
(`BUCKET_*` 是中文显示名,`PACK_KIND_*` 是英文 id 片段)。漏了翻译时
`severity()` 返回 -1,每个词都被当成最轻的一档 —— 三档全挤进「掌握」,
而且不报错。所以有一条测试**逐个档位名**断言 `severity() >= 0`。
"""

import unittest
from datetime import date

from core import exam_group, exam_seed
from core.models import Word
from core.packs import (
    PACK_KINDS,
    PACK_KIND_FUZZY,
    PACK_KIND_KNOWN,
    PACK_KIND_WRONG,
    PACK_TYPE_EXAM,
    PACK_TYPE_STUDY,
    WordPack,
    make_vocab_pack,
)
from core.quiz import ExamSession

TODAY = date(2026, 10, 14)


class FakeScheduler:
    """只把状态原样返回 —— 这一组测试关心的是分档,不是复习排期。"""

    def grade(self, state, grade, today):
        return state


class FakeJudge:
    """纯字面判分:答对 = 释义原样;模糊 = 释义的一部分;其余算错。"""

    def judge(self, word, answer):
        from core.interfaces import JudgeResult
        from core.models import Grade
        text = (answer or "").strip()
        if text == word.translation:
            return JudgeResult(Grade.CORRECT, 1.0, "offline", "")
        if text and text in word.translation:
            return JudgeResult(Grade.FUZZY, 0.6, "offline", "")
        return JudgeResult(Grade.WRONG, 0.0, "offline", "")


def make_words(count: int, prefix: str = "t"):
    return [Word(id="%s_%d" % (prefix, index), spelling_key="k%d" % index,
                 word="k%d" % index, translation="释义%d" % index)
            for index in range(count)]


def take_exam(words, correct=(), fuzzy=(), wrong=(), only=False):
    """按给定的分档造一场考试的会话。三个参数都是下标集合。

    `only=True` 表示"这一场只考被点名的那些词"(跳过其余)——
    "只考了一部分、别的档不该动"那条用例要的就是它。
    默认则把没点名的按答错处理,省得每处都写全 wrong。
    """
    session = ExamSession(words, FakeJudge(), FakeScheduler(), TODAY)
    for index, word in enumerate(words):
        if only and index not in correct and index not in fuzzy and index not in wrong:
            continue
        if index in correct:
            session.submit(word.translation)
        elif index in fuzzy:
            session.submit(word.translation[:1])
        else:
            session.submit("完全不相干")
    return session


class KindNameTest(unittest.TestCase):
    """档位名的翻译 —— 这一节锁的是那个"静默全归掌握"的坑。

    这一版把"最差的赢"换成了"以最后一场为准",所以不再有 severity()。
    但那个坑本身还在:`classify()` 返回的是中文分桶名,档位名是英文,
    **漏了翻译就会全部落回兜底的那一档**(掌握),而且不报错。
    所以这里直接把"一个答错的词"跑一遍,看它到底落在哪一档。
    """

    def test_bucket_names_are_translated_to_kinds(self):
        from core.models import BUCKET_FUZZY, BUCKET_KNOWN, BUCKET_NEW
        self.assertEqual(exam_group.BUCKET_TO_KIND[BUCKET_KNOWN], PACK_KIND_KNOWN)
        self.assertEqual(exam_group.BUCKET_TO_KIND[BUCKET_FUZZY], PACK_KIND_FUZZY)
        self.assertEqual(exam_group.BUCKET_TO_KIND[BUCKET_NEW], PACK_KIND_WRONG)

    def test_a_wrong_word_does_not_land_in_the_known_bucket(self):
        """这就是那个坑的**行为级**断言:翻译漏了的话,
        下面这行会拿到 PACK_KIND_KNOWN,而测试会当场红。"""
        words = make_words(1)
        session = take_exam(words, wrong={0}, only=True)
        self.assertEqual(exam_group.kind_of(words[0], session), PACK_KIND_WRONG)

    def test_a_correct_word_lands_in_the_known_bucket(self):
        words = make_words(1)
        session = take_exam(words, correct={0}, only=True)
        self.assertEqual(exam_group.kind_of(words[0], session), PACK_KIND_KNOWN)


class SetupMixin:
    def setUp(self):
        self.words = make_words(6)
        self.index = {word.id: word for word in self.words}
        self.vocab = make_vocab_pack("sample", "sample",
                                     [w.id for w in self.words], "2026-10-14")
        self.packs = [self.vocab]


class NamingTest(SetupMixin, unittest.TestCase):
    """三个包的名称与数量。名称是用户直接点的要求。"""

    def test_titles_match_the_requested_shape(self):
        exam_group.merge_exam(self.packs, "sample", "sample",
                              take_exam(self.words, correct={0}), self.index)
        titles = sorted(pack.title for pack in self.packs
                        if exam_group.is_exam_pack(pack))
        self.assertEqual(titles, ["sample考试·掌握", "sample考试·模糊",
                                  "sample考试·错题"])

    def test_exactly_three_packs_no_matter_how_many_exams(self):
        """这一条是用户报的核心问题:考几次都不该多出包来。"""
        for good in ({0}, {1, 2}, set(), {0, 1, 2, 3, 4, 5}):
            exam_group.merge_exam(self.packs, "sample", "sample",
                                  take_exam(self.words, correct=good), self.index)
        exam_packs = [pack for pack in self.packs if exam_group.is_exam_pack(pack)]
        self.assertEqual(len(exam_packs), 3)
        self.assertEqual(len({pack.id for pack in exam_packs}), 3)

    def test_pack_ids_are_derived_from_the_vocab_id(self):
        exam_group.merge_exam(self.packs, "sample", "sample",
                              take_exam(self.words, correct={0}), self.index)
        ids = {pack.kind: pack.id for pack in self.packs
               if exam_group.is_exam_pack(pack)}
        self.assertEqual(ids[PACK_KIND_KNOWN], "sample_exam_known")
        self.assertEqual(ids[PACK_KIND_WRONG], "sample_exam_wrong")


class PlacementTest(SetupMixin, unittest.TestCase):
    """每个词进哪一档。"""

    def merge(self, **kwargs):
        return exam_group.merge_exam(self.packs, "sample", "sample",
                                     take_exam(self.words, **kwargs), self.index)

    def by_kind(self, parts):
        return {pack.kind: pack.word_ids for pack in parts}

    def test_words_land_in_the_right_kind(self):
        landed = self.by_kind(self.merge(correct={0, 1}, fuzzy={2},
                                         wrong={3, 4, 5}))
        self.assertEqual(landed[PACK_KIND_KNOWN], ["t_0", "t_1"])
        self.assertEqual(landed[PACK_KIND_FUZZY], ["t_2"])
        self.assertEqual(landed[PACK_KIND_WRONG], ["t_3", "t_4", "t_5"])

    def test_three_kinds_never_overlap_and_cover_everything(self):
        parts = self.merge(correct={0, 1}, fuzzy={2}, wrong={3, 4, 5})
        collected = [word_id for pack in parts for word_id in pack.word_ids]
        self.assertEqual(len(collected), len(set(collected)), "有词出现在多个档里")
        self.assertEqual(sorted(collected), sorted(self.index))

    def test_results_accumulate_across_exams(self):
        """用户举的例子:第一次有些词错,第二次那些词答对 → 数字会变。"""
        self.merge(correct={0, 1}, wrong={2, 3, 4, 5})
        landed = self.by_kind(self.merge(correct={0, 1, 2, 3, 4, 5}))
        self.assertEqual(len(landed[PACK_KIND_KNOWN]), 6)
        self.assertEqual(landed[PACK_KIND_WRONG], [])

    def test_a_word_can_be_demoted_too(self):
        """答错要从「掌握」挪到「错题」 —— 包说的是"现在什么状态"。"""
        self.merge(correct={0, 1, 2, 3, 4, 5})
        landed = self.by_kind(self.merge(wrong={0, 1, 2, 3, 4, 5}))
        self.assertEqual(landed[PACK_KIND_KNOWN], [])
        self.assertEqual(len(landed[PACK_KIND_WRONG]), 6)

    def test_latest_exam_decides_not_the_old_severe_one(self):
        """这一版**不再**用"当天最差归位"。包的语义是"这份词表现在什么
        状态",所以答对之后必须能离开错题档 —— 否则错题包会一直留着一个
        用户其实已经会了的词,它就不再代表"我现在不会的词"。"""
        first = exam_group.merge_exam(self.packs, "sample", "sample",
                                      take_exam(self.words, wrong={0}, only=True),
                                      self.index)
        self.assertEqual(self.by_kind(first)[PACK_KIND_WRONG], ["t_0"])
        landed = self.by_kind(
            exam_group.merge_exam(self.packs, "sample", "sample",
                                  take_exam(self.words, correct={0}, only=True),
                                  self.index))
        self.assertEqual(landed[PACK_KIND_KNOWN], ["t_0"])
        self.assertEqual(landed[PACK_KIND_WRONG], [])

    def test_words_not_in_this_exam_keep_their_kind(self):
        """这一场只考了一部分词,别的档不该被动。

        "没考到的词留在原来那一档"是这一节最要紧的一条:只按"这一场考过的词"
        重排的话,考 2 个词会把另外 4 个从各自的档里抹掉。

        也顺带锁住"提前结束"那种情况 —— 后面的题没答、没有分数,
        不该被倒进「错题」里。
        """
        self.merge(correct={0, 1}, wrong={2, 3, 4, 5})
        session = take_exam(self.words, correct={1}, only=True)
        landed = self.by_kind(exam_group.merge_exam(
            self.packs, "sample", "sample", session, self.index))
        # t_0 这一场没考到 → 留在原来的档(它上一场是错的)
        self.assertIn("t_0", landed[PACK_KIND_WRONG])
        # t_1 这一场又考对了 → 仍在掌握里
        self.assertIn("t_1", landed[PACK_KIND_KNOWN])
        # 其余没考到的都留在错题里,一个都没被抹掉
        self.assertEqual(sorted(landed[PACK_KIND_WRONG]),
                         ["t_0", "t_2", "t_3", "t_4", "t_5"])

    def test_words_missing_from_the_index_are_skipped(self):
        orphan = Word(id="gone", spelling_key="gone", word="gone", translation="没")
        parts = exam_group.merge_exam(self.packs, "sample", "sample",
                                      take_exam([orphan], correct={0}), self.index)
        every = [wid for pack in parts for wid in pack.word_ids]
        self.assertNotIn("gone", every)

    def test_other_vocab_packs_are_untouched(self):
        self.packs.append(make_vocab_pack("other", "别的词表", ["t_0"], "2026-10-14"))
        self.merge(correct={0})
        self.assertEqual(exam_group.exam_packs_of(self.packs, "other"), [])


class LookupTest(SetupMixin, unittest.TestCase):
    """归属判断:学习词包 / 考试包各自指向哪份单词表。"""

    def test_a_vocab_pack_belongs_to_itself(self):
        self.assertEqual(exam_group.vocab_of(self.vocab, self.packs), "sample")

    def test_a_study_pack_belongs_to_its_source_vocab(self):
        """用户考试多半勾"今天的学习词包",结果要落到那份单词表名下。"""
        study = WordPack(id="pack_20261014_001", pack_type=PACK_TYPE_STUDY,
                         title="2026-10-14 学习词包", created_at="2026-10-14",
                         word_ids=["t_0"], source_vocab="sample")
        self.assertEqual(exam_group.vocab_of(study, self.packs), "sample")

    def test_an_exam_pack_belongs_to_its_parent_vocab(self):
        parts = exam_group.merge_exam(self.packs, "sample", "sample",
                                      take_exam(self.words, correct={0}),
                                      self.index)
        for pack in parts:
            self.assertEqual(exam_group.vocab_of(pack, self.packs), "sample")

    def test_an_old_study_pack_without_source_vocab_is_recognised(self):
        """老存档的学习词包只记了 source_pack,那一份恰好是单词表时也认。"""
        study = WordPack(id="old_study", pack_type=PACK_TYPE_STUDY, title="旧",
                         created_at="2026-10-14", word_ids=["t_0"],
                         source_pack="sample")
        self.assertEqual(exam_group.vocab_of(study, self.packs), "sample")

    def test_an_unknown_pack_has_no_vocab(self):
        loose = WordPack(id="x", pack_type=PACK_TYPE_STUDY, title="无来源",
                         created_at="2026-10-14", word_ids=["t_0"])
        self.assertEqual(exam_group.vocab_of(loose, self.packs), "")


class ReviewExclusionTest(SetupMixin, unittest.TestCase):
    """记忆曲线剔除考试结果包 —— 用户 2026-10-14 明确要求。"""

    def test_exam_packs_are_not_reviewable(self):
        parts = exam_group.merge_exam(self.packs, "sample", "sample",
                                      take_exam(self.words, correct={0}),
                                      self.index)
        for pack in parts:
            self.assertFalse(exam_group.is_reviewable(pack), pack.title)

    def test_vocab_and_study_packs_stay_reviewable(self):
        study = WordPack(id="s", pack_type=PACK_TYPE_STUDY, title="学习",
                         created_at="2026-10-14", word_ids=["t_0"])
        self.assertTrue(exam_group.is_reviewable(self.vocab))
        self.assertTrue(exam_group.is_reviewable(study))

    def test_old_dated_exam_packs_are_left_alone(self):
        """上一版留下的带日期考试包没有 group_id,不算这一套 ——
        它们不会被合并进新的三个包,也不会被自动删掉。"""
        old = WordPack(id="pack_20261013_002", pack_type=PACK_TYPE_EXAM,
                       title="词包考试", created_at="2026-10-13")
        self.assertFalse(exam_group.is_exam_pack(old))
        self.assertFalse(exam_group.is_reviewable(old))


class CascadeDeleteTest(SetupMixin, unittest.TestCase):
    """删单词表时,它名下三个考试包跟着走。"""

    def test_dropping_a_vocab_takes_its_exam_packs(self):
        exam_group.merge_exam(self.packs, "sample", "sample",
                              take_exam(self.words, correct={0}), self.index)
        doomed = exam_group.drop_for_vocab(self.packs, "sample")
        self.assertEqual(len(doomed), 3)
        self.assertEqual(exam_group.exam_packs_of(self.packs, "sample"), [])
        self.assertNotIn(doomed[0], self.packs)

    def test_dropping_does_not_touch_other_vocab(self):
        self.packs.append(make_vocab_pack("other", "别的词表", ["t_0"], "2026-10-14"))
        exam_group.merge_exam(self.packs, "other", "别的词表",
                              take_exam(self.words, correct={0}), self.index)
        exam_group.drop_for_vocab(self.packs, "sample")
        self.assertEqual(len(exam_group.exam_packs_of(self.packs, "other")), 3)

    def test_rename_follows_the_vocab_title(self):
        exam_group.merge_exam(self.packs, "sample", "sample",
                              take_exam(self.words, correct={0}), self.index)
        exam_group.retitle(self.packs, "sample", "新名字")
        titles = sorted(p.title for p in self.packs if exam_group.is_exam_pack(p))
        self.assertEqual(titles, ["新名字考试·掌握", "新名字考试·模糊",
                                  "新名字考试·错题"])


class SeedTest(unittest.TestCase):
    """「随机加入全考试词包」的 3 : 4 : 5 抽样。"""

    def setUp(self):
        self.words = make_words(60, prefix="b")
        self.index = {w.id: w for w in self.words}
        self.packs = [make_vocab_pack("v", "v", list(self.index), "2026-10-14")]
        # 三档各 20 个词
        exam_group.merge_exam(
            self.packs, "v", "v",
            take_exam(self.words, correct=set(range(20)),
                      fuzzy=set(range(20, 40)), wrong=set(range(40, 60))),
            self.index)

    def test_weights_are_three_four_five(self):
        self.assertEqual([weight for _kind, weight in exam_seed.SEED_WEIGHTS],
                         [3, 4, 5])

    def test_plan_scales_with_the_requested_count(self):
        """三档各 20 个词,按 3:4:5 抽 12 个 → 3 / 4 / 5。"""
        plan = exam_seed.seed_plan(self.packs, "v", 12)
        self.assertEqual(plan[PACK_KIND_KNOWN], 3)
        self.assertEqual(plan[PACK_KIND_FUZZY], 4)
        self.assertEqual(plan[PACK_KIND_WRONG], 5)

    def test_a_scarce_kind_does_not_borrow_from_others(self):
        """某一档不够时只抽它有的那些 —— 不从别的档借,借来的词属于另一档,
        抽进来会让用户看不懂("我明明全对了,怎么又在考它")。"""
        small = make_words(6)
        index = {w.id: w for w in small}
        packs = [make_vocab_pack("s", "s", list(index), "2026-10-14")]
        exam_group.merge_exam(packs, "s", "s",
                              take_exam(small, correct={0, 1, 2, 3, 4},
                                        wrong={5}), index)
        plan = exam_seed.seed_plan(packs, "s", 12)
        self.assertEqual(plan[PACK_KIND_WRONG], 1)
        self.assertLessEqual(plan[PACK_KIND_KNOWN], 5)

    def test_seed_words_come_from_the_exam_packs(self):
        picked = exam_seed.seed_words(self.packs, "v", self.index, 12)
        self.assertEqual(len(picked), 12)
        for word in picked:
            self.assertIn(word.id, self.index)

    def test_no_exam_packs_means_nothing_to_add(self):
        empty = [make_vocab_pack("e", "e", ["b_0"], "2026-10-14")]
        self.assertEqual(exam_seed.seed_plan(empty, "e", 12),
                         {kind: 0 for kind in PACK_KINDS})
        self.assertEqual(exam_seed.seed_words(empty, "e", self.index, 12), [])


class SummaryTest(SetupMixin, unittest.TestCase):
    """给界面用的一行小字。"""

    def test_summary_counts_each_kind(self):
        exam_group.merge_exam(self.packs, "sample", "sample",
                              take_exam(self.words, correct={0, 1, 2},
                                        fuzzy={3}, wrong={4, 5}), self.index)
        text = exam_group.summary_text(self.packs, "sample")
        self.assertIn("掌握 3", text)
        self.assertIn("模糊 1", text)
        self.assertIn("错题 2", text)

    def test_summary_before_any_exam_is_empty(self):
        self.assertEqual(exam_group.summary_text(self.packs, "sample"), "")


if __name__ == "__main__":
    unittest.main()
