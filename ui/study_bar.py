# -*- coding: utf-8 -*-
"""学习页的两条按钮行:顶部一条、底部一条。

**为什么分成两条**(用户提的):翻页那四个按钮是这一页用得最多的,
放在**底部中间**手最容易够到;而"返回 / 标记 / 隐藏老师"是低频动作,
留在顶部的两头。以前七个按钮挤在一行,常用的和不常用的混在一起,
反而不好按。

这一版还去掉了对话框,于是单词表一直伸到原来对话框的下沿 ——
底部那条按钮行就摆在这块拉长了的单词表下面。

语义(和上一版一致,没有变):

    上一组 · 下一组 · 跳过本组 · 结束学习

* **下一组** = 这一组我记住了(记 CORRECT、推进度)
* **上一组** = 回去看一眼,**不改任何状态**(和"下一组"不对称是故意的)
* **跳过本组** = 我还没准备好评价它(不记状态、不推进度)
* **结束学习** = 收尾(落结果包、推进度、回上一级)
"""

import tkinter as tk
from typing import Callable, List

from .theme import Theme
from .widgets import ghost_button, primary_button, theme_color

# 底部那条的按钮:(文字, 是不是主按钮)。
# 「下一组」是主按钮 —— 它是这一页 90% 的时间里要按的那一个。
PAGING_BUTTONS = (
    ("上一组", False),
    ("下一组", True),
    ("跳过本组", False),
    ("结束学习", False),
)


class StudyToolbar(tk.Frame):
    """**顶部**一条:「← 返回」在最左,「标记 / 隐藏老师」在最右。

    中间空着 —— 那是刻意的:返回和"调版面/盖个章"是两类动作,
    挤在一起容易误按。
    """

    def __init__(self, master: tk.Misc, theme: Theme,
                 on_back: Callable[[], None],
                 on_mark: Callable[[], None],
                 on_toggle_teacher: Callable[[], None]) -> None:
        super().__init__(master, bg=theme_color(theme, "background"))
        self.theme = theme

        ghost_button(self, "← 返回", on_back, theme).pack(side="left")

        self.teacher_button = ghost_button(self, "隐藏老师", on_toggle_teacher, theme)
        self.teacher_button.pack(side="right")
        self.mark_button = primary_button(self, "标记", on_mark, theme)
        self.mark_button.pack(side="right", padx=(0, 8))

    def set_teacher_visible(self, visible: bool) -> None:
        """按老师当前显不显示,把按钮文字切成对应动作。

        文字必须跟着状态走:写着「隐藏老师」却点了变显示,是最容易让人
        以为自己点错的一种反馈。
        """
        self.teacher_button.configure(text="隐藏老师" if visible else "显示老师")

    def set_mark_enabled(self, enabled: bool) -> None:
        """没有可标记的位置时(比如结果包没有"第几个"这个坐标)就灰掉。"""
        self.mark_button.configure(state="normal" if enabled else "disabled")


class StudyNavBar(tk.Frame):
    """**底部**一条:翻页与收尾,居中摆放。

    单独一个类而不是塞进顶部那条:两条行的生命周期和语义都不一样
    (一条是"调版面",一条是"往下学"),合在一起会让"这一页的按钮在哪"
    变成一件要靠读 pack 顺序才知道的事。
    """

    def __init__(self, master: tk.Misc, theme: Theme,
                 on_previous: Callable[[], None],
                 on_next: Callable[[], None],
                 on_skip: Callable[[], None],
                 on_finish: Callable[[], None]) -> None:
        super().__init__(master, bg=theme_color(theme, "background"))
        self.theme = theme
        commands = (on_previous, on_next, on_skip, on_finish)

        # 用 inner 居中:直接在 self 上 pack(side="left") 的话,
        # 按钮会靠左边排,而不是像要求那样摆在单词表下方**正中**。
        inner = tk.Frame(self, bg=theme_color(theme, "background"))
        inner.pack()
        for (text, primary), command in zip(PAGING_BUTTONS, commands):
            maker = primary_button if primary else ghost_button
            maker(inner, text, command, theme).pack(side="left", padx=6)


def toolbar_texts() -> List[str]:
    """顶部那条应有的文字。界面冒烟和测试从这里取,不另抄一份。"""
    return ["← 返回", "标记", "隐藏老师"]


def nav_texts() -> List[str]:
    """底部那条应有的文字。"""
    return [text for text, _primary in PAGING_BUTTONS]
