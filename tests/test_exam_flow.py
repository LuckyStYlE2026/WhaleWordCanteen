# -*- coding: utf-8 -*-
"""考试结果包的**界面**那一半:落到哪份词表、级联删除、随机考试的加题。

纯逻辑那一半(三档怎么分、包怎么命名)在 tests/test_exam_group.py。
这里管的是"点了按钮之后实际发生什么":

* 勾**学习词包**去考,结果要落到它**来源的那份单词表**名下
  (用户 2026-10-14 选的就是这条:一份词表永远只有三个考试包);
* 删单词表时,它名下三个考试包跟着走(子包脱离父包就没有出处);
* 「随机考试」的子选项:从考试词包里按 3:4:5 抽一批混进来。

弹窗全部换成了替身 —— 真弹窗会阻塞,而这里要验的是"选了之后做什么",
不是弹窗长什么样。
"""

import unittest

from core import exam_group
from core.models import Word
from core.exam_group import is_exam_pack
from core.pack_edit import remove_pack_and_children
from core.packs import (
    PACK_KIND_KNOWN,
    PACK_KIND_WRONG,
    PACK_TYPE_STUDY,
    WordPack,
    make_vocab_pack,
)

from .tk_case import HAVE_TK, TkTestCase


def fuzzy_answer(word) -> str:
    """造一个落在模糊带的答案(判分器给 0.55 ~ 0.85)。

    做法:取释义的两个字并在中间插一个字,既不是子串(撞不上 0.88 的包含
    关系)也不至于完全不像。算不出长度够的释义时退回一个字 ——
    那一种可能落到"正确"里,调用方的断言会当场发现。
    """
    text = (word.translation or "").strip()
    if len(text) >= 3:
        return text[0] + "某" + text[-1]
    return text[:1] or "某"


class HarnessMixin:
    """造几个词、一份单词表,并把弹窗换成替身。"""

    def setup_app(self, count: int = 6):
        self.app = self.make_app()
        self.words = []
        for index in range(count):
            word = Word(id="t_%d" % index, spelling_key="k%d" % index,
                        word="k%d" % index, translation="释义%d" % index)
            self.app.words[word.id] = word
            self.words.append(word)
        self.vocab = make_vocab_pack("sample", "sample",
                                     [w.id for w in self.words], "2026-10-14")
        self.app.packs.append(self.vocab)
        self.app.settings.study.exam_size = count
        self.prompts = []
        self.answers = {"volume": True, "order": "sequential", "seed": "none"}
        self._stub_dialogs()

    def _stub_dialogs(self):
        import ui.dialogs as dialogs
        import ui.views.exam as exam_view
        import ui.views.exam_pick as exam_pick
        import ui.views.exam_seed_flow as seed_flow
        import ui.views.pack_pick as pack_pick

        def fake_choice(parent, theme, title, prompt, options, initial=""):
            self.prompts.append((title, prompt))
            if title == "随机考试":
                return self.answers["seed"]
            return self.answers["order"]

        def fake_info(parent, title, message):
            self.prompts.append((title, message))

        # ⚠️ 替身要按**现在实际的引用位置**打。
        #
        # 早先这里还替了 `exam_pick.info` / `exam_pick.confirm`,但那两处后来
        # 都不在 exam_pick 里了(v1.15 的"词量提醒"回到纯 confirm,
        # 加题那一支搬去了 exam_seed_flow)。留着一个不存在的属性会在
        # `self._saved = (...)` 那一行直接 AttributeError —— 报的是替身的问题,
        # 看起来却像被测代码坏了。
        #
        # 现在 exam_pick 用的是 `ui.dialogs.confirm` 和 `ui.prompts.ask_choice`,
        # 所以替 dialogs 那一层就够(它也是 exam_seed_flow 的落点)。
        self._saved = (exam_view.info, pack_pick.info, dialogs.info,
                       dialogs.confirm, seed_flow.ask_choice,
                       exam_pick.ask_choice)
        exam_view.info = fake_info
        pack_pick.info = fake_info
        dialogs.info = fake_info
        # 词量那一问是纯确认(是非题):这一组造的包都不大,一般问不到;
        # 一律答"确认",免得测试被一个和本组无关的弹窗卡住。
        dialogs.confirm = lambda *a, **k: True
        seed_flow.ask_choice = fake_choice
        exam_pick.ask_choice = fake_choice
        self.addCleanup(self._restore_dialogs)

    def _restore_dialogs(self):
        import ui.dialogs as dialogs
        import ui.views.exam as exam_view
        import ui.views.exam_pick as exam_pick
        import ui.views.exam_seed_flow as seed_flow
        import ui.views.pack_pick as pack_pick
        (exam_view.info, pack_pick.info, dialogs.info, dialogs.confirm,
         seed_flow.ask_choice, exam_pick.ask_choice) = self._saved

    def take_exam(self, correct: int, fuzzy: int = 0):
        """开一场考试:前 correct 个答对、接着 fuzzy 个答得含糊,其余答错。

        含糊 = 只答出释义的第一个字。判分器对"答案只是义项的一部分"给
        0.88(在正确阈值之上)—— 那对短释义不成立,所以这里**按当前位置
        算一个真的落在模糊带的答案**:答对一部分但不够撞上包含关系。
        算不出来时跳过(那一个词就不算模糊,后面的断言会自己发现)。
        """
        self.app.show("exam_pick")
        self.app.update()
        self.app.current_view.pack_list.check_all(True)
        self.app.current_view.on_action()
        self.app.update()
        exam = self.app.current_view
        answered = 0
        while exam.session is not None:
            if exam.awaiting_next:
                exam.on_submit()          # 翻到下一题
                self.app.update()
                continue
            word = exam.session.current
            if answered < correct:
                answer = word.translation
            elif answered < correct + fuzzy:
                answer = fuzzy_answer(word)
            else:
                answer = "完全不对的一个答案"
            exam.answer_var.set(answer)
            exam.on_submit()
            self.app.update()
            answered += 1
            self.assertLess(answered, 80, "答不完,可能卡住了")
        return answered


