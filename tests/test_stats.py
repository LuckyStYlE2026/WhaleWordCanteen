# -*- coding: utf-8 -*-
"""统计与记忆曲线测试。

重点不是算得"准不准",而是三件事:
  · 空词库不能除零、不能崩
  · 曲线必须是单调下降的(不然画出来就不是遗忘曲线了)
  · 汇总数必须跟着真实状态走,不读任何缓存
"""

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import Mastery, Word, WordState          # noqa: E402
from core.packs import PackSchedule, WordPack             # noqa: E402
from core.scheduler import EBBINGHAUS_LADDER              # noqa: E402
from core.stats import (                                  # noqa: E402
    CURVE_DAYS,
    MIN_RETENTION,
    average_strength,
    build_diagnosis_payload,
    diagnosis_text,
    due_forecast,
    forgetting_curve,
    ladder_marks,
    pack_status_label,
    progress_line,
    summarize,
    summary_for_pack,
    word_retention,
)

TODAY = date(2026, 10, 12)


def make_word(word_id="w_1", word="bank", **state_kwargs):
    return Word(id=word_id, spelling_key=word, word=word, translation="银行",
                state=WordState(**state_kwargs))


class TestSummary(unittest.TestCase):

    def test_empty_index_gives_zeroes_not_zero_division(self):
        summary = summarize({}, TODAY)
        self.assertEqual(summary.total, 0)
        self.assertEqual(summary.mastery_rate, 0.0)

    def test_each_mastery_lands_in_its_own_bucket(self):
        index = {
            "w_1": make_word("w_1", "a", mastery=Mastery.KNOWN),
            "w_2": make_word("w_2", "b", mastery=Mastery.FUZZY),
            "w_3": make_word("w_3", "c", mastery=Mastery.NEW),
            "w_4": make_word("w_4", "d", mastery=Mastery.RELEARN),
        }
        summary = summarize(index, TODAY)
        self.assertEqual((summary.known, summary.fuzzy, summary.new, summary.relearn),
                         (1, 1, 1, 1))
        self.assertEqual(summary.total, 4)

    def test_mastery_rate(self):
        index = {
            "w_1": make_word("w_1", "a", mastery=Mastery.KNOWN),
            "w_2": make_word("w_2", "b", mastery=Mastery.KNOWN),
            "w_3": make_word("w_3", "c", mastery=Mastery.NEW),
            "w_4": make_word("w_4", "d", mastery=Mastery.NEW),
        }
        self.assertAlmostEqual(summarize(index, TODAY).mastery_rate, 0.5)

    def test_due_today_includes_overdue_but_not_future(self):
        index = {
            "w_1": make_word("w_1", "a", next_review="2026-10-12", review_count=1),
            "w_2": make_word("w_2", "b", next_review="2026-10-01", review_count=1),
            "w_3": make_word("w_3", "c", next_review="2026-10-20", review_count=1),
            "w_4": make_word("w_4", "d", next_review=None, review_count=1),
        }
        self.assertEqual(summarize(index, TODAY).due_today, 2)

    def test_never_studied_words_are_not_due(self):
        """口径必须和 scheduler.due_words 一致。

        新建的词出生就带"今天到期"(见 scheduler.initial_state),
        算进 due_today 的话,刚导入 100 个词的那天主菜单会写
        "今天有 100 个单词等着复习",而它们一个都没进过考场。
        """
        index = {"w_1": make_word("w_1", "a", next_review="2026-10-12",
                                  review_count=0, mastery=Mastery.NEW)}
        summary = summarize(index, TODAY)
        self.assertEqual(summary.due_today, 0)
        self.assertEqual(summary.new, 1, "它仍然该算作'还没学过'")

    def test_mistakes_are_counted_from_the_derived_rule(self):
        index = {
            "w_1": make_word("w_1", "a", wrong_count=2),
            "w_2": make_word("w_2", "b", wrong_count=1, streak_correct=3),
            "w_3": make_word("w_3", "c", wrong_count=1),
        }
        self.assertEqual(summarize(index, TODAY).mistakes, 2)


