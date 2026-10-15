# -*- coding: utf-8 -*-
"""考试页左边那块「刚才发生了什么」记录面板。

从 ui/views/exam.py 拆出来,理由是那块页面已经超过项目 300 行的体积约定,
而这块面板是**自成一体的一个小单元**:一个可开合的框 + 一个按钮文字同步。

## 为什么要"默认隐藏 + 按钮开合"

考试时这块面板白占着左边的画面,而答题的人并不需要一直看着它;
想回看"我上一题答了什么"再调出来就够了(用户要求)。

## 为什么按钮是「刚才发生了什么」而不是「问老师」

考试时不该引导用户去找老师聊天 —— 想聊天的人会直接点画面上的 AI 形象,
那才是谈天的入口(见 ui/views/base.on_character_click)。

注意:拆掉「问老师」按钮**不影响**"把问题打进输入框"这条路。
那条路在 ExamView.on_submit 里靠 core.lines.is_question 判断,
和这里的按钮没有关系。
"""

import tkinter as tk

from .panels import DialogueLog
from .widgets import theme_color

# 面板的位置(相对整个页面)。和学习页一样靠 place,不是 pack ——
# 它是浮在场景上的,不参与页面的流式布局。
PANEL_BOX = (0.03, 0.30, 0.27, 0.34)

TITLE = "刚才发生了什么"
OPEN_TEXT = "收起记录"
CLOSED_TEXT = TITLE


class ExamLog:
    """那块记录面板 + 它现在算开还是关。

    面板**一直存在**,关的时候只是不 place —— 隐藏期间 append 照常往里记,
    所以拉出来能看到完整历史,不会丢掉隐藏那段时间的内容。
    """

    def __init__(self, parent: tk.Misc, theme) -> None:
        self.theme = theme
        self.visible = False
        self.holder = tk.Frame(
            parent, bg=theme_color(theme, "panel"), highlightthickness=1,
            highlightbackground=theme_color(theme, "panel_light"))
        # 注意:这里**不** place。开合由 show / hide 负责。
        tk.Label(self.holder, text=TITLE, bg=theme_color(theme, "panel"),
                 fg=theme_color(theme, "text_dim"),
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=8,
                                                      pady=(6, 0))
        self.log = DialogueLog(self.holder, theme, height=8)
        self.log.pack(fill="both", expand=True, padx=6, pady=6)

    # ---- 内容 ------------------------------------------------------------

    def append(self, speaker: str, line: str) -> None:
        """记一笔。**关着的时候也照记** —— 那是这个设计成立的前提。"""
        self.log.append(speaker, line)

    def clear(self) -> None:
        self.log.clear()

    # ---- 开合 ------------------------------------------------------------

    def toggle(self) -> None:
        self.hide() if self.visible else self.show()

    def show(self) -> None:
        self.visible = True
        left, top, width, height = PANEL_BOX
        self.holder.place(relx=left, rely=top, relwidth=width, relheight=height)
        # 拉出来的时候要盖在场景上;不 lift 会被后画的层压住
        self.holder.lift()

    def hide(self) -> None:
        self.visible = False
        # place_forget 只是不再摆放,控件和里面的文字都留着
        self.holder.place_forget()

    def button_text(self) -> str:
        """按钮该写什么。

        文字要说明"按下去会怎样",否则用户不知道现在算开还是关。
        """
        return OPEN_TEXT if self.visible else CLOSED_TEXT