@unittest.skipUnless(HAVE_TK, "需要图形环境")
class ExamStoresIntoVocabTest(HarnessMixin, TkTestCase):
    """考完试,结果进哪三个包。"""

    def setUp(self):
        self.setup_app()

    def test_exam_results_land_in_three_fixed_packs(self):
        self.take_exam(correct=4)
        packs = exam_group.exam_packs_of(self.app.packs, "sample")
        self.assertEqual(len(packs), 3)
        self.assertEqual(len({pack.id for pack in packs}), 3)

    def test_the_three_kinds_are_reachable_and_cover_the_exam(self):
        self.take_exam(correct=4)
        packs = {pack.kind: pack for pack in
                 exam_group.exam_packs_of(self.app.packs, "sample")}
        self.assertEqual(packs[PACK_KIND_KNOWN].word_count, 4)
        self.assertEqual(packs[PACK_KIND_WRONG].word_count, 2)

    def test_learning_pack_exam_still_lands_in_the_source_vocab(self):
        """用户考试多半勾"今天的学习词包" —— 结果也要落到那份单词表名下,
        否则每学一批就多一套考试包,又变回堆积。"""
        self.app.packs.append(WordPack(
            id="pack_20261014_001", pack_type=PACK_TYPE_STUDY,
            title="2026-10-14 学习词包", created_at="2026-10-14",
            word_ids=[w.id for w in self.words], source_vocab="sample"))
        self.take_exam(correct=2)
        packs = exam_group.exam_packs_of(self.app.packs, "sample")
        self.assertEqual(len(packs), 3)
        self.assertEqual(sum(pack.word_count for pack in packs), len(self.words))

    def test_the_summary_says_which_vocab_it_updated(self):
        """考完那句提示必须说清归属 —— 用户看不到磁盘上多了几个文件,
        不说的话他下次发现包数没变会以为这次没记上。"""
        self.take_exam(correct=4)
        blob = "\n".join("%s\n%s" % pair for pair in self.prompts)
        self.assertIn("sample", blob)
        self.assertIn("考试结果包", blob)

    def test_two_exams_do_not_grow_the_pack_list(self):
        self.take_exam(correct=6)
        before = len(self.app.packs)
        self.take_exam(correct=0)
        self.assertEqual(len(self.app.packs), before,
                         "考第二次又多出包来了")