class TestForgettingCurve(unittest.TestCase):

    def test_starts_at_one_hundred_percent(self):
        self.assertAlmostEqual(forgetting_curve(7.0)[0][1], 1.0)

    def test_is_monotonically_decreasing(self):
        """不是单调下降的话,画出来就不叫遗忘曲线了。"""
        values = [value for _, value in forgetting_curve(5.0)]
        for earlier, later in zip(values, values[1:]):
            self.assertLessEqual(later, earlier)

    def test_longer_axis_when_strength_is_higher(self):
        weak = forgetting_curve(2.0)[7][1]
        strong = forgetting_curve(20.0)[7][1]
        self.assertLess(weak, strong, "记忆强度越大,七天后的保持率应该越高")

    def test_never_drops_below_the_floor(self):
        values = [value for _, value in forgetting_curve(1.0, days=200)]
        self.assertGreaterEqual(min(values), MIN_RETENTION)

    def test_covers_the_requested_number_of_days(self):
        self.assertEqual(len(forgetting_curve(3.0)), CURVE_DAYS + 1)

    def test_absurd_strength_does_not_crash(self):
        """存档被手工改坏成 0 或负数时,曲线也得画得出来。"""
        for strength in (0.0, -5.0):
            self.assertEqual(len(forgetting_curve(strength)), CURVE_DAYS + 1)


class TestStrength(unittest.TestCase):

    def test_unlearned_words_are_ignored(self):
        """没学过的词间隔是 0,算进去会把曲线压成一条贴着 0 的直线。"""
        index = {
            "w_1": make_word("w_1", "a", mastery=Mastery.NEW, interval_days=0),
            "w_2": make_word("w_2", "b", mastery=Mastery.KNOWN, interval_days=10),
        }
        self.assertAlmostEqual(average_strength(index), 10.0)

    def test_falls_back_when_nothing_is_learned(self):
        self.assertEqual(average_strength({}), 1.0)
        self.assertEqual(
            average_strength({"w_1": make_word()}), 1.0)


class TestWordRetention(unittest.TestCase):

    def test_never_reviewed_word_has_no_retention(self):
        self.assertEqual(word_retention(make_word(), TODAY), 0.0)

    def test_retention_drops_as_time_passes(self):
        fresh = make_word(last_review="2026-10-12", interval_days=7)
        stale = make_word(last_review="2026-10-01", interval_days=7)
        self.assertGreater(word_retention(fresh, TODAY), word_retention(stale, TODAY))


class TestDueForecast(unittest.TestCase):

    def test_counts_land_on_the_right_day(self):
        index = {
            "w_1": make_word("w_1", "a", next_review="2026-10-12", review_count=1),
            "w_2": make_word("w_2", "b", next_review="2026-10-14", review_count=1),
            "w_3": make_word("w_3", "c", next_review="2026-10-14", review_count=1),
        }
        forecast = dict(due_forecast(index, TODAY))
        self.assertEqual(forecast[0], 1)
        self.assertEqual(forecast[2], 2)

    def test_overdue_and_far_future_are_left_out(self):
        index = {
            "w_1": make_word("w_1", "a", next_review="2026-10-01", review_count=1),
            "w_2": make_word("w_2", "b", next_review="2026-12-01", review_count=1),
            "w_3": make_word("w_3", "c", next_review=None, review_count=1),
        }
        self.assertEqual(sum(count for _, count in due_forecast(index, TODAY)), 0)

    def test_never_studied_words_are_left_off_the_chart(self):
        """新导入的词没有"复习日",不该在第 0 天堆成一根柱子把图压垮。"""
        index = {"w_1": make_word("w_1", "a", next_review="2026-10-12",
                                  review_count=0)}
        self.assertEqual(sum(count for _, count in due_forecast(index, TODAY)), 0)

    def test_ladder_marks_stay_inside_the_axis(self):
        marks = ladder_marks()
        self.assertTrue(marks)
        for day in marks:
            self.assertIn(day, EBBINGHAUS_LADDER)
            self.assertLessEqual(day, CURVE_DAYS)


class TestTexts(unittest.TestCase):

    def test_empty_library_gets_an_invitation_not_a_zero(self):
        text = progress_line(summarize({}, TODAY))
        self.assertIn("导入", text)

    def test_progress_line_mentions_the_numbers(self):
        index = {"w_1": make_word("w_1", "a", mastery=Mastery.KNOWN,
                                  next_review="2026-10-12")}
        text = progress_line(summarize(index, TODAY))
        self.assertIn("1", text)

    def test_diagnosis_prefers_the_most_actionable_advice(self):
        """有到期的词就先说复习,这是最该做的一件事。"""
        index = {
            "w_1": make_word("w_1", "a", mastery=Mastery.KNOWN,
                             next_review="2026-10-01", review_count=1),
            "w_2": make_word("w_2", "b", wrong_count=3, review_count=1),
        }
        self.assertIn("复习", diagnosis_text(summarize(index, TODAY)))

    def test_diagnosis_handles_every_branch_without_crashing(self):
        for index in ({}, {"w_1": make_word()},
                      {"w_1": make_word(wrong_count=3)},
                      {"w_1": make_word(mastery=Mastery.KNOWN)}):
            self.assertTrue(diagnosis_text(summarize(index, TODAY)))

    def test_payload_carries_counts_only(self):
        """发给模型的诊断输入只带汇总数字 —— 传单词细节会让输出 token 暴涨。"""
        index = {"w_1": make_word("w_1", "a", mastery=Mastery.KNOWN)}
        payload = build_diagnosis_payload(summarize(index, TODAY), pack_title="第一包")
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["pack"], "第一包")
        self.assertNotIn("words", payload)
        self.assertNotIn("w_1", str(payload))


