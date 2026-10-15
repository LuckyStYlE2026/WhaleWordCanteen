# -*- coding: utf-8 -*-
"""表单零件:带标签的输入框、下拉框、开关行、分区标题。

设置页和单词编辑页要摆几十个输入框。如果每一处都手写
"先建 Label 再建 Entry 再 pack 再对齐",两个后果:代码里全是重复的
样板,而且**不同页面的输入框会长得不一样** —— 因为人眼看不出来
padding 差了 2 像素,但用户看得出来"这两页风格不统一"。

所以输入控件统一从这里出。这里只认识 tkinter,不认识 core。
"""

import tkinter as tk
from typing import Callable, List, Optional, Tuple

from .theme import Theme
from .widgets import theme_color


def section_title(parent: tk.Misc, theme: Theme, text: str,
                  hint: str = "") -> tk.Frame:
    """分区标题。设置页里靠它把一长串选项切成几块。"""
    box = tk.Frame(parent, bg=theme_color(theme, "background"))
    box.pack(fill="x", pady=(18, 6))
    tk.Label(box, text=text, bg=theme_color(theme, "background"),
             fg=theme_color(theme, "text"),
             font=("Microsoft YaHei UI", 13, "bold"), anchor="w").pack(anchor="w")
    if hint:
        tk.Label(box, text=hint, bg=theme_color(theme, "background"),
                 fg=theme_color(theme, "text_dim"), font=("Microsoft YaHei UI", 9),
                 anchor="w", justify="left", wraplength=640).pack(anchor="w")
    return box


class LabeledEntry:
    """一行"标签 + 输入框"。可选带一行说明。

    做成类而不是一个函数,是因为调用方几乎总是要拿到 Entry 句柄
    去读值、写值、禁用 —— 返回一个能直接用的对象比返回元组好读。
    """

    def __init__(self, parent: tk.Misc, theme: Theme, label: str,
                 width: int = 32, hint: str = "", show: str = "") -> None:
        self.theme = theme
        self.frame = tk.Frame(parent, bg=theme_color(theme, "panel"))
        self.frame.pack(fill="x", padx=18, pady=5)

        tk.Label(self.frame, text=label, bg=theme_color(theme, "panel"),
                 fg=theme_color(theme, "text"), width=12, anchor="w",
                 font=("Microsoft YaHei UI", 10)).pack(side="left")

        self.var = tk.StringVar()
        self.entry = tk.Entry(
            self.frame, textvariable=self.var, width=width,
            bg=theme_color(theme, "background"), fg=theme_color(theme, "text"),
            insertbackground=theme_color(theme, "text"),
            relief="flat", bd=0, highlightthickness=1,
            highlightbackground=theme_color(theme, "panel_light"),
            highlightcolor=theme_color(theme, "accent"),
            font=("Microsoft YaHei UI", 11), show=show)
        self.entry.pack(side="left", fill="x", expand=True, ipady=5)

        if hint:
            tk.Label(self.frame, text=hint, bg=theme_color(theme, "panel"),
                     fg=theme_color(theme, "text_dim"), anchor="w",
                     justify="left", wraplength=520,
                     font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(10, 0))

    # ---- 取值 / 写值 ------------------------------------------------------

    def get(self) -> str:
        return self.var.get().strip()

    def set(self, value: str) -> None:
        self.var.set(value or "")


class LabeledChoice:
    """一行"标签 + 下拉框"。给"从几个固定选项里挑一个"用。"""

    def __init__(self, parent: tk.Misc, theme: Theme, label: str,
                 options: List[Tuple[str, str]],
                 initial: str = "") -> None:
        """
        options 的形式是 [(显示文字, 内部值), ...] —— 分开是因为
        界面上要显示"1280 × 720",而设置里存的是 [1280, 720]。
        """
        from tkinter import ttk

        self._values: List[str] = [value for _text, value in options]
        self._labels: List[str] = [text for text, _value in options]
        self.theme = theme

        self.frame = tk.Frame(parent, bg=theme_color(theme, "panel"))
        self.frame.pack(fill="x", padx=18, pady=5)
        tk.Label(self.frame, text=label, bg=theme_color(theme, "panel"),
                 fg=theme_color(theme, "text"), width=12, anchor="w",
                 font=("Microsoft YaHei UI", 10)).pack(side="left")

        self.var = tk.StringVar()
        self.combo = ttk.Combobox(self.frame, textvariable=self.var,
                                  values=self._labels, state="readonly",
                                  font=("Microsoft YaHei UI", 10), width=28)
        self.combo.pack(side="left", ipady=3)
        self.set(initial)

    def get(self) -> str:
        """返回内部值,不是显示文字。"""
        index = self.combo.current()
        if 0 <= index < len(self._values):
            return self._values[index]
        return self._values[0] if self._values else ""

    def set(self, value: str) -> None:
        if value in self._values:
            self.combo.current(self._values.index(value))
        elif self._labels:
            self.combo.current(0)


