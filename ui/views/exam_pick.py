# -*- coding: utf-8 -*-
"""进行考试:勾词包 → 确认词量与顺序(随机时可选"加考试词")→ 开考。

发车前有两件事要做,都在这里:

1. **词量提醒** —— 超过 `LARGE_PACK_WORDS` 就先确认一句。这是个
   **纯确认**(是非题),不改变题量:100 个词确实是一次很长的考试,
   值得先打个招呼。
2. **顺序** —— 顺序考试 / 随机考试。随机**不改编外面的词包**
   (见 ui/session.shuffle_plan)。
3. **加考试词**(只在选了随机、且勾的是**子集**时) —— 从这份词表已有的
   三个考试包里按 3 : 4 : 5 抽一批混进来。

## 题量:勾了什么就考完什么

**没有任何截断。** 勾一份 30 词的学习词包就考 30 题,勾 100 词的单词表就考
100 题。「每场考试题数」这个设置**不影响考试题量**。

> 这一条被来回改过三次,记下结论免得再绕:早先一律按「每场考试题数」截断,
> 于是 30 词的词包考 20 题、剩 10 个词永远考不到(没有"继续考"的机制);
> 中间我试过"按范围给不同默认值",结果**把范围和题量搅在了一起** ——
> 学习词包被当成"子集"又挨一刀,你说得对:别弄混词包和词表。
> 现在的规则只有一句:**勾中的那个词包/词表里的全部词。**

结果落到"来源单词表"名下的三个固定包,见 core/exam_group.py。
列表里把同一份单词表的三档排在一起,让人看得出它们是一组。
"""

from core.exam_group import is_exam_pack
from core.packs import PACK_TYPE_STUDY, PACK_TYPE_VOCAB

from .. import dialogs
from ..prompts import ask_choice
from ..session import MODE_EXAM, ORDER_RANDOM, ORDER_SEQUENTIAL, SessionPlan
from .. import exam_target
from .. import exam_pick_text as text
from ..exam_pick_text import LARGE_PACK_WORDS
from .pack_pick import PackPickView


