# -*- coding: utf-8 -*-
"""学习页这一版的新行为:**翻页即表态、标记、隐藏老师**。

这一版把学习页的角色换了:以前是"自评 + 对话框",现在是一张单词表,
靠翻页表示"这组我过了"。所以这里锁的是新的语义:

* 「下一组」= 记住了(记 CORRECT、推进度)
* 「上一组」= 回去看,**不记状态**(和「下一组」不对称是故意的)
* 「跳过本组」= 不记状态、不推进度
* 「标记」= 这一组按记住了处理 + 把这一组最后一个词设成书签(再按一次取消)
* 「隐藏老师」= 单词表铺满全屏,按钮文字变成「显示老师」
* 结果包只收**真正评过**的词(提前结束时没看过的词不该混进去)

前一半是纯逻辑(core/tally.py)和不需要窗口的部分,后一半要真窗口。
"""

import unittest

from core import tally as tally_module
from core.models import Grade, Word
from core.packs import make_vocab_pack
from core.pack_progress import bookmark_index
from ui.study_bar import nav_texts, toolbar_texts

from .tk_case import HAVE_TK, TkTestCase


class TallyTest(unittest.TestCase):
    """成绩单:学习页一边评一边加,收尾流程读它。"""

    def test_empty_starts_at_zero(self):
        self.assertEqual(tally_module.empty(),
                         {"correct": 0, "fuzzy": 0, "wrong": 0})

    def test_add_accumulates(self):
        board = tally_module.empty()
        tally_module.add(board, Grade.CORRECT, 3)
        tally_module.add(board, Grade.CORRECT, 2)
        tally_module.add(board, Grade.WRONG, 1)
        self.assertEqual(board["correct"], 5)
        self.assertEqual(board["wrong"], 1)
        self.assertEqual(tally_module.total(board), 6)

    def test_unknown_bucket_is_ignored(self):
        """成绩单的键是固定的三个 —— 多塞一个键会让总结显示成怪东西。"""
        board = tally_module.empty()
        board["不存在的档"] = 0
        tally_module.add(board, Grade.CORRECT, 1)
        self.assertEqual(set(board) - {"correct", "fuzzy", "wrong"}, {"不存在的档"})


class ButtonSetTest(unittest.TestCase):
    """按钮分成了两条,各自该有哪些。换按钮是这一版最显眼的变化,值得锁住。"""

    def test_top_row_holds_the_occasional_actions(self):
        """高频的翻页不在这里 —— 它挪到底部中间了(见下一条)。"""
        self.assertEqual(toolbar_texts(), ["← 返回", "标记", "隐藏老师"])

    def test_bottom_row_holds_the_paging_buttons(self):
        """翻页和收尾放在单词表**下方中间**,手最容易够到。"""
        self.assertEqual(nav_texts(), ["上一组", "下一组", "跳过本组", "结束学习"])

    def test_the_two_rows_together_cover_everything(self):
        """两条行合起来要齐,而且不许有重复 ——

        重复意味着同一个动作有两个入口,过一阵就会有人只改其中一个。
        """
        combined = toolbar_texts() + nav_texts()
        self.assertEqual(len(combined), len(set(combined)))
        for expected in ("← 返回", "上一组", "下一组", "跳过本组", "结束学习",
                         "标记", "隐藏老师"):
            self.assertIn(expected, combined)

    def test_the_old_self_rating_buttons_are_gone(self):
        """「记住了 / 有点模糊 / 没见过」在这一版被翻页取代了。

        它们代表的是"让用户给自己打分",而这一页展示的本来就是释义 ——
        再问一句"你记住了吗"没有信息量。这条是**回归锁**:谁要加回来,
        先在这里被拦住。
        """
        texts = toolbar_texts() + nav_texts()
        for gone in ("记住了", "有点模糊", "没见过"):
            self.assertNotIn(gone, texts)


