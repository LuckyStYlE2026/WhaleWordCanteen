# -*- coding: utf-8 -*-
"""小问答弹窗:要一行文字,或者要用户在几个选项里挑一个。

和 dialogs.py 的分工:那边是"编辑一个对象"的重窗口(单词、人设),
这边是"回答一个问题"的轻窗口 —— 问完即走,不进任何列表。

做成自己的弹窗而不是用 messagebox,是因为 messagebox 只能给你
"确定/取消"两个按钮、而且按钮文字是 Windows 定的,改不了。
要一行输入、要在三个格式里挑一个,messagebox 都做不到。

从 dialogs.py 拆出来的直接原因:加上"选格式"之后那个文件要过 300 行,
而这两类东西本来就不是一回事 —— 重窗口会随字段增减改版,轻窗口不会。
"""

import tkinter as tk
from typing import List, Optional, Tuple

from .dialogs import center_on, owner_window
from .theme import Theme
from .widgets import ghost_button, primary_button, theme_color

# 选项的形式:(显示给用户看的文字, 程序内部用的值)。
# 两者分开,是为了让界面可以写中文而内部仍然用英文名(见 CLAUDE.md 的命名约定)。
Choice = Tuple[str, str]


def ask_text(parent: tk.Misc, theme: Theme, title: str,
             prompt: str, initial: str = "") -> Optional[str]:
    """要一行文字。用带输入框的小弹窗,而不是 messagebox 那种
    "先让你点确定再让你输入"的两步流程。"""
    dialog = TextPrompt(parent, theme, title, prompt, initial)
    parent.wait_window(dialog)
    return dialog.result


def ask_choice(parent: tk.Misc, theme: Theme, title: str, prompt: str,
               options: List[Choice], initial: str = "") -> Optional[str]:
    """让用户在几个选项里挑一个。取消返回 None。

    options 为空时返回 None —— 调用方拿到的永远是"一个合法的值"或"用户放弃了",
    不需要再去分辨"空选项"这种第三种情况。
    """
    if not options:
        return None
    dialog = ChoicePrompt(parent, theme, title, prompt, options, initial)
    parent.wait_window(dialog)
    return dialog.result


def ask_text_block(parent: tk.Misc, theme: Theme, title: str,
                   prompt: str, initial: str = "") -> Optional[str]:
    """要一大段多行文本。给"粘贴词表建包"用。取消返回 None。"""
    dialog = TextBlockPrompt(parent, theme, title, prompt, initial)
    parent.wait_window(dialog)
    return dialog.result


class _PromptBase(tk.Toplevel):
    """两种小弹窗共用的骨架:模态、居中、Esc 取消。

    共用的部分就这三件事,所以基类只做这三件事 ——
    内容由子类自己摆,免得基类长成一个"什么都能装"的万能窗口。
    """

    def __init__(self, master: tk.Misc, theme: Theme, title: str) -> None:
        super().__init__(master)
        self.theme = theme
        self.result: Optional[str] = None

        self.title(title)
        self.configure(bg=theme_color(theme, "background"))
        self.resizable(False, False)
        self.panel = tk.Frame(self, bg=theme_color(theme, "panel"))
        self.panel.pack(fill="both", expand=True, padx=14, pady=14)

        self.bind("<Escape>", lambda _e: self.destroy())
        # 必须等控件摆完才知道窗口该多大,所以居中推迟到 idle
        self.after_idle(lambda: center_on(self, master))

    def _question(self, prompt: str) -> None:
        """摆问题文字。子类要先调它,再摆自己的内容 —— 内容必须夹在
        问题与按钮之间,不然会出现"输入框在问题上面"这种读起来别扭的版面。"""
        tk.Label(self.panel, text=prompt, bg=theme_color(self.theme, "panel"),
                 fg=theme_color(self.theme, "text"), justify="left",
                 wraplength=420,
                 font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=14,
                                                       pady=(12, 6))

    def _buttons(self, master: tk.Misc, enter_to_ok: bool = True) -> None:
        """摆按钮行,并把窗口变成模态。子类摆完内容的最后一步。

        enter_to_ok=False 给多行文本框用:那里回车是换行,不该触发确定。
        """
        buttons = tk.Frame(self.panel, bg=theme_color(self.theme, "panel"))
        buttons.pack(fill="x", padx=14, pady=12)
        primary_button(buttons, "确定", self._on_ok, self.theme).pack(side="right")
        ghost_button(buttons, "取消", self.destroy, self.theme).pack(side="right",
                                                                     padx=8)

        self.transient(owner_window(master))
        self.grab_set()
        if enter_to_ok:
            self.bind("<Return>", lambda _e: self._on_ok())

    def _on_ok(self) -> None:
        self.destroy()