@unittest.skipUnless(HAVE_TK, "需要图形环境")
class CascadeDeleteTest(HarnessMixin, TkTestCase):
    """删单词表时,它名下三个考试包跟着走。"""

    def setUp(self):
        self.setup_app()

    def test_deleting_the_vocab_takes_its_exam_packs(self):
        self.take_exam(correct=4)
        self.assertEqual(len(exam_group.exam_packs_of(self.app.packs, "sample")), 3)
        children = remove_pack_and_children(self.app.words, self.app.packs,
                                            self.vocab)
        self.assertEqual(len(children), 3)
        self.assertNotIn(self.vocab, self.app.packs)
        layout_ids = [pack.id for pack in self.app.packs]
        for child in children:
            self.assertNotIn(child.id, layout_ids)

    def test_deleting_keeps_words_that_another_pack_still_uses(self):
        """级联删除不能把别的包还在用的词一起删掉。"""
        self.take_exam(correct=4)
        self.app.packs.append(make_vocab_pack("keeper", "保留表",
                                              [w.id for w in self.words],
                                              "2026-10-14"))
        remove_pack_and_children(self.app.words, self.app.packs, self.vocab)
        for word in self.words:
            self.assertIn(word.id, self.app.words, "词被误删了")

    def test_deleting_a_vocab_without_exams_is_harmless(self):
        children = remove_pack_and_children(self.app.words, self.app.packs,
                                            self.vocab)
        self.assertEqual(children, [])


