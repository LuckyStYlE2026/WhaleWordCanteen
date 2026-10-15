# -*- coding: utf-8 -*-
"""调度器测试。

这是全项目最重要的算法 —— 它决定用户什么时候被安排复习什么词,
算错了用户会直接感受到"这软件瞎安排"。所以测试写得比别处密。

关键手法:**所有测试都传一个固定的 today**,不用 date.today()。
否则测试结果会随运行日期变化,那就不叫测试了。
"""

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import Grade, Mastery, Word, WordState        # noqa: E402
from core.packs import (                                       # noqa: E402
    PACK_TYPE_STUDY,
    REGULARITY_DELAYED,
    REGULARITY_ON_SCHEDULE,
    REGULARITY_OVERDUE,
    PackSchedule,
    WordPack,
)
from core.scheduler import (                                   # noqa: E402
    EBBINGHAUS_LADDER,
    EbbinghausScheduler,
    initial_state,
    parse_day,
)

TODAY = date(2026, 10, 12)


def make_word(word_id="w_1", next_review=None, **state_kwargs):
    """造一个测试用单词。next_review 直接用字符串,方便断言。"""
    word = Word(id=word_id, spelling_key=word_id, word=word_id, translation="意思")
    word.state = WordState(next_review=next_review, **state_kwargs)
    return word


class TestLadderBasics(unittest.TestCase):
    def test_ladder_is_ascending_and_starts_at_zero(self):
        """阶梯必须严格递增,否则 box 前进却不会推远复习日期。"""
        self.assertEqual(EBBINGHAUS_LADDER[0], 0)
        for earlier, later in zip(EBBINGHAUS_LADDER, EBBINGHAUS_LADDER[1:]):
            self.assertLess(earlier, later)

    def test_parse_day_handles_junk(self):
        """手工编辑过的存档里什么日期都可能出现,不能让它把程序搞崩。"""
        self.assertEqual(parse_day("2026-10-12"), date(2026, 10, 12))
        self.assertIsNone(parse_day(""))
        self.assertIsNone(parse_day(None))
        self.assertIsNone(parse_day("昨天"))
        self.assertIsNone(parse_day("2026-13-45"))

    def test_initial_state_is_due_immediately(self):
        """新导入的词必须当天就能学,否则用户会以为导入失败了。"""
        state = initial_state(TODAY)
        self.assertEqual(state.next_review, "2026-10-12")
        self.assertEqual(state.box, 0)
        self.assertEqual(state.mastery, Mastery.NEW)


