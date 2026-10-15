# -*- coding: utf-8 -*-
"""学习/考试里两个**账不会算**的问题。

用户 2026-10-15 报的两个:

1. 学到一半点「结束」,**当前屏幕上那一屏没被保存**。
   20 词、点一次「下一组」再结束,应当保存 10 词,实际只保存 5 词。

2. 考试选整个 100 词的单词表,提示问"词包过大,是否确认考试",
   确认之后进去**只有 20 个词** —— 那个确认框等于在骗人。

两个都是"说的和做的不一致",而且都不报错。
"""

import unittest

from core.models import Word

from .tk_case import HAVE_TK, TkTestCase


@unittest.skipUnless(HAVE_TK, "需要图形环境")
class CommitCurrentPageTest(TkTestCase):
    """学到一半结束:当前那一屏也要算数。"""

    def setUp(self):
        self.app = self.make_app()
        # 从干净词库开始 —— 基类指向临时目录,但那里可能留着上一个用例的词
        self.app.words.clear()
        self.app.packs.clear()
        self._stub_dialogs()
        self.words = self._add_words(20)

    def _stub_dialogs(self):
        import ui.views.exam as exam_view
        import ui.study_flow as flow
        self.messages = []
        self._saved = (flow.info, exam_view.info)
        hook = lambda parent, title, message: self.messages.append(message)
        flow.info = hook
        exam_view.info = hook
        self.addCleanup(self._restore)

    def _restore(self):
        import ui.views.exam as exam_view
        import ui.study_flow as flow
        flow.info, exam_view.info = self._saved

    def _add_words(self, count):
        from core.packs import make_vocab_pack
        words = []
        for index in range(count):
            word = Word(id="p_%d" % index, spelling_key="p%d" % index,
                        word="p%d" % index, translation="释义%d" % index)
            self.app.words[word.id] = word
            words.append(word)
        self.pack = make_vocab_pack("cet", "cet46", [w.id for w in words],
                                    "2026-10-15")
        self.app.packs.append(self.pack)
        return words

    def _open(self, page_size=5):
        from ui.session import SessionPlan
        self.app.settings.study.page_size = page_size
        self.app.settings.study.result_pack_mode = "merge"
        self.app.show("study", plan=SessionPlan(words=list(self.words),
                                                title="cet46", pack=self.pack,
                                                pack_id=self.pack.id))
        self.app.update()
        return self.app.current_view

    def _result_pack(self):
        for pack in self.app.packs:
            if pack.pack_type == "study":
                return pack
        return None

    def test_ending_after_one_next_saves_two_pages(self):
        """**用户报的那条**:20 词、点一次下一组、结束 -> 保存 10 词。"""
        view = self._open()
        view.on_next()                      # 第 1 屏记分并翻到第 2 屏
        self.app.update()
        self.assertEqual(len(view.graded), 5)
        view.on_finish()
        self.app.update()
        self.assertEqual(self._result_pack().word_count, 10,
                         "当前那一屏没被保存 —— 用户白看了 5 个词")

    def test_ending_without_pressing_next_saves_the_first_page(self):
        """一次都不按就结束:第一屏(他在看的那一屏)也该保存。"""
        view = self._open()
        view.on_finish()
        self.app.update()
        self.assertEqual(self._result_pack().word_count, 5)

    def test_ending_after_two_nexts_saves_three_pages(self):
        view = self._open()
        view.on_next()
        view.on_next()
        self.app.update()
        view.on_finish()
        self.app.update()
        self.assertEqual(self._result_pack().word_count, 15)

    def test_back_also_saves_the_current_page(self):
        """「返回」和「结束学习」只该差一个落点,记分行为必须一样。"""
        view = self._open()
        view.on_next()
        self.app.update()
        view.on_back()
        self.app.update()
        self.assertEqual(self._result_pack().word_count, 10)

    def test_the_whole_session_is_saved_when_it_runs_to_the_end(self):
        """自然学完时,20 个词一个都不能少(也别多算)。"""
        view = self._open()
        for _ in range(10):
            if view.finished:
                break
            view.on_next()
            self.app.update()
        self.assertEqual(self._result_pack().word_count, 20)
        for word in self.words:
            self.assertEqual(word.state.review_count, 1,
                             "「%s」被评了 %d 次" % (word.word,
                                                word.state.review_count))

    def test_skipping_does_not_count_the_page_as_remembered(self):
        """「跳过本组」是"我还没准备好评价它",跳过之后结束不该把它记成记住。

        跳过会翻页,所以结束记的是**新**那一屏 —— 被跳过的那一屏不算数。
        """
        view = self._open()
        view.on_skip()
        self.app.update()
        view.on_finish()
        self.app.update()
        pack = self._result_pack()
        self.assertEqual(pack.word_count, 5)
        # 第 1 屏(被跳过的那 5 个)不该出现在结果包里
        for word in self.words[:5]:
            self.assertNotIn(word.id, pack.word_ids,
                             "被跳过的那一屏被记成记住了")


