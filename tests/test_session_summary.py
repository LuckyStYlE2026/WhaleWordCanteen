# -*- coding: utf-8 -*-
"""收尾那几句话必须只讲**这一场**的事,而且要讲对。

用户 2026-10-15 报的:

    结束后的提示,20词全部掌握,但是说"有7个词你反复出错",
    这不应该出现在学习单词的部分。

根因:诊断文案把**整个词库**的统计传了进去。词库里别的词的历史错误
就那样跑进了"这一场学得怎么样"的总结里 —— 用户刚学完 20 个全对的词,
却被告知有 7 个词反复出错。

同时守另一件事:**单词表包的状态标签**不能一律显示"还没学过"
(用户同一天报的:"作为单词表的 cet46 和 sample 不应该表示为'还没学过'")。
"""

import unittest

from core.models import Grade, Mastery, Word
from core.packs import PACK_TYPE_STUDY, WordPack, make_vocab_pack
from core.stats import pack_status_label, summarize, summary_for_pack

from .tk_case import HAVE_TK, TkTestCase

TODAY = "2026-10-15"


def word(word_id: str, mastery=Mastery.NEW, wrong: int = 0) -> Word:
    item = Word(id=word_id, spelling_key=word_id, word=word_id,
                translation="释义%s" % word_id)
    item.state.mastery = mastery
    item.state.wrong_count = wrong
    # "学过了"的判据是 next_review 被推过 —— 从没学过的话它还是上次排的
    if mastery != Mastery.NEW or wrong:
        item.state.review_count = 3
        item.state.next_review = "2026-11-01"
    return item


class PackStatusLabelTest(unittest.TestCase):
    """单词表包:按学习进度显示,而不是"还没学过"。"""

    def test_a_vocab_pack_shows_the_study_progress(self):
        from datetime import date
        words = {w.id: w for w in (
            word("a", Mastery.KNOWN), word("b", Mastery.FUZZY),
            word("c", Mastery.NEW), word("d", Mastery.NEW))}
        pack = make_vocab_pack("cet", "cet46", list(words), TODAY)
        own = summary_for_pack(pack, words, date(2026, 10, 15))
        label = pack_status_label(pack, date(2026, 10, 15), own)
        self.assertIn("50%", label)
        self.assertIn("2/4", label)
        self.assertNotIn("还没学过", label)

    def test_a_vocab_pack_nobody_studied_still_says_so(self):
        from datetime import date
        words = {w.id: w for w in (word("a"), word("b"))}
        pack = make_vocab_pack("cet", "cet46", list(words), TODAY)
        own = summary_for_pack(pack, words, date(2026, 10, 15))
        self.assertEqual(pack_status_label(pack, date(2026, 10, 15), own),
                         "还没学过")

    def test_a_studied_vocab_pack_is_fully_studied(self):
        from datetime import date
        words = {w.id: w for w in (word("a", Mastery.KNOWN),
                                   word("b", Mastery.FUZZY))}
        pack = make_vocab_pack("cet", "cet46", list(words), TODAY)
        own = summary_for_pack(pack, words, date(2026, 10, 15))
        label = pack_status_label(pack, date(2026, 10, 15), own)
        self.assertIn("100%", label)

    def test_a_study_pack_with_a_schedule_still_shows_the_due_date(self):
        """有排期的包行为不变 —— 不能为了修单词表把学习包也改了。"""
        from datetime import date
        pack = WordPack(id="p", pack_type=PACK_TYPE_STUDY, title="学习词包",
                        created_at=TODAY, word_ids=["a"])
        pack.schedule.recommended_next = "2026-10-18"
        own = summary_for_pack(pack, {"a": word("a", Mastery.KNOWN)},
                               date(2026, 10, 15))
        self.assertEqual(pack_status_label(pack, date(2026, 10, 15), own),
                         "3 天后到期")

    def test_needs_relearn_still_wins(self):
        """顺序不能反:要重学的包不该显示成"已学习 x%"或"n 天后到期"。"""
        from datetime import date
        pack = WordPack(id="p", pack_type=PACK_TYPE_STUDY, title="学习词包",
                        created_at=TODAY, word_ids=["a"])
        pack.schedule.recommended_next = "2026-10-01"
        pack.schedule.needs_relearn = True
        own = summary_for_pack(pack, {"a": word("a", Mastery.KNOWN)},
                               date(2026, 10, 15))
        self.assertEqual(pack_status_label(pack, date(2026, 10, 15), own),
                         "需要重学")


class SummaryScopeTest(unittest.TestCase):
    """汇总的 studied / studied_rate 两个口径。"""

    def test_studied_counts_everything_that_is_not_new(self):
        from datetime import date
        words = {w.id: w for w in (
            word("a", Mastery.KNOWN), word("b", Mastery.FUZZY),
            word("c", Mastery.RELEARN), word("d", Mastery.NEW))}
        summary = summarize(words, date(2026, 10, 15))
        self.assertEqual(summary.total, 4)
        self.assertEqual(summary.studied, 3)
        self.assertAlmostEqual(summary.studied_rate, 0.75)

    def test_an_empty_summary_does_not_divide_by_zero(self):
        from datetime import date
        summary = summarize({}, date(2026, 10, 15))
        self.assertEqual(summary.studied_rate, 0.0)