class TestGradeCorrect(unittest.TestCase):
    """答对:box 前进,间隔跳到新等级,连续答对累积。"""

    def setUp(self):
        self.scheduler = EbbinghausScheduler()

    def test_first_correct_gives_one_day(self):
        result = self.scheduler.grade(WordState(), Grade.CORRECT, TODAY)
        self.assertEqual(result.box, 1)
        self.assertEqual(result.interval_days, 1)
        self.assertEqual(result.next_review, "2026-10-13")
        self.assertEqual(result.streak_correct, 1)
        self.assertEqual(result.correct_count, 1)
        self.assertEqual(result.review_count, 1)
        self.assertEqual(result.last_review, "2026-10-12")

    def test_interval_matches_ladder_at_every_box(self):
        """逐级验证:每一步的间隔都必须等于阶梯上对应下标的值。"""
        state = WordState()
        for expected_box in range(1, len(EBBINGHAUS_LADDER)):
            state = self.scheduler.grade(state, Grade.CORRECT, TODAY)
            self.assertEqual(state.box, expected_box)
            self.assertEqual(state.interval_days, EBBINGHAUS_LADDER[expected_box],
                             "box=%d 的间隔不对" % expected_box)
            self.assertEqual(state.next_review,
                             (TODAY + timedelta(days=EBBINGHAUS_LADDER[expected_box])).isoformat())

    def test_box_is_capped_at_top_of_ladder(self):
        """连续答对不会让间隔无限增长,封顶在 30 天。"""
        state = WordState(box=len(EBBINGHAUS_LADDER) - 1)
        for _ in range(5):
            state = self.scheduler.grade(state, Grade.CORRECT, TODAY)
        self.assertEqual(state.box, len(EBBINGHAUS_LADDER) - 1)
        self.assertEqual(state.interval_days, 30)

    def test_mastery_only_at_seven_days_or_more(self):
        """规格要求"7 天以上才算掌握"。

        阶梯下标 3 是 4 天、下标 4 才是 7 天 —— 这是个很容易写错一位的地方,
        所以在这里钉死:4 天时还不算掌握,7 天时才算。
        """
        # 从 box=2 答对 → 落到 box=3,间隔 4 天,此时还不算掌握
        four_day = self.scheduler.grade(WordState(box=2), Grade.CORRECT, TODAY)
        self.assertEqual(four_day.box, 3)
        self.assertEqual(four_day.interval_days, 4)
        self.assertEqual(four_day.mastery, Mastery.FUZZY, "间隔 4 天不该算掌握")

        # 从 box=3 答对 → 落到 box=4,间隔 7 天,这才算掌握
        seven_day = self.scheduler.grade(WordState(box=3), Grade.CORRECT, TODAY)
        self.assertEqual(seven_day.box, 4)
        self.assertEqual(seven_day.interval_days, 7)
        self.assertEqual(seven_day.mastery, Mastery.KNOWN, "间隔 7 天才算掌握")


class TestGradeFuzzy(unittest.TestCase):
    def setUp(self):
        self.scheduler = EbbinghausScheduler()

    def test_fuzzy_keeps_box_but_halves_interval(self):
        """模糊:不加分也不重罚 —— box 原地不动,间隔砍半。"""
        state = WordState(box=4, interval_days=7, mastery=Mastery.KNOWN, streak_correct=5)
        result = self.scheduler.grade(state, Grade.FUZZY, TODAY)
        self.assertEqual(result.box, 4, "box 不该变")
        self.assertEqual(result.interval_days, 3, "7 天砍半应为 3 天")
        self.assertEqual(result.mastery, Mastery.FUZZY)
        self.assertEqual(result.streak_correct, 0, "连对计数必须清零")
        self.assertEqual(result.fuzzy_count, 1)

    def test_fuzzy_interval_never_drops_below_one_day(self):
        """box=0 时间隔是 0,砍半还是 0 —— 必须兜到 1,否则当天重复同一张卡。"""
        result = self.scheduler.grade(WordState(box=0), Grade.FUZZY, TODAY)
        self.assertEqual(result.interval_days, 1)
        self.assertEqual(result.next_review, "2026-10-13")

    def test_fuzzy_does_not_lose_known_permanently(self):
        """模糊只是暂时的,不该像答错那样标记 lapses。"""
        state = WordState(box=4, mastery=Mastery.KNOWN)
        result = self.scheduler.grade(state, Grade.FUZZY, TODAY)
        self.assertEqual(result.lapses, 0)


class TestGradeWrong(unittest.TestCase):
    def setUp(self):
        self.scheduler = EbbinghausScheduler()

    def test_wrong_resets_to_one_day(self):
        state = WordState(box=4, interval_days=7, mastery=Mastery.KNOWN)
        result = self.scheduler.grade(state, Grade.WRONG, TODAY)
        self.assertEqual(result.box, 3, "box 退一级")
        self.assertEqual(result.interval_days, 1, "打回 1 天")
        self.assertEqual(result.next_review, "2026-10-13")
        self.assertEqual(result.wrong_count, 1)
        self.assertEqual(result.streak_correct, 0)
        self.assertEqual(result.lapses, 1)

    def test_wrong_never_drops_box_below_one(self):
        """不能再退回 box=0 —— 那会让它显得像从没学过的全新词。"""
        state = WordState(box=0)
        result = self.scheduler.grade(state, Grade.WRONG, TODAY)
        self.assertEqual(result.box, 1)

    def test_wrong_marks_relearn_only_if_previously_mastered(self):
        """掌握过的词答错叫"遗忘"(relearn);没掌握过的只是"还没学会"(new)。"""
        mastered = self.scheduler.grade(
            WordState(box=5, mastery=Mastery.KNOWN), Grade.WRONG, TODAY)
        self.assertEqual(mastered.mastery, Mastery.RELEARN)

        learning = self.scheduler.grade(
            WordState(box=2, mastery=Mastery.FUZZY), Grade.WRONG, TODAY)
        self.assertEqual(learning.mastery, Mastery.NEW)