@unittest.skipUnless(HAVE_TK, "需要图形环境")
class StudyPageTest(TkTestCase):
    """学习页的交互。用真窗口,因为测的是控件状态和面板尺寸。

    基类会把存档指到临时目录(test/tk_case.py),所以这些用例
    不会往用户真实的词包列表里塞测试数据。
    """

    def setUp(self):
        self.app = self.make_app()
        self._add_words()

    def _add_words(self):
        spec = (("atmosphere", "n. 大气层", "1"), ("lithosphere", "n. 岩石圈", "1"),
                ("hydrosphere", "n. 水圈", "2"), ("biosphere", "n. 生物圈", ""),
                ("geosphere", "n. 陆界", ""), ("exosphere", "n. 外逸层", ""))
        words = []
        for index, (spelling, translation, group) in enumerate(spec):
            word = Word(id="w%d" % index, spelling_key=spelling, word=spelling,
                        translation=translation, group=group)
            self.app.words[word.id] = word
            words.append(word)
        self.pack = make_vocab_pack("pack_test", "测试词表",
                                    [w.id for w in words], "2026-01-01")
        self.app.packs.append(self.pack)
        self.words = words

    def _open(self):
        from ui.session import SessionPlan
        plan = SessionPlan(words=self.words, title="测试词表",
                           pack=self.pack, pack_id=self.pack.id)
        self.app.show("study", plan=plan)
        self.app.update()
        return self.app.current_view

    # ---- 翻页 ------------------------------------------------------------

    def test_next_group_counts_as_remembered(self):
        view = self._open()
        first = list(view.pages[0])
        view.on_next()
        self.assertEqual(view.tally["correct"], len(first))
        self.assertIn(first[0].id, [w.id for w in view.graded])

    def test_previous_group_changes_nothing(self):
        """回头**不该**被记成"我记住了" —— 和「下一组」不对称是故意的。"""
        view = self._open()
        view.on_next()
        before = dict(view.tally), len(view.graded), view.progress_to
        view.on_previous()
        self.assertEqual((dict(view.tally), len(view.graded), view.progress_to), before)
        self.assertEqual(view.page_index, 0)

    def test_previous_on_first_group_is_a_no_op(self):
        view = self._open()
        view.on_previous()
        self.assertEqual(view.page_index, 0)

    def test_skip_records_nothing_and_does_not_advance_progress(self):
        view = self._open()
        view.on_skip()
        self.assertEqual(tally_module.total(view.tally), 0)
        self.assertEqual(view.graded, [])
        self.assertEqual(view.progress_to, 0)

    # ---- 标记 ------------------------------------------------------------

    def test_marking_grades_the_group_and_sets_the_bookmark(self):
        """标记 = 这一组按"记住了" + 把这一组**最后一个词**设成书签。"""
        view = self._open()
        group = list(view.pages[0])
        view.on_mark()
        self.assertEqual(bookmark_index(self.pack), self.pack.word_ids.index(group[-1].id))
        self.assertEqual(view.tally["correct"], len(group))

    def test_marking_twice_cancels_the_bookmark(self):
        """和词包编辑页的「标记此处」一致:再按一次就是取消。"""
        view = self._open()
        view.on_mark()
        self.assertGreaterEqual(bookmark_index(self.pack), 0)
        view.on_mark()
        self.assertEqual(bookmark_index(self.pack), -1)

    def test_cancelling_does_not_undo_the_grading(self):
        """取消标记只是"不想让它当起点了",不是要否认刚学过的词。"""
        view = self._open()
        group = list(view.pages[0])
        view.on_mark()
        recorded = dict(view.tally)
        view.on_mark()
        self.assertEqual(dict(view.tally), recorded)
        self.assertEqual(view.tally["correct"], len(group))

    def test_marking_shows_a_star_in_the_title(self):
        view = self._open()
        self.assertNotIn("★", view.page_title.cget("text"))
        view.on_mark()
        self.assertIn("★", view.page_title.cget("text"))

    def test_marking_a_result_pack_is_refused_without_crashing(self):
        """结果包没有"第几个"这个坐标,标记对它没有意义。"""
        view = self._open()
        view.plan.pack = make_vocab_pack("out", "结果包", ["w0"], "2026-01-01")
        view.plan.pack.pack_type = "study"
        view.on_mark()          # 不该抛异常
        self.assertEqual(view.tally["correct"], 0)

    # ---- 隐藏老师 --------------------------------------------------------

    def test_hiding_the_teacher_hides_her_and_widens_the_list(self):
        view = self._open()
        self.assertTrue(view.teacher_visible)
        view.on_toggle_teacher()
        self.app.update()
        self.assertFalse(view.teacher_visible)
        self.assertFalse(view.scene.character, "老师还在画面上")
        self.assertEqual(view.toolbar.teacher_button.cget("text"), "显示老师")

    def test_showing_the_teacher_again_restores_her(self):
        """藏起来不是把形象弄丢 —— 再按一次要原样回来。"""
        view = self._open()
        view.on_toggle_teacher()
        view.on_toggle_teacher()
        self.app.update()
        self.assertTrue(view.teacher_visible)
        self.assertTrue(view.scene.character)
        self.assertEqual(view.toolbar.teacher_button.cget("text"), "隐藏老师")

    def test_hidden_teacher_is_not_clickable(self):
        """老师藏起来之后,画面上不该还能点出一个对话页来。"""
        view = self._open()
        view.on_toggle_teacher()
        self.app.update()
        self.assertFalse(view.scene.character_hit(600, 300))

    # ---- 结果包 ----------------------------------------------------------

    def test_result_pack_only_holds_the_words_actually_graded(self):
        """提前结束时,没看过的词不该混进结果包。"""
        from ui.study_flow import _store_result
        from ui.session import SessionPlan
        from core.config import RESULT_PACK_SEPARATE

        view = self._open()
        view.on_next()                      # 只学第一组
        graded = list(view.graded)
        view.plan.words = self.words        # 计划里还有没看过的词
        self.app.settings.study.result_pack_mode = RESULT_PACK_SEPARATE

        pack, _mode = _store_result(view, view.plan, graded, 2, 0, 0)
        self.assertEqual(pack.word_ids, [w.id for w in graded])
        self.assertLess(pack.word_count, len(self.words))

    def test_finishing_never_tries_to_speak(self):
        """收尾时**不该**去调 say()。

        学习页这一版没有对话框,也就没有 say()。以前收尾流程是无条件调它的,
        于是每个调用方都被迫养一个"什么都不做"的同名方法 —— 那是一段只为
        骗过调用方而存在的代码。现在由 scene_dialogue 决定说不说。

        这条测试用"调了就报错"的替身来锁:真调了会抛 AttributeError。
        """
        from ui import study_flow

        view = self._open()
        self.assertFalse(getattr(view, "scene_dialogue", True),
                         "学习页不该有对话框")

        def explode(*_args, **_kwargs):
            raise AssertionError("学习页没有对话框,不该调 say()")

        view.say = explode
        view.on_next()          # 记一组,让 rated > 0
        self.app.settings.study.result_pack_mode = "none"
        view.on_finish()        # 收尾;不该因为 say 而炸


if __name__ == "__main__":
    unittest.main()