class LabeledScale:
    """一行"标签 + 滑块"。给"大小、透明度"这类连续取值用。

    为什么用滑块而不是输入框:这两个值是**凭眼睛调**的 ——
    没人知道自己想要 0.82 还是 0.85,但一眼能看出"再透一点更好"。
    滑块旁边实时显示当前值,所以调完不必再去别处确认。
    """

    def __init__(self, parent: tk.Misc, theme: Theme, label: str,
                 low: float, high: float, initial: float,
                 hint: str = "", step: float = 0.02,
                 command: Optional[Callable[[], None]] = None) -> None:
        self.low, self.high = float(low), float(high)
        self.theme = theme
        frame = tk.Frame(parent, bg=theme_color(theme, "panel"))
        frame.pack(fill="x", padx=18, pady=5)

        tk.Label(frame, text=label, bg=theme_color(theme, "panel"),
                 fg=theme_color(theme, "text"), width=12, anchor="w",
                 font=("Microsoft YaHei UI", 10)).pack(side="left")

        self.value_label = tk.Label(
            frame, text="", bg=theme_color(theme, "panel"),
            fg=theme_color(theme, "accent"), width=6, anchor="w",
            font=("Microsoft YaHei UI", 10, "bold"))
        self.value_label.pack(side="left", padx=(0, 8))

        # tk.Scale 只认整数,所以内部按"步数"走,对外换算成浮点。
        # Tk 没有原生的浮点滑块,这是绕过去的标准做法。
        self._steps = max(1, int(round((self.high - self.low) / max(0.001, step))))
        self.var = tk.IntVar(value=self._to_step(initial))
        self.scale = tk.Scale(
            frame, variable=self.var, from_=0, to=self._steps, orient="horizontal",
            showvalue=False, length=260,
            bg=theme_color(theme, "panel"), fg=theme_color(theme, "text"),
            troughcolor=theme_color(theme, "background"),
            activebackground=theme_color(theme, "accent"),
            highlightthickness=0, bd=0, sliderrelief="flat",
            command=lambda _v: self._on_move(command))
        self.scale.pack(side="left")
        self._refresh_value()

        if hint:
            tk.Label(frame, text=hint, bg=theme_color(theme, "panel"),
                     fg=theme_color(theme, "text_dim"), anchor="w",
                     justify="left", wraplength=340,
                     font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(10, 0))

    def _to_step(self, value: float) -> int:
        ratio = (float(value) - self.low) / max(0.001, self.high - self.low)
        return max(0, min(self._steps, int(round(ratio * self._steps))))

    def _refresh_value(self) -> None:
        # 显示用两位小数,读出来就是"0.82 这种能填进设置里的数"
        self.value_label.configure(text="%.2f" % self.get())

    def _on_move(self, command: Optional[Callable[[], None]]) -> None:
        self._refresh_value()
        if command is not None:
            command()

    def get(self) -> float:
        return self.low + (self.high - self.low) * (self.var.get() / float(self._steps))

    def set(self, value: float) -> None:
        self.var.set(self._to_step(value))
        self._refresh_value()


class LabeledCheck:
    """一行复选框。"""

    def __init__(self, parent: tk.Misc, theme: Theme, text: str,
                 hint: str = "", initial: bool = False,
                 command: Optional[Callable[[], None]] = None) -> None:
        self.var = tk.BooleanVar(value=bool(initial))
        box = tk.Frame(parent, bg=theme_color(theme, "panel"))
        box.pack(fill="x", padx=18, pady=4)

        self.check = tk.Checkbutton(
            box, text=text, variable=self.var, command=command,
            bg=theme_color(theme, "panel"), fg=theme_color(theme, "text"),
            activebackground=theme_color(theme, "panel"),
            activeforeground=theme_color(theme, "text"),
            selectcolor=theme_color(theme, "background"),
            font=("Microsoft YaHei UI", 10), anchor="w",
            relief="flat", bd=0, highlightthickness=0, cursor="hand2")
        self.check.pack(anchor="w")

        if hint:
            tk.Label(box, text=hint, bg=theme_color(theme, "panel"),
                     fg=theme_color(theme, "text_dim"), anchor="w", justify="left",
                     wraplength=620,
                     font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=(22, 0))

    def get(self) -> bool:
        return bool(self.var.get())

    def set(self, value: bool) -> None:
        self.var.set(bool(value))


def flat_button(parent: tk.Misc, theme: Theme, text: str,
                command: Callable[[], None]) -> tk.Button:
    """无边框的小按钮。放在列表行尾当操作按钮用。

    单独一个而不是复用 ghost_button,是因为这里会在一行里放好几个,
    带边框会显得很吵。
    """
    return tk.Button(
        parent, text=text, command=command,
        bg=theme_color(theme, "panel_light"), fg=theme_color(theme, "text"),
        activebackground=theme_color(theme, "accent"),
        activeforeground=theme_color(theme, "accent_text"),
        relief="flat", bd=0, highlightthickness=0, cursor="hand2",
        font=("Microsoft YaHei UI", 9), padx=10, pady=3)


def hint_label(parent: tk.Misc, theme: Theme, text: str,
               wrap: int = 640) -> tk.Label:
    """一行灰色小字。用来解释那些"看名字会误解"的选项。"""
    label = tk.Label(parent, text=text, bg=theme_color(theme, "panel"),
                     fg=theme_color(theme, "text_dim"), anchor="w",
                     justify="left", wraplength=wrap,
                     font=("Microsoft YaHei UI", 9))
    label.pack(fill="x", padx=18, pady=(0, 6))
    return label