class TestGradeIsPure(unittest.TestCase):
    """grade() 必须返回新状态,不能原地改。

    这保证了调用方能同时持有"判分前"和"判分后"两份状态 ——
    既方便测试,也让"撤销上一步"之类的功能将来能实现。
    """

    def test_original_state_is_not_mutated(self):
        scheduler = EbbinghausScheduler()
        original = WordState(box=1, correct_count=3)
        original.append_history("2026-10-01", Grade.CORRECT)
        before = original.to_dict()

        scheduler.grade(original, Grade.CORRECT, TODAY)

        self.assertEqual(original.to_dict(), before, "原状态被改动了")
        self.assertEqual(len(original.history), 1, "历史被共享而不是复制")

    def test_history_is_appended_on_the_new_state(self):
        scheduler = EbbinghausScheduler()
        original = WordState()
        result = scheduler.grade(original, Grade.CORRECT, TODAY)
        self.assertEqual(len(result.history), 1)
        self.assertEqual(result.history[0].day, "2026-10-12")
        self.assertEqual(result.history[0].result, Grade.CORRECT)

    def test_clone_does_not_share_history_list(self):
        original = WordState()
        original.append_history("2026-10-01", Grade.CORRECT)
        duplicate = original.clone()
        duplicate.append_history("2026-10-02", Grade.WRONG)
        self.assertEqual(len(original.history), 1, "clone 共享了同一个列表")


class TestDueWords(unittest.TestCase):
    """到期查询必须跨词包 —— 这是规格明确要求的设计。"""

    def setUp(self):
        self.scheduler = EbbinghausScheduler()

    def test_only_overdue_words_are_returned(self):
        index = {
            "past": make_word("past", next_review="2026-10-10", review_count=1),
            "today": make_word("today", next_review="2026-10-12", review_count=1),
            "future": make_word("future", next_review="2026-10-20", review_count=1),
        }
        due = self.scheduler.due_words(index, TODAY)
        self.assertEqual([w.id for w in due], ["past", "today"])

    def test_words_never_scheduled_are_not_due(self):
        """没排过复习的新词不算"到期" —— 它们归学习模式管,不混进每日复习。"""
        index = {"new": make_word("new", next_review=None)}
        self.assertEqual(self.scheduler.due_words(index, TODAY), [])

    def test_never_studied_words_are_not_due_even_when_stamped_today(self):
        """新建的词出生就带"今天到期"(见 initial_state),但那是"随时能开始学"。

        不加这道过滤的话,刚导入 100 个词,「今日复习」就会立刻
        摆出 100 个待复习 —— 而其实一个都还没学过。
        """
        index = {"brand_new": make_word("brand_new", next_review="2026-10-12",
                                        interval_days=0, review_count=0)}
        self.assertEqual(self.scheduler.due_words(index, TODAY), [])

    def test_a_word_answered_wrong_is_still_due_tomorrow(self):
        """答错会把 mastery 打回 NEW,但它显然学过,不能因此被踢出复习队列。"""
        wrong_once = make_word("wrong", next_review="2026-10-12",
                               mastery=Mastery.NEW, review_count=1)
        due = self.scheduler.due_words({"wrong": wrong_once}, TODAY)
        self.assertEqual([w.id for w in due], ["wrong"])

    def test_most_overdue_comes_first(self):
        """逾期最久的排最前 —— 它们忘得最厉害。"""
        index = {
            "mild": make_word("mild", next_review="2026-10-11", review_count=1),
            "severe": make_word("severe", next_review="2026-10-01", review_count=1),
            "medium": make_word("medium", next_review="2026-10-05", review_count=1),
        }
        due = self.scheduler.due_words(index, TODAY)
        self.assertEqual([w.id for w in due], ["severe", "medium", "mild"])

    def test_limit_is_respected(self):
        index = {"w%d" % i: make_word("w%d" % i, next_review="2026-10-01",
                                      review_count=1) for i in range(10)}
        self.assertEqual(len(self.scheduler.due_words(index, TODAY, limit=3)), 3)

    def test_limit_zero_means_unlimited(self):
        index = {"w%d" % i: make_word("w%d" % i, next_review="2026-10-01",
                                      review_count=1) for i in range(10)}
        self.assertEqual(len(self.scheduler.due_words(index, TODAY, limit=0)), 10)

    def test_broken_next_review_date_is_ignored(self):
        """存档里的日期被手工改坏时,跳过这个词而不是崩溃。"""
        index = {"broken": make_word("broken", next_review="昨天")}
        self.assertEqual(self.scheduler.due_words(index, TODAY), [])


