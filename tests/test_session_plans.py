# -*- coding: utf-8 -*-
"""会话计划层的测试:挑词、合并、抽样。

这一层最要紧的两条:

1. **抽样只能发生一次。** 以前"随机考试"先抽一遍、发车前又抽一遍,第二次
   因为池子已经缩到题量、走的只是打乱顺序的分支,第一次算出来的加权
   等于白算了 —— 而这一点在界面上完全看不出来。所以这里专门锁住
   "构造计划时不缩水、只有 resample_for_exam 会缩水"。
2. **抽样不按"毕业/到期"过滤(2026-10-12 用户反馈)。** 考试是用户主动
   发起的检验,选了什么词包就考什么;以前全毕业的池子会被抽成空计划,
   界面只好提示"没词可考"。现在全毕业也照样出题 —— 该复习什么由
   「开始复习」那条按记忆曲线走的路负责,考试不替用户做主。

不需要图形界面 —— ui/session.py 刻意不 import tkinter。
"""

import random
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.interfaces import RawWord                     # noqa: E402
from core.wordpack_import import apply_import           # noqa: E402
from ui.session import (                                # noqa: E402
    MODE_EXAM,
    MODE_STUDY,
    merge_words,
    plan_from_pack_range,
    plan_from_packs,
    plan_from_parts,
    plan_random_exam,
    resample_for_exam,
    target_view,
)

TODAY = date(2026, 10, 12)


def build_index(count=5):
    """造一个含 count 个词的词库,返回 (index, ids)。"""
    index = {}
    raws = [RawWord(word="word%d" % i, translation="释义%d" % i)
            for i in range(count)]
    _, ids = apply_import(index, raws, pack_id="pack_a", today=TODAY,
                          return_ids=True)
    return index, ids


def graduate_everything(index):
    """把所有词改成毕业状态:连续答对够多、复习日还在未来。"""
    future = (TODAY + timedelta(days=30)).isoformat()
    for word in index.values():
        word.state.streak_correct = 99
        word.state.next_review = future


class TestMergeWords(unittest.TestCase):
    def test_dedupes_by_id_keeping_first_occurrence(self):
        index, ids = build_index(3)
        first = index[ids[0]]
        second = index[ids[1]]
        merged = merge_words([first, second], [second, first], [index[ids[2]]])
        self.assertEqual([w.id for w in merged], ids, "去重后应保持首次出现的顺序")

    def test_empty_groups_are_fine(self):
        self.assertEqual(merge_words([], []), [])


class TestPlanFromParts(unittest.TestCase):
    def test_single_part_uses_its_own_name(self):
        index, ids = build_index(2)
        plan = plan_from_parts([("今日复习", [index[i] for i in ids])], MODE_STUDY)
        self.assertEqual(plan.title, "今日复习")

    def test_many_parts_use_counted_title(self):
        index, ids = build_index(3)
        plan = plan_from_parts([("今日复习", [index[ids[0]]]),
                                ("学习新词", [index[ids[1]]]),
                                ("甲包", [index[ids[2]]])], MODE_STUDY)
        self.assertEqual(plan.title, "今日复习 等 3 项")

    def test_empty_parts_are_skipped_and_shared_words_deduped(self):
        index, ids = build_index(2)
        word = index[ids[0]]
        plan = plan_from_parts([("空", []), ("甲", [word]),
                                ("乙", [word, index[ids[1]]])], MODE_STUDY)
        self.assertEqual(plan.title, "甲 等 2 项")
        self.assertEqual(len(plan.words), 2, "同一个词出现在两处只算一次")

    def test_cross_source_plan_has_no_pack_id(self):
        index, ids = build_index(2)
        plan = plan_from_parts([("今日复习", [index[i] for i in ids])], MODE_STUDY)
        self.assertEqual(plan.pack_id, "", "跨来源的会话不该假装自己有来源词包")


class TestPlanRandomExamIsAPool(unittest.TestCase):
    def test_returns_the_whole_library_unsampled(self):
        """回归锁:构造计划时**不能**抽样。

        「随机考试」曾经在这里就抽一次,发车前又抽一次。这条测试改之前必失败
        —— 它锁的就是那个双重抽样。
        """
        index, _ids = build_index(30)
        plan = plan_random_exam(index)
        self.assertEqual(plan.mode, MODE_EXAM)
        self.assertEqual(plan.title, "随机考试")
        self.assertEqual(len(plan.words), 30, "候选池应该是全库,不该提前缩水")


