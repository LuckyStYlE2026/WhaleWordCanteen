# -*- coding: utf-8 -*-
"""开始学习:勾词包(顶部还有按词表包拆开的「今日复习」),进入学习模式。

「今日复习」以前是页面上一个独立的按钮,现在拆成**一行一个词表包** ——
用户想看的正是"今天该复习哪几个词表",而不是一个跨全库的总数。
拆开之后模型也统一了:能学的都是"一批词",勾在一起还能合成一场会话。

这些行**不落盘**:它们是当场按到期时间算出来的,不是存档里的词包,所以
进不了 checked_packs(见 lists.PackCheckList.fill 的说明)。

**只为词表包(vocab)出到期行。** 结果包(study/exam)的 word_ids 基本是
某个词表包的子集,给它们也出行的话,同一批词会以「今日复习 · 2026-10-12
学习词包」这种名字再出现一遍,读起来更乱而不是更清楚。

**起点在点「开始学习」时选。** 恰好勾中一个词表包时,发车前会弹出一个
**看着单词列表挑起点**的窗口(见 ui/study_start):整包的词摆成一张只读的
表,带搜索,选中哪行就从哪个词开始。不弹"从第()个开始"的输入框 ——
用户不知道第 347 个是什么词,让用户填一个看不见的数字等于让他猜。
"""

from core.exam_group import is_reviewable
from core.packs import PACK_TYPE_VOCAB

from ..session import (
    MODE_STUDY,
    plan_from_pack_range,
    plan_from_packs,
    plan_from_parts,
    words_from_packs,
)
from ..study_start import ask_start_point
from .pack_pick import PackPickView

# 置顶行的勾选 key = 前缀 + 词包 id。词包 id 长成 pack_20261012_001,
# 加了前缀之后不会和任何真词包的 id 撞上(checked_packs 是按 id 匹配的),
# 于是"置顶行"和"真词包"在同一个勾选状态里也不会互相误伤。
DUE_PREFIX = "due:"
DUE_OTHER_KEY = "due:__other__"


def due_key(pack_id: str) -> str:
    """某个词表包「今日复习」那一行的勾选 key。"""
    return DUE_PREFIX + pack_id


class StudyPickView(PackPickView):
    """选词包开始学习。"""

    title_text = "开始学习"
    subtitle_text = "挑词包,按顺序一篇篇背过去"
    picker_hint = "勾选要学的词包,然后点「开始学习」。"
    mode = MODE_STUDY
    action_text = "开始学习"

    # ---- 今日复习 --------------------------------------------------------

    def _due_words(self):
        """今天到期的词,**不限数量**。

        行上要显示真实的到期数 —— 限了量的数字会让用户以为自己就欠这么
        多。真正的截断在发车时做(见 _due_selection),底部那句灰字负责
        说明当前上限。
        """
        return self.app.scheduler.due_words(self.app.words, self.app.today(), 0)

    def _due_by_pack(self, due):
        """把到期词摊到各词表包上,返回 ([(词包, 词...)], 不属于任何词表包的词)。

        一个词同属两个词表包时**两处都出现** —— 两个包都真的需要复习它,
        藏掉一个只会让某个包看起来"已经复习过了"。发车时按 id 去重
        (plan_from_parts → merge_words),不会真的学两遍。

        **只给"该复习的包"出到期行**(`is_reviewable`)。
        考试结果包不参与:它的词和词表包里的词是同一个对象,该复习的会被
        词表包排上;再给它排一遍,同一个词会在「今日复习」里出现两次,
        复习量虚高 —— 用户 2026-10-14 明确要求剔除。
        """
        by_id = dict((word.id, word) for word in due)
        groups = []
        claimed = set()
        for pack in self.app.packs:
            if not is_reviewable(pack):
                continue
            hits = [by_id[word_id] for word_id in pack.word_ids if word_id in by_id]
            if not hits:
                continue
            groups.append((pack, hits))
            claimed.update(word.id for word in hits)
        # 兜底:词表包被删了、结果包还留着它的时候,这些词也得有地方去
        orphans = [word for word in due if word.id not in claimed]
        return groups, orphans

    def leading_rows(self):
        groups, orphans = self._due_by_pack(self._due_words())
        rows = [(due_key(pack.id), pack.title, "%d 个词 · 今天到期" % len(hits))
                for pack, hits in groups]
        if orphans:
            rows.append((DUE_OTHER_KEY, "其他词", "%d 个词 · 今天到期" % len(orphans)))
        return rows

    def leading_title(self) -> str:
        """一行到期都没有时,整个「今日复习」分区不出现。

        这和 v1.2 的"显示一行 0 个词"不同:勾一个 0 个词的行点「开始学习」,
        只会得到一句"没有可用的单词"。
        """
        return "今日复习" if self.leading_rows() else ""

    def footer_hint(self) -> str:
        limit = self.app.settings.study.daily_due_limit
        if limit <= 0 or not self._due_words():
            return ""
        return "每天最多复习 %d 个词(可在设置里改)" % limit

    # ---- 计划 ------------------------------------------------------------

    def _due_selection(self, picks):
        """勾中的那几行到期词,合并去重,再按设置里的上限截断。

        顺序取自 due_words(逾期最久的排最前),所以截断留下的是最该先
        复习的那几个 —— 这一刀是有意义的,不是随便砍。
        """
        due = self._due_words()
        groups, orphans = self._due_by_pack(due)
        wanted = set()
        for pack, hits in groups:
            if due_key(pack.id) in picks:
                wanted.update(word.id for word in hits)
        if DUE_OTHER_KEY in picks:
            wanted.update(word.id for word in orphans)

        picked = [word for word in due if word.id in wanted]
        limit = self.app.settings.study.daily_due_limit
        if limit > 0:
            picked = picked[:limit]
        return picked

    def _make_plan(self):
        checked = self.pack_list.checked_ids()
        picks = [key for key in checked if key.startswith(DUE_PREFIX)]

        parts = []
        if picks:
            parts.append(("今日复习", self._due_selection(picks)))
        packs = self.pack_list.checked_packs()

        # 只勾了词包时走 plan_from_packs:单勾一个词包它会填上 pack_id,
        # 而「从哪开始学」和学习结束时记来源都要用这个 id。
        if not parts:
            return plan_from_packs(packs, self.app.words, MODE_STUDY)

        for pack in packs:
            parts.append((pack.title, words_from_packs([pack], self.app.words)))
        return plan_from_parts(parts, MODE_STUDY)

    def _adjust_plan(self, plan):
        """恰好勾中一个词表包时,发车前问一句"从哪开始学"。

        问的窗口在 ui/study_start:整包的词摆成一张只读的表,带搜索,
        选中哪行就从哪个词开始。多包 / 跨来源(今日复习)的会话不问:
        那种会话根本没有"第几个"这个坐标 —— 几包词混在一起,"第 347 个"
        算谁的?结果包也不问,它的进度不参与"接着上次"
        (见 study.py 的 _note_progress)。
        """
        pack = plan.pack
        if not plan.pack_id or pack is None:
            return plan
        if pack.pack_type != PACK_TYPE_VOCAB:
            return plan
        chosen = ask_start_point(self, self.theme, pack,
                                 self.app.settings.study.batch_size,
                                 self.app.words)
        if chosen is None:
            return None                 # 用户取消了 —— 留在挑词页
        start, count = chosen
        return plan_from_pack_range(pack, self.app.words, MODE_STUDY, start, count)