class TextPrompt(_PromptBase):
    """一行文字的小输入框。"""

    def __init__(self, master: tk.Misc, theme: Theme, title: str,
                 prompt: str, initial: str = "") -> None:
        super().__init__(master, theme, title)

        self._question(prompt)
        self.var = tk.StringVar(value=initial)
        entry = tk.Entry(self.panel, textvariable=self.var, width=36,
                         bg=theme_color(theme, "background"),
                         fg=theme_color(theme, "text"),
                         insertbackground=theme_color(theme, "text"),
                         relief="flat", bd=0, highlightthickness=1,
                         highlightbackground=theme_color(theme, "panel_light"),
                         highlightcolor=theme_color(theme, "accent"),
                         font=("Microsoft YaHei UI", 11))
        entry.pack(padx=14, ipady=5, fill="x")

        self._buttons(master)
        entry.focus_set()
        entry.select_range(0, "end")

    def _on_ok(self) -> None:
        self.result = self.var.get().strip()
        self.destroy()


class TextBlockPrompt(_PromptBase):
    """多行文本输入。给"粘贴一整段词表建包"用。

    回车在这里是换行,不是提交 —— 所以走 enter_to_ok=False,
    确定只能点按钮。否则用户在中文输入法里一回车,候选词没确认完
    反倒把整段没写完的文本提交了。
    """

    def __init__(self, master: tk.Misc, theme: Theme, title: str,
                 prompt: str, initial: str = "") -> None:
        super().__init__(master, theme, title)

        self._question(prompt)
        self.text = tk.Text(
            self.panel, width=54, height=16, wrap="word",
            bg=theme_color(theme, "background"),
            fg=theme_color(theme, "text"),
            insertbackground=theme_color(theme, "text"),
            relief="flat", bd=0, highlightthickness=1,
            highlightbackground=theme_color(theme, "panel_light"),
            highlightcolor=theme_color(theme, "accent"),
            font=("Microsoft YaHei UI", 11), padx=8, pady=6)
        self.text.pack(padx=14, fill="both", expand=True)
        if initial:
            self.text.insert("1.0", initial)

        self._buttons(master, enter_to_ok=False)
        self.text.focus_set()

    def _on_ok(self) -> None:
        self.result = self.text.get("1.0", "end").strip()
        self.destroy()


class ChoicePrompt(_PromptBase):
    """单选弹窗。一行一个选项,选中即返回它的内部值。"""

    def __init__(self, master: tk.Misc, theme: Theme, title: str, prompt: str,
                 options: List[Choice], initial: str = "") -> None:
        super().__init__(master, theme, title)

        self._question(prompt)
        self.var = tk.StringVar(value=initial or options[0][1])
        for label, value in options:
            tk.Radiobutton(
                self.panel, text=label, value=value, variable=self.var,
                bg=theme_color(theme, "panel"), fg=theme_color(theme, "text"),
                activebackground=theme_color(theme, "panel"),
                activeforeground=theme_color(theme, "text"),
                selectcolor=theme_color(theme, "background"),
                font=("Microsoft YaHei UI", 11), anchor="w", cursor="hand2",
                relief="flat", bd=0, highlightthickness=0,
            ).pack(fill="x", padx=18, pady=2)

        self._buttons(master)

    def _on_ok(self) -> None:
        self.result = self.var.get()
        self.destroy()