class TestResampleForExam(unittest.TestCase):
    def test_study_plan_passes_through_untouched(self):
        """学习是"把这一包按顺序背一遍",缩水就少背了词。"""
        index, ids = build_index(30)
        source = [index[i] for i in ids]
        plan = resample_for_exam(plan_from_parts([("甲", source)], MODE_STUDY), 5)
        self.assertEqual(len(plan.words), 30)

    def test_exam_plan_is_cut_down_to_size(self):
        index, _ids = build_index(30)
        plan = resample_for_exam(plan_random_exam(index), 7)
        self.assertEqual(len(plan.words), 7)
        self.assertTrue(set(w.id for w in plan.words) <= set(index.keys()))

    def test_small_pool_gives_everything_without_error(self):
        index, _ids = build_index(3)
        plan = resample_for_exam(plan_random_exam(index), 20)
        self.assertEqual(len(plan.words), 3, "词不够不该考不了试")

    def test_injected_rng_makes_it_reproducible(self):
        index, _ids = build_index(30)
        first = resample_for_exam(plan_random_exam(index), 8,
                                  rng=random.Random(0))
        second = resample_for_exam(plan_random_exam(index), 8,
                                   rng=random.Random(0))
        self.assertEqual([w.id for w in first.words],
                         [w.id for w in second.words])

    def test_all_graduated_pool_still_yields_questions(self):
        """回归锁(2026-10-12 用户反馈):全毕业的池子也照样出题。

        以前抽样把"已毕业且没到期"的词整个滤掉,用户挑了自己的词包
        想考试,却被告知"没有可以用来考试的词"。现在考试考用户选的。
        """
        index, _ids = build_index(5)
        graduate_everything(index)
        plan = resample_for_exam(plan_random_exam(index), 20)
        self.assertEqual(len(plan.words), 5)


class TestTargetView(unittest.TestCase):
    def test_routes_by_mode(self):
        index, ids = build_index(2)
        words = [index[i] for i in ids]
        self.assertEqual(target_view(plan_from_parts([("甲", words)], MODE_STUDY)),
                         "study")
        self.assertEqual(target_view(plan_from_parts([("甲", words)], MODE_EXAM)),
                         "exam")


class TestPlanFromPacksKeepsPackId(unittest.TestCase):
    def test_single_pack_records_its_id_for_the_result_pack(self):
        """学习结束时要用 pack_id 记结果包的来源(见 study.py 写 source_pack)。"""
        index, ids = build_index(2)
        pack = _make_pack("pack_a", ids)
        plan = plan_from_packs([pack], index, MODE_STUDY)
        self.assertEqual(plan.pack_id, "pack_a")
        self.assertIs(plan.pack, pack)

    def test_multiple_packs_have_no_single_source(self):
        index, ids = build_index(2)
        plan = plan_from_packs([_make_pack("pack_a", ids),
                                _make_pack("pack_b", ids)], index, MODE_STUDY)
        self.assertEqual(plan.pack_id, "")
        self.assertEqual(plan.title, "甲 等 2 个词包")


class TestPlanFromPackRange(unittest.TestCase):
    """「从一个词表包的第几个开始学多少个」—— 1.3 的起点选择走这条路。"""

    def test_slices_words_and_records_where_it_started(self):
        index, ids = build_index(10)
        pack = _make_pack("pack_a", ids)
        plan = plan_from_pack_range(pack, index, MODE_STUDY, 3, 2)
        self.assertEqual(plan.start_index, 3, "学习页要靠它把进度写回去")
        self.assertEqual(plan.pack_id, "pack_a")
        self.assertIs(plan.pack, pack)
        self.assertEqual([w.id for w in plan.words], ids[3:5])

    def test_zero_count_means_to_the_end_of_the_pack(self):
        index, ids = build_index(6)
        plan = plan_from_pack_range(_make_pack("pack_a", ids), index,
                                    MODE_STUDY, 4, 0)
        self.assertEqual([w.id for w in plan.words], ids[4:])

    def test_out_of_range_start_does_not_raise(self):
        """起点越界是用户能填出来的(手填 9999)—— 该得到空计划,
        由一个正常的提示接住,而不是一个异常。"""
        index, ids = build_index(3)
        plan = plan_from_pack_range(_make_pack("pack_a", ids), index,
                                    MODE_STUDY, 9999, 5)
        self.assertEqual(plan.words, [])
        self.assertEqual(plan.start_index, 3, "夹回词数,不是夹到最后一个词")

    def test_ids_missing_from_the_index_are_skipped(self):
        """词被删了、词包数据里还留着引用 —— 跳过就够,不必清理。"""
        index, ids = build_index(3)
        pack = _make_pack("pack_a", ids + ["w_不存在"])
        plan = plan_from_pack_range(pack, index, MODE_STUDY, 0, 0)
        self.assertEqual(len(plan.words), 3)


class TestDeadNewWordEntryPointsAreGone(unittest.TestCase):
    """「学习新词」整条线已经删掉(玩家学词表即学新词)。

    这条是回归锁:哪天有人把 new_words / is_new_word 加回来再接一个
    「学习新词」入口,这里会直接失败,而不是等到用户发现学习页里
    莫名其妙多出一栏不知道从哪来的词。
    """

    def test_session_module_no_longer_offers_new_words(self):
        import ui.session as session
        self.assertFalse(hasattr(session, "new_words"))
        self.assertFalse(hasattr(session, "is_new_word"))


def _make_pack(pack_id, word_ids):
    from core.packs import make_vocab_pack
    return make_vocab_pack(pack_id, "甲", word_ids, TODAY.isoformat())


if __name__ == "__main__":
    unittest.main(verbosity=2)