class TestPackRegularity(unittest.TestCase):
    """规律性判定:决定词包是否需要重学。"""

    def setUp(self):
        self.scheduler = EbbinghausScheduler()

    def make_pack(self, last_studied, recommended_next):
        pack = WordPack(id="p", pack_type=PACK_TYPE_STUDY, title="t",
                        created_at=last_studied, word_ids=["w_1"])
        pack.schedule = PackSchedule(last_studied=last_studied,
                                     recommended_next=recommended_next)
        return pack

    def test_on_time(self):
        pack = self.make_pack("2026-10-05", "2026-10-12")
        self.assertEqual(self.scheduler.evaluate_pack_regularity(pack, TODAY),
                         REGULARITY_ON_SCHEDULE)

    def test_early_return_is_still_on_schedule(self):
        """提前回来学习不该被算作"不规律"。"""
        pack = self.make_pack("2026-10-10", "2026-10-20")
        self.assertEqual(self.scheduler.evaluate_pack_regularity(pack, TODAY),
                         REGULARITY_ON_SCHEDULE)

    def test_slightly_late_is_delayed_not_overdue(self):
        # 原定 10-10(间隔 5 天),晚了 2 天 → 容忍范围 max(2, 2) = 2,刚好算 delayed
        pack = self.make_pack("2026-10-05", "2026-10-10")
        self.assertEqual(self.scheduler.evaluate_pack_regularity(pack, TODAY),
                         REGULARITY_DELAYED)

    def test_very_late_is_overdue(self):
        # 原定 10-01 却拖到 10-12,晚了 11 天
        pack = self.make_pack("2026-09-26", "2026-10-01")
        self.assertEqual(self.scheduler.evaluate_pack_regularity(pack, TODAY),
                         REGULARITY_OVERDUE)

    def test_absolute_cap_overrides_long_intervals(self):
        """硬规则:逾期超过 7 天一律 overdue,哪怕原定间隔是 30 天。

        否则"30 天的间隔拖了 20 天"按比例算还在容忍范围内,
        但 20 天足够把词忘光了。
        """
        pack = self.make_pack("2026-09-01", "2026-10-01")
        # 原定间隔 30 天,拖了 11 天 —— 按比例(15天容忍)本该算 delayed,
        # 但硬规则判定 overdue
        self.assertEqual(self.scheduler.evaluate_pack_regularity(pack, TODAY),
                         REGULARITY_OVERDUE)

    def test_missing_dates_default_to_on_schedule(self):
        pack = self.make_pack("", "")
        self.assertEqual(self.scheduler.evaluate_pack_regularity(pack, TODAY),
                         REGULARITY_ON_SCHEDULE)