class ExamPickView(PackPickView):
    """选词包进行考试。"""

    title_text = "进行考试"
    subtitle_text = "挑词包,确认顺序后开始"
    picker_hint = ("勾选要考的词包,然后点「开始考试」——下一步会让你确认"
                   "出题顺序。")
    mode = MODE_EXAM
    action_text = "开始考试"

    # ---- 发车前的确认 ---------------------------------------------------

    def _adjust_plan(self, plan: SessionPlan):
        """发车前两件事:词量极大时确认一句,然后问出题顺序。

        取消任一步都返回 None(不发车)。用户已经看到确认框了,所以取消时
        **不再**弹第二个框说"你取消了" —— 那个框本身已经把话说完。

        ⚠️ **这里只管"确认"和"顺序",不改题量。** 题量永远是"勾中的那个
        词包/词表里的全部词" —— 见 _sample_size()。

        这一版之前这里还有一层"考全部 / 只抽一部分"的选择,那是我把
        **范围**和**题量**搅在一起了:勾了一个 30 词的学习词包,它被当成
        "子集",于是又被「每场考试题数」(20)砍了一刀,剩下 10 个词永远
        考不到(用户 2026-10-17 报的正是这个)。**勾了什么就考完什么。**
        """
        if not self._confirm_volume(plan):
            return None
        order = self._ask_order(plan)
        if order is None:
            return None
        plan.order = order
        return plan

    def _sample_size(self) -> int:
        """这一场考多少个词:**勾中的词包/词表里的全部**(0 = 全部)。

        不做任何截断 —— 截断就是"考不完",而用户要的是考完。
        「每场考试题数」那个设置因此不再影响考试题量(它只用来决定
        "随机加考试词"加多少个,见 ui/views/exam_seed_flow.py)。
        """
        return 0

    def _confirm_volume(self, plan: SessionPlan) -> bool:
        """词包很大时先确认一句。返回 False 表示用户不想考了。

        这是一个**纯确认**(是非题),不改变题量。

        阈值以上的词包确实是一次很长的考试,值得先打个招呼
        (用户 2026-10-16 要求保留这一问)。
        """
        total = len(plan.words)
        if total <= LARGE_PACK_WORDS:
            return True
        # ⚠️ 走 `dialogs.confirm(...)` 而不是 `from ..dialogs import confirm`。
        # 直接 import 名字的话这里拿到的是"当时那个函数对象",测试(以及将来
        # 任何替换对话框的地方)改 `ui.dialogs.confirm` 影响不到它 ——
        # 于是测试里弹出**真弹窗**,而 Tk 的模态框在等一个永远不会来的点击,
        # 表现是"测试跑不完"而不是"测试失败",最难查。
        # 同一个坑在 ui/views/exam_seed_flow.py 里也记了一遍。
        return dialogs.confirm(self, "词量提醒", text.volume_prompt(total))

    def _pack_is_whole_table(self, plan: SessionPlan) -> bool:
        """勾中的那个包**就是一份单词表**吗。

        是 → 用户选的是整张表;不是(学习词包 / 考试包)→ 只是表里的一部分。
        """
        return (plan.pack is not None
                and plan.pack.pack_type == PACK_TYPE_VOCAB)

    def _covers_everything(self, plan: SessionPlan) -> bool:
        """这一场是不是**把整份单词表都考了** —— 也就是错词已经在范围里。

        **只有勾整份单词表才算。** 别的都不算,包括学习词包。

        ⚠️ 学习词包**不是**整表:它只是这份表里**今天学的那几个词**。
        例如一份 18 词的词表、今天学了 6 个 —— 勾这个学习词包时,另外 12 个词
        (包括以前的错题)都**不在这一场里**,所以"要不要把考试词包里的词也
        抽进来考"是有意义的。

        (上一版我把这个判断写成了"单词表**或**学习词包都算整表",于是勾学习
        词包时加题那一问**再也不会出现** —— 而且不报错,只是那个选项静默消失。
        用户 2026-10-16 的要求其实只针对**整表**:那时错词确实已经在范围里,
        再抽一遍是把同一个词考第二次。)

        这个判断只用来决定"随机加考试词"那一问要不要出现。
        """
        return self._pack_is_whole_table(plan)

    def _after_sample(self, plan: SessionPlan):
        """抽样之后:随机考试时可以再补一批考试词。

        ⚠️ **必须挂在"抽样之后"这个钩子上。** 第一版写在 _adjust_plan 里,
        于是加进来的词随即被 resample_for_exam 按题量砍掉了 ——
        用户点了"加入",结果一个都没进来,而且**不报任何错**。
        见 ui/views/pack_pick.py 里两个钩子的分工说明。
        """
        if plan.order != ORDER_RANDOM:
            return plan
        if not self._add_exam_words(plan):
            return None
        return plan

    def _ask_order(self, plan: SessionPlan) -> str:
        """二次确认:顺序还是随机。取消返回 None。"""
        return ask_choice(
            self, self.theme, "确认考试", self._order_prompt(plan),
            text.ORDER_OPTIONS, initial=ORDER_SEQUENTIAL)

    def _order_prompt(self, plan: SessionPlan) -> str:
        """确认框里那句说明。把"要考多少、来自哪里"写清楚。

        题量就是**勾中的词包里的全部词**,所以这句话是"你要考的完整范围",
        不会有"点进去才发现少了"的情况。
        """
        parts = ["这次要考 %d 个词" % len(plan.words)]
        if plan.title:
            parts.append("来自「%s」" % plan.title)
        parts.append("请选择出题顺序:")
        return "\n".join(parts)

    # ---- 随机考试的"加题"子选项 -------------------------------------------
    #
    # 整表范围时不问也不加:错词本来就在范围里,再抽一遍是把同一个词考第二次。
    # 这一支的实现在 ui/views/exam_seed_flow.py。

    def _add_exam_words(self, plan: SessionPlan) -> bool:
        """问一句要不要加考试词;返回 False 表示用户取消了(不发车)。"""
        if self._covers_everything(plan):
            return True
        vocab_id = self._plan_vocab(plan)
        if not vocab_id:
            return True
        from .exam_seed_flow import ask_and_mix
        return ask_and_mix(self, plan, vocab_id,
                           self._exam_word_count(vocab_id),
                           self._exam_summary(vocab_id))

    def _exam_word_count(self, vocab_id: str) -> int:
        return exam_target.exam_word_total(self.app.packs, vocab_id)

    def _exam_summary(self, vocab_id: str) -> str:
        from core.exam_group import summary_text
        return summary_text(self.app.packs, vocab_id) or "(还没有)"

    # ---- 计划 ------------------------------------------------------------

    def _plan_vocab(self, plan: SessionPlan) -> str:
        """这一场考的词属于哪份单词表。

        和考试页收尾时**必须是同一个答案**,所以实现放在 ui/exam_target.py,
        两处都调它 —— 各写一份的话,"加进来的词"和"结果落到哪"迟早会
        指向不同的词表,而且不报错。
        """
        return exam_target.plan_vocab_id(plan, self.app.packs)

    def _plan_title(self, plan: SessionPlan) -> str:
        # "甲词包 等 2 个词包"这种自动标题在考试语境下不够清楚,
        # 一律写成"词包考试" —— 用户看的是题目,不是标题里的词包名
        return "词包考试"

    # ---- 列表:把同一份单词表的三档排在一起 --------------------------------

    def _pack_groups(self):
        """结果那一组里,把同一份单词表的三个考试包排在一起显示。

        分组感是靠**相邻**给的,不必真做嵌套(见 core/exam_group.py 开头)。
        排一下之后「sample考试·掌握 / 模糊 / 错题」永远连在一起。
        """
        groups = super()._pack_groups()
        reordered = []
        for title, packs in groups:
            if title == RESULT_SECTION:
                reordered.append((title, text.cluster_by_vocab(packs)))
            else:
                reordered.append((title, packs))
        return reordered

    def _pack_subtitle(self, pack) -> str:
        """三档的小字写成「sample 的考试结果 · 12 个词」。

        标题里已经带着单词表名了,这里补的是"它是结果而不是材料"这件事 ——
        用户看到三个「某某考试·」的包时,需要知道它们是同一份词表的三档。
        """
        if not is_exam_pack(pack):
            return super()._pack_subtitle(pack)
        vocab = self._vocab_name(pack.group_id)
        return "%s 的考试结果 · %d 个词" % (vocab, pack.word_count)

    def _vocab_name(self, vocab_id: str) -> str:
        for pack in self.app.packs:
            if pack.id == vocab_id:
                return pack.title
        return vocab_id

    def describe_pack(self, pack) -> str:
        """列表里那一行的文字。考试包直接用标题(已自带词表名 + 档位)。"""
        return pack.title


# 「学习/考试结果」那个分区的标题(和 pack_pick._pack_groups 里写的一致)。
RESULT_SECTION = "学习/考试结果"