@unittest.skipUnless(HAVE_TK, "需要图形环境")
class RandomSeedTest(HarnessMixin, TkTestCase):
    """「随机考试 → 随机加入考试词包」这一层子选项。

    ⚠️ 这一功能**只对子集范围**(勾学习词包 / 考试包)有意义。勾**整份单词表**
    的时候错词本来就在范围里,再抽一遍等于把同一个词考第二次 —— 所以那一问
    不显示、也不生效(用户 2026-10-16 的要求)。下面的用例都勾一个学习词包
    来造出子集范围。
    """

    # 这一组要**够多的词**才能测出"加题进来了":
    # 先考一场把三档填满,再只勾其中一小部分 —— 加题带来的必须是**新词**。
    # (用默认的 6 词是不够的:6 个词一场考完,三个考试包里全是它们,
    #  再怎么抽也抽不出新的来,断言就永远立不住。)
    TOTAL = 18
    SUBSET = 6

    def setUp(self):
        self.setup_app(count=self.TOTAL)
        # 先考一场(把整份词表都考一遍),让三个考试包里有词
        self.take_exam(correct=6, fuzzy=6)   # 6 对 / 6 模糊 / 6 错
        self.subset = self._make_subset()

    def _make_subset(self):
        """造一个只含**前几个(答对的那批)**词的学习词包,用作"子集范围"。

        ⚠️ 必须挑"答对"那批,不能让这个测试带随机性:
        加题是从三档里按 3:4:5 抽的,如果子集和别的档有重叠,抽出来的词
        可能**全都在这一场里了**,于是"有没有加进来"就变成了运气 ——
        时过时不过的测试比没有测试更糟。

        这一场是前 6 个答对、中间 6 个模糊、后面 6 个错,所以三个档正好是
        t_0-5 / t_6-11 / t_12-17。子集取答对那批,那么加题只要抽到模糊或
        错题档,**必然是新词**。
        """
        study = WordPack(id="sub_study", pack_type=PACK_TYPE_STUDY,
                         title="2026-10-16 学习词包", created_at="2026-10-16",
                         word_ids=[w.id for w in self.words[:self.SUBSET]],
                         source_vocab="sample")
        self.app.packs.append(study)
        return study

    def _run_random(self, seed: str, subset: bool = True,
                    order: str = "random"):
        """走一次随机考试的准备流程(subset=True 勾子集,否则勾整份词表)。"""
        self.answers["order"] = order
        self.answers["seed"] = seed
        self.answers["volume"] = "sample"   # 子集范围才会问,答"只抽一部分"
        # 题量不再受 exam_size 影响(v1.15:"勾了什么就考完什么"),
        # 所以这个值只是"设置里恰好是几",不参与断言
        self.app.settings.study.exam_size = 4
        self.app.show("exam_pick")
        self.app.update()
        view = self.app.current_view
        wanted = self.subset.id if subset else self.vocab.id
        for key, var in view.pack_list._vars.items():
            var.set(key == wanted)
        view.on_action()
        self.app.update()
        return self.app.current_view.plan

    def test_declining_the_seed_keeps_only_the_chosen_words(self):
        """不加题时,考的就是勾中的那份词包**全部**。

        这一条以前断言 4 —— 那时题量由「每场考试题数」截断(v1.15 取消了:
        "勾了什么就考完什么")。现在勾 12 词的学习词包就是 12 题。
        """
        plan = self._run_random("none")
        self.assertEqual(len(plan.words), self.SUBSET)
        self.assertTrue(all(w.id.startswith("t_") for w in plan.words))

    def test_the_seed_question_is_only_asked_for_random_exams(self):
        self._run_random("none", order="sequential")
        asked = [title for title, _prompt in self.prompts]
        self.assertNotIn("随机考试", asked)

    def test_the_seed_question_is_not_asked_for_a_whole_vocab_pack(self):
        """**用户 2026-10-16 的要求**:整表范围时不显示、也不生效。

        整份单词表里已经包含那些错词了,再抽一遍就是同一个词考第二次。
        """
        plan = self._run_random("all", subset=False)
        asked = [title for title, _prompt in self.prompts]
        self.assertNotIn("随机考试", asked, "整表范围不该问加题")
        # 而且真的没多塞词:考的就是整份词表
        self.assertEqual(len(plan.words), len(self.words))

    def test_asking_for_the_seed_mentions_the_three_kinds(self):
        self._run_random("all")
        blob = "\n".join("%s\n%s" % pair for pair in self.prompts)
        self.assertIn("掌握", blob)
        self.assertIn("错题", blob)

    def test_the_seed_words_actually_land_in_the_plan(self):
        """这一条锁的是一个**静默**的 bug。

        第一版把"加题"写在 _adjust_plan 里,而那是**抽样之前**的钩子 ——
        加进来的词随即被 resample_for_exam 按题量砍掉了。用户点了"加入",
        结果一个都没进来,而且**不报任何错**。

        (题量截断在 v1.15 取消了,但这条测试仍然有价值:它锁的是
        "加题发生在抽样**之后**"这个顺序 —— 钩子挂错就又会静默丢弃。)

        前提是三档里都要有词可抽,所以这里单独造一份 18 词的词表、
        先考一场把三档各填 6 个,再勾一个 12 词的学习词包随机考一次。
        """
        self.app.packs.clear()
        self.app.words.clear()
        words = []
        for index in range(18):
            word = Word(id="s_%d" % index, spelling_key="s%d" % index,
                        word="s%d" % index, translation="释%d" % index)
            self.app.words[word.id] = word
            words.append(word)
        self.app.packs.append(make_vocab_pack("seed", "seed",
                                             [w.id for w in words], "2026-10-14"))

        self.app.settings.study.exam_size = 18
        self.take_exam(correct=6, fuzzy=6)   # 6 对 / 6 模糊 / 6 错
        summary = exam_group.summary_of(self.app.packs, "seed")
        self.assertTrue(all(count > 0 for count in summary.values()),
                        "三档没填满,后面的断言就不成立: %s" % summary)

        # 子集:只含前 12 个词的学习词包
        self.words = words
        self.subset = WordPack(id="sub2", pack_type=PACK_TYPE_STUDY,
                               title="子集", created_at="2026-10-16",
                               word_ids=[w.id for w in words[:12]],
                               source_vocab="seed")
        self.app.packs.append(self.subset)
        self.vocab = self.app.packs[0]

        without = len(self._run_random("none").words)
        with_seed = len(self._run_random("all").words)
        self.assertGreater(with_seed, without, "加进来的考试词被 exam_size 砍掉了")

    def test_the_seed_never_duplicates_a_word_already_in_the_exam(self):
        """同一个词在一场里考两次等于多扣一次分。"""
        plan = self._run_random("all")
        ids = [word.id for word in plan.words]
        self.assertEqual(len(ids), len(set(ids)))

    def test_adding_seed_words_does_not_change_the_summary_of_the_word_lists(self):
        """加题是往**这一场**里加,不改任何词包里的词。

        (考试结果包**会**变 —— 考完当然要更新掌握/模糊/错题,
        所以这里比的是"每个包里的词",只看词清单不看结果。)
        """
        before = {pack.id: list(pack.word_ids) for pack in self.app.packs}
        self._run_random("all")
        # 只比"用户勾的那些包里,除了考试结果包之外"的部分
        for pack in self.app.packs:
            if pack.id in before and not is_exam_pack(pack):
                self.assertEqual(before[pack.id], pack.word_ids,
                                 "%s 的词被加题改动了" % pack.title)


if __name__ == "__main__":
    unittest.main()
