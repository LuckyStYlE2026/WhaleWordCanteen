# -*- coding: utf-8 -*-
"""学习页的单词卡片 —— **可滚动**的一屏词。

**为什么必须能滚。** 一个"组合"里的词数是用户导入词表时定的,可能有十几个。
学习页一屏放不下那么多卡片,而这一页**不能靠翻页看全一个组**:
「下一组」翻的是组,组内的词得在这一个屏里看全。所以列表必须能滚 ——
不然第 5 个词之后的都被挡在外面,而用户完全看不出那里还有内容。

**为什么单独一个文件。** 卡片的排版(词 + 音标一行、释义一行、例句与搭配)
和"第几组、标记在哪、老师显不显示"没有关系 —— 后者才是学习页要操心的。
配色由调用方通过 `palette` 传进来(见 ui/widgets.py 的 panel_palette):
卡片要跟着**底板**的底色走,底板可能是用户的图片,算过才知道该用深字还是浅字。
"""

import tkinter as tk
from typing import List

from .panels import ScrollFrame


def example_lines(word) -> List[str]:
    """例句和搭配那两行。两个都没有就返回空列表(卡片底部留一点空)。

    放在这里而不是 core:它决定的是"卡片上显示哪两行",是排版问题,
    不是单词模型的一部分。
    """
    lines = []
    if word.example:
        lines.append("例:%s" % word.example)
    if word.collocation:
        lines.append("搭配:%s" % word.collocation)
    return lines


class WordList(ScrollFrame):
    """一屏单词,放不下时可以滚。

    继承 ScrollFrame:它的 `body` 就是那个"可以无限高的内层容器",
    卡片往那里放,滚轮和滚动条它已经处理好了(包括切页时的解绑)。
    """

    def __init__(self, master: tk.Misc, palette: dict, theme, **kwargs) -> None:
        # 底色用**底板的颜色**(palette["surface"])而不是主题背景色 ——
        # 这一块坐在画进场景图的那层板上,用主题色会在浅色底板上露出一块
        # 突兀的深色方块(ScrollFrame 默认用的是主题背景色)。
        super().__init__(master, theme, bg=palette["surface"], **kwargs)
        self.palette = palette

    def render(self, words) -> None:
        """清空重画这一屏。"""
        for child in self.body.winfo_children():
            child.destroy()
        for word in words:
            self._add_card(word)
        self.to_top()

    def _add_card(self, word) -> None:
        palette = self.palette
        card_bg = palette["card"]

        # 卡片带一条描边:底板可以换成浅色的图,卡片和底板要分得开 ——
        # 描边是最省的解法,换底板图时也不必再调配色。
        card = tk.Frame(self.body, bg=card_bg, highlightthickness=1,
                        highlightbackground=palette["card_border"])
        card.pack(fill="x", pady=3)

        head = tk.Frame(card, bg=card_bg)
        head.pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(head, text=word.word, bg=card_bg, fg=palette["card_text"],
                 font=("Microsoft YaHei UI", 16, "bold")).pack(side="left")
        if word.phonetic:
            tk.Label(head, text=word.phonetic, bg=card_bg, fg=palette["card_dim"],
                     font=("Microsoft YaHei UI", 10)).pack(side="left", padx=10)

        # wraplength 给得宽:隐藏老师之后这一块会占满整个窗口,
        # 释义和例句都该跟着变宽,而不是挤在一条窄列里
        tk.Label(card, text=word.translation, bg=card_bg, fg=palette["card_accent"],
                 font=("Microsoft YaHei UI", 11), anchor="w", justify="left",
                 wraplength=900).pack(fill="x", padx=12, pady=(2, 0))

        extras = example_lines(word)
        if extras:
            tk.Label(card, text="\n".join(extras), bg=card_bg, fg=palette["card_dim"],
                     font=("Microsoft YaHei UI", 9), anchor="w", justify="left",
                     wraplength=900).pack(fill="x", padx=12, pady=(2, 8))
        else:
            tk.Frame(card, bg=card_bg, height=8).pack()

    def to_top(self) -> None:
        """滚回最上面。翻到新的一组时也调它。

        不调的话,从"第 3 组"翻到"第 4 组"时视图还停在上一组滚到的位置,
        用户会以为翻页没生效(新一组的前几个词被滚过头了)。
        """
        try:
            self.canvas.yview_moveto(0.0)
        except tk.TclError:
            pass
