# -*- coding: utf-8 -*-
"""开始:先选一条路,再挑词包。

这一页放三张大卡片,对应三条路:
  开始学习 —— 用户挑词包,按顺序背过去;
  开始复习 —— 记忆曲线挑词,把今天到期的词拉回来重过一遍;
  进行考试 —— 用户挑词包,随机抽查检验。

「开始复习」单独成卡是 2026-10-12 用户反馈的结果:以前考试的抽样
会把"已毕业又没到期"的词整个滤掉,造成"想考却考不了";而该复习
什么本来就该由记忆曲线决定,不该考试替用户做主。现在考试考用户选
的,到期词走自己这条专门的复习路。

底部那行概况文字是个提示,不抢卡片的位置,但用户进门第一眼能看到。
"""

import tkinter as tk

from core.stats import summarize

from ..dialogs import info
from ..session import MODE_STUDY, plan_from_parts, target_view
from ..widgets import Card, theme_color
from .base import View

# (标题, 一句话说明, 目标板块)。"开始复习"不在里面 —— 它不挑词包,
# 说明文字还随当天到期数变,单独建卡片(见 build)。
CHOICES = [
    ("开始学习", "挑词包,按顺序一篇篇背过去", "study_pick"),
    ("进行考试", "挑词包,随机抽查检验", "exam_pick"),
]


class StartView(View):
    """一级挑选页:学习、复习,还是考试。"""

    title_text = "开始"
    subtitle_text = "先选一条路,再挑词包"

    def build(self) -> None:
        self.header(self)
        body = tk.Frame(self, bg=theme_color(self.theme, "background"))
        body.pack(fill="both", expand=True, padx=24, pady=(0, 18))
        # 三张卡片要等宽等高地把整块地方分掉,所以用 grid 而不是 pack ——
        # pack 做不到"几列各自平分剩余宽度"
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.columnconfigure(2, weight=1)
        body.rowconfigure(0, weight=1)

        # 复习卡放正中间:它和左右两条"用户挑词包"的路不是一种挑法
        self.review_card = Card(body, self.theme, "开始复习", "",
                                command=self._start_review)
        self.review_card.grid(row=0, column=1, sticky="nsew", padx=(10, 10))
        for index, (title, subtitle, target) in enumerate(CHOICES):
            self._add_choice(body, index * 2, title, subtitle, target)

        self.summary_label = tk.Label(
            body, text="", bg=theme_color(self.theme, "background"),
            fg=theme_color(self.theme, "accent"),
            font=("Microsoft YaHei UI", 11), anchor="w", justify="left")
        self.summary_label.grid(row=1, column=0, columnspan=3, sticky="w",
                                pady=(14, 0))
        self.refresh()

    def _add_choice(self, parent: tk.Misc, column: int, title: str,
                    subtitle: str, target: str) -> None:
        card = Card(parent, self.theme, title, subtitle,
                    command=lambda name=target: self.app.show(name))
        card.grid(row=0, column=column, sticky="nsew",
                  padx=(0, 10) if column == 0 else (10, 0))

    # ---- 发车 ------------------------------------------------------------

    def _start_review(self) -> None:
        """复习这条路不挑词包:到期词由记忆曲线替用户挑。

        到期的词本来就分散在各词包里,按到期时间跨包汇总
        (见 scheduler.due_words),所以这里没有"第二步挑词包"。
        """
        limit = self.app.settings.study.daily_due_limit
        due = self.app.scheduler.due_words(self.app.words, self.app.today(),
                                           limit)
        if not due:
            info(self, "开始复习",
                 "今天没有到期的词。学过的词到了复习日,这里就能直接开始。")
            return
        plan = plan_from_parts([("今日复习", due)], MODE_STUDY)
        self.app.show(target_view(plan), plan=plan)

    # ---- 数据 ------------------------------------------------------------

    def refresh(self) -> None:
        """复习卡片上的一句话 + 底部概况。

        复习卡的说明随当天到期数变,有没有到期词一眼可辨;
        底部小字只报库存概况,不重复"今天有 N 个词该复习" ——
        那句话已经写在复习卡上了,同一屏说两遍反而像两个不同的数。
        """
        summary = summarize(self.app.words, self.app.today())
        if summary.total == 0:
            self.review_card.subtitle_label.configure(text="词库还是空的")
            text = "词库还是空的,先去「单词设置」导入一份词表"
        else:
            if summary.due_today:
                self.review_card.subtitle_label.configure(
                    text="记忆曲线挑词:%d 个词今天到期" % summary.due_today)
            else:
                self.review_card.subtitle_label.configure(
                    text="今天没有到期的词")
            text = "共 %d 个词,已掌握 %d 个" % (summary.total, summary.known)
        self.summary_label.configure(text=text)