@unittest.skipUnless(HAVE_TK, "需要图形环境")
class LargeExamMeansAllTest(TkTestCase):
    """考试题量:**勾了什么就考完什么**,没有任何截断。

    这一条被来回改过三次,所以这里的用例是逐条锁住结论的:

    * 勾一份 30 词的词包 → 考 30 题(**以前会被「每场考试题数」砍成 20**,
      剩下的 10 个用户永远考不到);
    * 勾 100 词的整表 → 考 100 题,但**「词包极大」那一问要问**
      (用户要求保留:100 题确实很长,值得先打个招呼);
    * 那一问是**纯确认**(是非题),不再有"考全部 / 只抽一部分"的选项 ——
      题量本来就没有别的可能。
    """

    def setUp(self):
        self.app = self.make_app()
        # 从干净词库开始 —— 不清的话会考到别的用例留下的词
        self.app.words.clear()
        self.app.packs.clear()
        self.app.settings.study.exam_size = 20
        self.words = self._add_words(100)
        # 一个 90 词的学习词包(模拟"今天学的那些词")
        from core.packs import WordPack, PACK_TYPE_STUDY
        self.subset = WordPack(id="st_sub", pack_type=PACK_TYPE_STUDY,
                               title="2026-10-16 学习词包",
                               created_at="2026-10-16",
                               word_ids=[w.id for w in self.words[:90]],
                               source_vocab=self.pack.id)
        self.app.packs.append(self.subset)
        self._stub_dialogs()

    def _add_words(self, count):
        from core.packs import make_vocab_pack
        words = []
        for index in range(count):
            word = Word(id="e_%d" % index, spelling_key="e%d" % index,
                        word="e%d" % index, translation="释义%d" % index)
            self.app.words[word.id] = word
            words.append(word)
        self.pack = make_vocab_pack("cet46", "cet46", [w.id for w in words],
                                    "2026-10-15")
        self.app.packs.append(self.pack)
        return words

    def _stub_dialogs(self):
        import ui.dialogs as dialogs
        import ui.views.exam as exam_view
        import ui.views.exam_pick as exam_pick
        import ui.views.exam_seed_flow as seed_flow
        import ui.views.pack_pick as pack_pick

        # 常量从**定义它们的地方**取:exam_pick 只是转出过一部分,
        # 而转出的那几个后来随重构撤掉了(测试不该依赖转出)
        from ui.exam_pick_text import SEED_NONE
        from ui.session import ORDER_SEQUENTIAL

        self.asked = []
        self.confirm_answer = True       # 词量那一问答"确认"
        self.order_choice = ORDER_SEQUENTIAL
        self.seed_choice = SEED_NONE

        def ask_choice(parent, theme, title, prompt, options, initial=""):
            self.asked.append((title, prompt))
            if title == "随机考试":
                return self.seed_choice
            return self.order_choice

        hook = lambda parent, title, message: self.asked.append((title, message))
        self._saved = (exam_view.info, pack_pick.info, dialogs.info,
                       dialogs.confirm, seed_flow.ask_choice,
                       exam_pick.ask_choice)

        def fake_confirm(parent, title, message, **kwargs):
            # 词量那一问走的是 confirm(纯确认),但它问的内容也要记下来 ——
            # 否则"它到底问没问、问的是什么"就无从断言
            self.asked.append((title, message))
            return self.confirm_answer

        exam_view.info = hook
        pack_pick.info = hook
        dialogs.info = hook
        dialogs.confirm = fake_confirm
        seed_flow.ask_choice = ask_choice
        exam_pick.ask_choice = ask_choice
        self.addCleanup(self._restore)

    def _restore(self):
        import ui.dialogs as dialogs
        import ui.views.exam as exam_view
        import ui.views.exam_pick as exam_pick
        import ui.views.exam_seed_flow as seed_flow
        import ui.views.pack_pick as pack_pick
        (exam_view.info, pack_pick.info, dialogs.info, dialogs.confirm,
         seed_flow.ask_choice, exam_pick.ask_choice) = self._saved

    def _start(self, pick: str = "vocab"):
        """开考。pick="vocab" 勾整份单词表;"study" 勾那个学习词包。"""
        self.app.show("exam_pick")
        self.app.update()
        view = self.app.current_view
        wanted = self.pack.id if pick == "vocab" else self.subset.id
        for key, var in view.pack_list._vars.items():
            var.set(key == wanted)
        view.on_action()
        self.app.update()
        return self.app.current_view

    def _titles(self):
        return [title for title, _ in self.asked]

    # ---- 题量:勾了什么就考完什么 ------------------------------------------

    def test_a_small_pack_is_asked_completely(self):
        """**用户报的那条**:30 词的词包要考满 30,不能被砍成 20。"""
        self.app.words.clear()
        self.app.packs.clear()
        self.words = self._add_words(30)
        self.app.settings.study.exam_size = 20
        view = self._start("vocab")
        self.assertEqual(len(view.plan.words), 30,
                         "普通词包被「每场考试题数」截断了")
        self.assertNotIn("词量提醒", self._titles(), "小包不该问那一句")

    def test_a_whole_vocab_pack_is_asked_completely(self):
        view = self._start("vocab")
        self.assertEqual(self.app.current_view_name, "exam")
        self.assertEqual(len(view.plan.words), 100)

    def test_a_study_pack_is_asked_completely(self):
        """**学习词包和单词表没有区别** —— 都是"我勾中的一份词包"。

        早先学习词包被当成"子集"、又挨了 exam_size 一刀,剩 10 个词永远
        考不到(用户 2026-10-17 报的)。
        """
        view = self._start("study")
        self.assertEqual(len(view.plan.words), 90)

    def test_a_large_pack_still_asks_the_volume_question(self):
        """那一问必须保留(用户 2026-10-16 要求)。

        它是给用户的一句**承诺**,不是装饰;删掉就等于悄悄开始一场 100 题的考试。
        """
        self._start("vocab")
        self.assertIn("词量提醒", self._titles())

    def test_nothing_is_truncated_however_the_question_is_answered(self):
        """"确认"只是确认 —— 它不改题量,所以答什么都是考 100 题。"""
        self.confirm_answer = True
        view = self._start("vocab")
        self.assertEqual(len(view.plan.words), 100)

    def test_cancelling_the_volume_question_does_not_start_the_exam(self):
        self.confirm_answer = False
        self._start("vocab")
        self.assertEqual(self.app.current_view_name, "exam_pick",
                         "用户在词量那一问取消了,不该开考")

    def test_the_question_says_how_many_will_be_tested(self):
        """提示里要写清题量,否则用户不知道自己在确认什么。"""
        self._start("vocab")
        prompt = [item for item in self.asked if item[0] == "词量提醒"][0][1]
        self.assertIn("100", prompt)


if __name__ == "__main__":
    unittest.main()
