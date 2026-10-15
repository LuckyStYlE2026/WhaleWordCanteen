# -*- coding: utf-8 -*-
"""二级挑选页:选定一个词包组合,然后发车。

「开始学习」和「进行考试」是同一件事的两个模式 —— 都是"勾几个词包,
点一下开始"。所以骨架放在这里,两个叶子页面只提供文案和各自的额外入口。

**为什么是两条注册名而不是一条带参数的页面?** 因为换主题时 App 是
`show(当前页名)` **不带任何参数**地重进这一页(见 ui/app.py 的 apply_theme)。
如果两个模式共用一个页面、靠 on_enter 的参数区分,换一次主题考试页就会
静默变成学习页。用类属性定模式,这件事从结构上就不可能发生。

**发车只有一个口**:_finish_plan。考试模式的抽样也只在这里发生一次,
而且调用的是 ui/session.resample_for_exam —— 全工程唯一碰 weighted_sample
的地方。以前"随机考试"在构造计划时抽一遍、这里又抽一遍,第二次因为
池子已经缩到题量、走的只是打乱顺序的分支,第一次的加权白算了。
"""

import tkinter as tk

from core.packs import PACK_TYPE_VOCAB

from ..dialogs import info
from ..forms import flat_button
from ..lists import PackCheckList
from ..session import (
    MODE_STUDY,
    SessionPlan,
    plan_from_packs,
    resample_for_exam,
    target_view,
)
from ..widgets import primary_button, theme_color
from .base import View


class PlanEntriesMixin:
    """"选词 → 发车"这一套操作,任何页面都能挂上。

    刻意不定义 __init__:这样子类里 View.__init__ 照常跑、照样调 build()。
    """

    def _finish_plan(self, plan: SessionPlan) -> None:
        """把计划送进对应的板块。全工程唯一的发车口。"""
        if not plan.words:
            info(self, "无法开始", "选中的词包里没有可用的单词。")
            return

        # 先让子类调整计划(学习页要在这里问"从第几个开始"并切片),
        # **必须在抽样之前** —— 切片是"这一轮学哪一段",抽样是"从那一段
        # 里抽几道题",顺序反了就会拿一段还没选好的词去抽。
        plan = self._adjust_plan(plan)
        if plan is None:
            return                     # 子类已经处理完(取消 / 已给出提示)

        # 题量由 _sample_size() 决定:考试页返回 0 = **勾中的全部词**
        # (勾了什么就考完什么,不做截断);学习页不抽样,原样返回。
        # 顺序由 plan.order 决定:顺序考试保持原顺序,随机考试才打乱/加权抽。
        plan = resample_for_exam(plan, self._sample_size())

        plan = self._after_sample(plan)
        if plan is None:
            return

        self.app.show(target_view(plan), plan=plan)

    def _sample_size(self) -> int:
        """这一场取多少个词。0 表示"全都要"。

        默认 0 —— 勾中的范围就是要处理的全部内容。子类可以覆盖。
        """
        return 0

    def _adjust_plan(self, plan: SessionPlan):
        """**抽样之前**的调整机会。默认原样返回;返回 None 表示"别发车"。

        返回 None 时**必须**自己给出提示 —— 用户按了按钮却什么都没发生
        是最让人困惑的一种表现。
        """
        return plan

    def _after_sample(self, plan: SessionPlan):
        """**抽样之后**的调整机会(默认原样返回;返回 None = 别发车)。

        为什么需要第二个钩子:有些调整必须在"题量已经定下来"之后做。

        > 这一版真踩过:考试页的"随机加入考试词包"原本写在 _adjust_plan 里,
        > 于是加进来的词随即被 resample_for_exam 按 exam_size 砍掉了 ——
        > 用户点了"加入",结果一个都没进来,而且不报任何错。
        >
        > 两个钩子的分工是:**抽样前**决定"从哪个池子里考多少"
        > (学习页的切片、考试页的顺序),"抽样后"决定"在这一场里再补什么"。
        """
        return plan