@unittest.skipUnless(HAVE_TK, "需要图形环境")
class SessionDiagnosisScopeTest(TkTestCase):
    """这一场的总结只讲这一场。"""

    def setUp(self):
        self.app = self.make_app()
        self.messages = []
        import ui.views.exam as exam_view
        import ui.study_flow as flow
        self._saved = (flow.info, exam_view.info)
        flow.info = lambda parent, title, message: self.messages.append(message)
        exam_view.info = lambda parent, title, message: self.messages.append(message)
        self.addCleanup(self._restore)

    def _restore(self):
        import ui.views.exam as exam_view
        import ui.study_flow as flow
        flow.info, exam_view.info = self._saved

    def _add_words(self, count: int, prefix: str, wrong: int = 0,
                   mastery=Mastery.NEW):
        from core.models import Word as W
        items = []
        for index in range(count):
            word_id = "%s_%d" % (prefix, index)
            item = W(id=word_id, spelling_key=word_id, word=word_id,
                     translation="释义%d" % index)
            item.state.mastery = mastery
            item.state.wrong_count = wrong
            if mastery != Mastery.NEW or wrong:
                item.state.review_count = 3
                item.state.next_review = "2026-11-01"
            self.app.words[item.id] = item
            items.append(item)
        return items

    def _learn_all_correct(self, words):
        """走完一场学习:每个词都答对(用真判分器),然后收尾。"""
        from ui.session import SessionPlan
        from core.packs import make_vocab_pack
        pack = make_vocab_pack("cet", "cet46", [w.id for w in words], "2026-10-15")
        self.app.packs.append(pack)
        self.app.settings.study.result_pack_mode = "none"     # 不建包,只看文案
        self.app.show("study", plan=SessionPlan(words=words, title="cet46",
                                                pack=pack, pack_id=pack.id))
        self.app.update()
        view = self.app.current_view
        for _ in range(40):
            if view.finished:
                break
            view.on_next()
            self.app.update()

    def test_a_clean_session_does_not_blame_old_mistakes(self):
        """**就是用户报的那条**:这一场 20 个全对,不该出现"反复出错"。

        词库里故意放 7 个历史错得很多的词 —— 但这一场一个都没考到,
        它们不该出现在这场总结里。
        """
        self._add_words(7, "old", wrong=5, mastery=Mastery.FUZZY)
        fresh = self._add_words(20, "new")
        self._learn_all_correct(fresh)

        blob = "\n".join(self.messages)
        self.assertIn("记住 20", blob)
        self.assertNotIn("反复出错", blob)

    def test_learning_never_reports_repeated_mistakes(self):
        """**用户 2026-10-17 报的那条**:学习里根本没有"答错"这条路。

        「下一组」是"记住了",页面没有"不会"这个选项 —— 所以
        "有 N 个词你反复出错"在学习总结里**永远**不该出现。

        而 `WordState.is_mistake()` 看的是**累积**的 wrong_count
        (错两次、或错过一次且还没连对)。一个词只要**上一次考试**错过,
        这次只是被看过一遍,就仍然满足那个条件 —— 于是学完 20 个词却被告知
        "有 N 个词反复出错"。见 ui/study_flow.session_summary。
        """
        from ui.session import SessionPlan
        from core.packs import make_vocab_pack

        words = self._add_words(3, "s")
        # 把这几个词做成"历史错题":累积错了很多次
        for word in words:
            word.state.wrong_count = 9
            word.state.streak_correct = 0
        pack = make_vocab_pack("cet", "cet46", [w.id for w in words], "2026-10-15")
        self.app.packs.append(pack)
        self.app.settings.study.result_pack_mode = "none"
        self.app.show("study", plan=SessionPlan(words=words, title="cet46",
                                                pack=pack, pack_id=pack.id))
        self.app.update()
        view = self.app.current_view
        view.on_finish()                 # 走正常收尾(这一屏按"记住了"记)
        self.app.update()

        blob = "\n".join(self.messages)
        self.assertNotIn("反复出错", blob,
                         "学习总结里出现了'反复出错' —— 学习没有答错这条路")
        # 但这一场的成绩单还是要说清楚
        self.assertIn("记住 3", blob)

    def test_ending_midway_does_not_double_count_the_current_page(self):
        """当前那一屏已经记过时,收尾不该再记一遍。

        同一个词被评两次会让 box 连跳两级 —— 那是"多学了一次"的假象。
        """
        from ui.session import SessionPlan
        from core.packs import make_vocab_pack

        words = self._add_words(4, "d")
        pack = make_vocab_pack("cet", "cet46", [w.id for w in words], "2026-10-15")
        self.app.packs.append(pack)
        self.app.settings.study.result_pack_mode = "none"
        self.app.settings.study.page_size = 5      # 一屏放得下全部 4 个
        self.app.show("study", plan=SessionPlan(words=words, title="cet46",
                                                pack=pack, pack_id=pack.id))
        self.app.update()
        view = self.app.current_view

        view._commit_current_page()                 # 记这一屏
        first = dict(view.tally)
        view._commit_current_page()                 # 再记一次:应当什么都不做
        self.assertEqual(dict(view.tally), first, "当前屏被记了两遍")
        for word in words:
            self.assertEqual(word.state.review_count, 1,
                             "「%s」被评了两次 —— box 会跳两级" % word.word)


if __name__ == "__main__":
    unittest.main()