def make_pack(pack_id="pack_1", word_ids=None, **schedule_kwargs):
    return WordPack(id=pack_id, pack_type="vocab", title="第一包",
                    created_at="2026-10-10", word_ids=list(word_ids or []),
                    schedule=PackSchedule(**schedule_kwargs))


class TestSummaryForPack(unittest.TestCase):
    """记忆曲线底部的「词包一览」用它。规矩只有一条:口径必须和全库一致。"""

    def test_only_counts_the_words_inside_the_pack(self):
        index = {
            "w_1": make_word("w_1", "a", mastery=Mastery.KNOWN),
            "w_2": make_word("w_2", "b", mastery=Mastery.KNOWN),
            "w_3": make_word("w_3", "c", mastery=Mastery.NEW),
        }
        pack = make_pack(word_ids=["w_1", "w_3"])
        summary = summary_for_pack(pack, index, TODAY)
        self.assertEqual(summary.total, 2, "包外那个已掌握的词不能被算进来")
        self.assertEqual(summary.known, 1)
        self.assertEqual(summary.new, 1)
        self.assertAlmostEqual(summary.mastery_rate, 0.5)

    def test_ids_pointing_at_deleted_words_are_skipped(self):
        """词包只存 id,词可能已经被别处删了 —— 差集要吃掉,不能 KeyError。"""
        index = {"w_1": make_word("w_1", "a", mastery=Mastery.KNOWN)}
        pack = make_pack(word_ids=["w_1", "w_已经没了"])
        summary = summary_for_pack(pack, index, TODAY)
        self.assertEqual(summary.total, 1)

    def test_empty_pack_does_not_divide_by_zero(self):
        summary = summary_for_pack(make_pack(), {}, TODAY)
        self.assertEqual(summary.total, 0)
        self.assertEqual(summary.mastery_rate, 0.0)

    def test_same_caliber_as_the_whole_library(self):
        """同一个词集,无论走包口径还是全库口径,数字必须一样。"""
        index = {
            "w_1": make_word("w_1", "a", mastery=Mastery.RELEARN,
                             next_review="2026-10-01", wrong_count=2),
            "w_2": make_word("w_2", "b", mastery=Mastery.FUZZY,
                             next_review="2026-10-20"),
        }
        by_pack = summary_for_pack(make_pack(word_ids=list(index)),
                                   index, TODAY)
        self.assertEqual(by_pack.to_dict(), summarize(index, TODAY).to_dict())


class TestPackStatusLabel(unittest.TestCase):

    def test_empty_pack_says_so(self):
        self.assertEqual(pack_status_label(make_pack(), TODAY), "空包")

    def test_needs_relearn_wins_over_a_future_date(self):
        """已经判定要重学的包,不能因为"下次到期日还在未来"就显示成没事。"""
        pack = make_pack(word_ids=["w_1"], recommended_next="2026-12-01",
                         needs_relearn=True)
        self.assertEqual(pack_status_label(pack, TODAY), "需要重学")

    def test_never_studied(self):
        pack = make_pack(word_ids=["w_1"])
        self.assertEqual(pack_status_label(pack, TODAY), "还没学过")

    def test_due_today_and_future_and_overdue(self):
        cases = [("2026-10-12", "今天到期"),
                 ("2026-10-15", "3 天后到期"),
                 ("2026-10-02", "逾期 10 天")]
        for recommended, expected in cases:
            pack = make_pack(word_ids=["w_1"], recommended_next=recommended)
            self.assertEqual(pack_status_label(pack, TODAY), expected,
                             "recommended_next=%s" % recommended)


if __name__ == "__main__":
    unittest.main(verbosity=2)