class TestRelearnPack(unittest.TestCase):
    def setUp(self):
        self.scheduler = EbbinghausScheduler()

    def test_all_words_are_pushed_back_to_the_queue(self):
        """重学后每个词都必须立刻到期,否则用户点了重学却看不到词。"""
        index = {
            "w_1": make_word("w_1", next_review="2026-11-01",
                             box=5, mastery=Mastery.KNOWN, correct_count=9),
            "w_2": make_word("w_2", next_review="2026-11-01", box=3),
        }
        pack = WordPack(id="p", pack_type=PACK_TYPE_STUDY, title="t",
                        created_at="2026-10-01", word_ids=["w_1", "w_2"])

        affected = self.scheduler.relearn_pack(pack, index, TODAY)

        self.assertEqual(sorted(affected), ["w_1", "w_2"])
        for word in index.values():
            self.assertEqual(word.state.box, 1)
            self.assertEqual(word.state.mastery, Mastery.RELEARN)
            self.assertEqual(word.state.next_review, "2026-10-12")
            self.assertEqual(word.state.streak_correct, 0)

    def test_cumulative_counters_survive_relearn(self):
        """重学不该抹掉历史错误次数 —— 错题本还得记得这个词一直很难。"""
        index = {"w_1": make_word("w_1", box=2, wrong_count=4, correct_count=9)}
        pack = WordPack(id="p", pack_type=PACK_TYPE_STUDY, title="t",
                        created_at="2026-10-01", word_ids=["w_1"])
        self.scheduler.relearn_pack(pack, index, TODAY)
        self.assertEqual(index["w_1"].state.wrong_count, 4)
        self.assertEqual(index["w_1"].state.correct_count, 9)

    def test_missing_word_ids_are_skipped(self):
        """词包里有指向已删除单词的 id 时,跳过而不是崩溃。"""
        index = {"w_1": make_word("w_1", box=2)}
        pack = WordPack(id="p", pack_type=PACK_TYPE_STUDY, title="t",
                        created_at="2026-10-01", word_ids=["w_1", "已删除"])
        self.assertEqual(self.scheduler.relearn_pack(pack, index, TODAY), ["w_1"])


class TestBuildStudyPack(unittest.TestCase):
    def setUp(self):
        self.scheduler = EbbinghausScheduler()

    def test_pack_records_words_and_dates(self):
        words = [make_word("w_1", next_review="2026-10-13"),
                 make_word("w_2", next_review="2026-10-20")]
        pack = self.scheduler.build_study_pack(words, TODAY)
        self.assertEqual(pack.word_ids, ["w_1", "w_2"])
        self.assertEqual(pack.pack_type, PACK_TYPE_STUDY)
        self.assertEqual(pack.created_at, "2026-10-12")
        self.assertEqual(pack.schedule.last_studied, "2026-10-12")
        # 建议下次日期取这批词里最早的到期日
        self.assertEqual(pack.schedule.recommended_next, "2026-10-13")

    def test_pack_falls_back_when_no_word_has_a_date(self):
        pack = self.scheduler.build_study_pack([make_word("w_1")], TODAY)
        self.assertEqual(pack.schedule.recommended_next, "2026-10-13")

    def test_session_records_accuracy(self):
        pack = self.scheduler.build_study_pack([make_word("w_1")], TODAY)
        self.scheduler.record_session(pack, TODAY, correct=8, fuzzy=1, wrong=1)
        self.assertEqual(len(pack.schedule.sessions), 1)
        session = pack.schedule.sessions[0]
        self.assertEqual((session.correct, session.fuzzy, session.wrong), (8, 1, 1))
        self.assertTrue(session.on_time)


if __name__ == "__main__":
    unittest.main(verbosity=2)