class PackPickView(PlanEntriesMixin, View):
    """二级挑选页的骨架。子类覆盖下面这几个类属性即可。"""

    # 子类覆盖。mode 决定发车去哪个板块,不是靠 on_enter 传参 —— 见模块开头。
    mode = MODE_STUDY
    action_text = "开始"
    picker_hint = ""

    def build(self) -> None:
        # 二级页的「返回」回一级页,不是回主菜单。这个按钮曾经整个漏掉过:
        # header 只在 back=True 时才画返回键(见 base.header),而这里传的是
        # back=False,on_back 成了一个没人调用的死参数 —— 挑词页于是
        # 进得来、出不去,只能从主菜单绕路。
        self.header(self, back=True, on_back=self._back_to_pick)
        body = tk.Frame(self, bg=theme_color(self.theme, "background"))
        body.pack(fill="both", expand=True, padx=24, pady=(0, 18))

        self._build_packs(body)
        self._build_footer(body)
        self.refresh()

    def _back_to_pick(self) -> None:
        self.app.show("start")

    def on_escape(self) -> bool:
        """Esc 在挑词页也是"回上一级",和学习/考试页的语义接成一条线
        (分发见 ui/app.py):从主菜单进来,一路按 Esc 就能原路退回去。"""
        self._back_to_pick()
        return True

    # ---- 界面 ------------------------------------------------------------

    def _build_packs(self, parent: tk.Misc) -> None:
        tk.Label(parent, text="词包", bg=theme_color(self.theme, "background"),
                 fg=theme_color(self.theme, "text"),
                 font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w", pady=(6, 2))
        tk.Label(parent, text=self.picker_hint,
                 bg=theme_color(self.theme, "background"),
                 fg=theme_color(self.theme, "text_dim"),
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w")

        self.pack_list = PackCheckList(parent, self.theme, height=9)
        self.pack_list.pack(fill="both", expand=True, pady=(8, 8))

    def _build_footer(self, parent: tk.Misc) -> None:
        bar = tk.Frame(parent, bg=theme_color(self.theme, "background"))
        bar.pack(fill="x")

        primary_button(bar, self.action_text, self.on_action,
                       self.theme).pack(side="left")
        flat_button(bar, self.theme, "全选",
                    lambda: self.pack_list.check_all(True)).pack(side="left", padx=8)
        flat_button(bar, self.theme, "全不选",
                    lambda: self.pack_list.check_all(False)).pack(side="left")
        self._build_extra(bar)

        hint = self.footer_hint()
        if hint:
            tk.Label(bar, text=hint, bg=theme_color(self.theme, "background"),
                     fg=theme_color(self.theme, "text_dim"),
                     font=("Microsoft YaHei UI", 9)).pack(side="right")

    def _build_extra(self, bar: tk.Misc) -> None:
        """子类往底部按钮行里加自己的入口。默认什么都不加。"""

    def footer_hint(self) -> str:
        """按钮行右边那句灰色小字。默认没有。"""
        return ""

    # ---- 数据 ------------------------------------------------------------

    def refresh(self) -> None:
        self.pack_list.fill(self._pack_groups(),
                            describe=self.describe_pack,
                            subtitle_of=self._pack_subtitle,
                            leading=self.leading_rows(),
                            leading_title=self.leading_title())

    def describe_pack(self, pack) -> str:
        """列表里那一行的文字。子类可以覆盖(考试页要把同一天的几档写清楚)。"""
        return pack.title

    def leading_rows(self):
        """列表最上面那几行伪条目 [(key, 标题, 说明), ...]。默认没有。"""
        return []

    def leading_title(self) -> str:
        """置顶行的分区标题。没有置顶行时不必给。"""
        return ""

    def _pack_groups(self):
        """把词包分成两组:用户导入的词表 vs 学习/考试结果。

        词表包是用户的资料,结果包是产物 —— 分开摆,用户才分得清
        「哪些是我自己的」「哪些是系统给我攒的」。勾选跨组,见
        PackCheckList.fill 的说明。

        两组**都列**,包括结果包:想重考一次刚错得多的那批词,
        直接从结果包发起是最自然的。
        """
        vocab, results = [], []
        for pack in self.app.packs:
            if pack.pack_type == PACK_TYPE_VOCAB:
                vocab.append(pack)
            else:
                results.append(pack)
        groups = []
        if vocab:
            groups.append(("我的词表", vocab))
        if results:
            groups.append(("学习/考试结果", results))
        return groups

    def _pack_subtitle(self, pack) -> str:
        """词包那一行小字:多少词、什么时候建的、建完有没有按时回来。"""
        parts = ["%d 个词" % pack.word_count, "建于 %s" % (pack.created_at or "未知")]
        if pack.schedule.recommended_next:
            parts.append("建议下次 %s" % pack.schedule.recommended_next)
        if pack.schedule.regularity == "overdue":
            parts.append("已经逾期较久,建议重新学一遍")
        return " · ".join(parts)

    # ---- 入口 ------------------------------------------------------------

    def _make_plan(self) -> SessionPlan:
        """把当前勾选变成一个计划。子类可以覆盖(学习页还要算上伪条目)。"""
        return plan_from_packs(self.pack_list.checked_packs(), self.app.words,
                               self.mode)

    def on_action(self) -> None:
        checked = self.pack_list.checked_ids()
        has_leading = any(key in checked
                          for key, _title, _subtitle in self.leading_rows())
        if not self.pack_list.checked_packs() and not has_leading:
            info(self, self.action_text, "先勾选至少一个词包。")
            return

        plan = self._make_plan()
        plan.title = self._plan_title(plan)
        self._finish_plan(plan)

    def _plan_title(self, plan: SessionPlan) -> str:
        return plan.title
