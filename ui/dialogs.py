# -*- coding: utf-8 -*-
"""弹窗:单词编辑器,以及几个包了一层的系统对话框。

**为什么给 messagebox 再包一层?** 因为项目要能切换语言(见 core/i18n.py),
而 messagebox 的按钮文字("确定""取消")是 Windows 给的,改不了。
包一层之后,标题和正文至少是我们自己的,用户看到的是中文,
而不是一半中文一半英文的对话框。

单词编辑器用 Toplevel 而不是嵌在页面里的一块表单,理由很实际:
编辑单词是个"进入—改完—退出"的动作,期间不该被列表刷新打断。
"""

import tkinter as tk
from typing import Dict, Optional

from .forms import LabeledEntry
from .theme import Theme
from .widgets import ghost_button, primary_button, theme_color

# 编辑器的字段顺序。前两个是必填 —— 与规格一致("只有单词,翻译是必填项")。
FIELDS = [
    ("word", "单词", True),
    ("translation", "翻译", True),
    ("phonetic", "发音", False),
    ("example", "例句", False),
    ("collocation", "搭配", False),
    ("group", "组合", False),
]

GROUP_HINT = "留空也行。填了以后,学习模式下同组的单词会一起出现。"


class WordEditor(tk.Toplevel):
    """新建 / 修改一个单词。

    用模态窗口(transient + grab_set)而不是普通窗口,是为了避免
    "编辑器开着,底下列表却在刷新"这种让人困惑的状态。
    """

    def __init__(self, master: tk.Misc, theme: Theme, title: str = "编辑单词",
                 values: Optional[Dict[str, str]] = None) -> None:
        super().__init__(master)
        self.theme = theme
        self.result: Optional[Dict[str, str]] = None
        self._entries: Dict[str, LabeledEntry] = {}

        self.title(title)
        self.configure(bg=theme_color(theme, "background"))
        self.resizable(False, False)

        panel = tk.Frame(self, bg=theme_color(theme, "panel"))
        panel.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(panel, text=title, bg=theme_color(theme, "panel"),
                 fg=theme_color(theme, "text"),
                 font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w", padx=18,
                                                              pady=(14, 4))
        tk.Label(panel, text="带 * 的必填;其余留空不影响使用。",
                 bg=theme_color(theme, "panel"), fg=theme_color(theme, "text_dim"),
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=18)

        source = values or {}
        for key, label, required in FIELDS:
            hint = "必填" if required else ("组合" if key == "group" else "")
            entry = LabeledEntry(panel, theme, "%s%s" % (label, " *" if required else ""),
                                 width=40, hint=(GROUP_HINT if key == "group" else ""))
            entry.set(source.get(key, ""))
            self._entries[key] = entry

        self.error_label = tk.Label(panel, text="", bg=theme_color(theme, "panel"),
                                    fg=theme_color(theme, "bad"),
                                    font=("Microsoft YaHei UI", 9))
        self.error_label.pack(anchor="w", padx=18, pady=(6, 0))

        buttons = tk.Frame(panel, bg=theme_color(theme, "panel"))
        buttons.pack(fill="x", padx=18, pady=14)
        primary_button(buttons, "保存", self._on_save, theme).pack(side="right")
        ghost_button(buttons, "取消", self._on_cancel, theme).pack(side="right", padx=8)

        # 只绑 Esc 取消,**不绑回车保存**:这是多字段中文输入的弹窗,
        # 输入法用回车确认候选词时会误触发 <Return>,把没填完的词存进去、
        # 或者弹窗提前关掉 —— 用户会以为「按了个回车就出 bug 了」。
        # 保存留给右下角那个显眼的「保存」按钮。
        self.bind("<Escape>", lambda _e: self._on_cancel())

        self.transient(master.winfo_toplevel())
        self.grab_set()
        center_on(self, master)
        self._entries["word"].entry.focus_set()

    # ---- 按钮 ------------------------------------------------------------

    def _on_save(self) -> None:
        values = {key: entry.get() for key, entry in self._entries.items()}
        if not values["word"]:
            self.error_label.configure(text="单词不能为空。")
            return
        if not values["translation"]:
            self.error_label.configure(text="翻译不能为空 —— 没有释义就没法判断你答得对不对。")
            return
        self.result = values
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()


class PersonaEditor(tk.Toplevel):
    """编辑一段人设:名字 + 提示词。

    提示词用多行文本框而不是单行输入框 —— 它是写给模型看的一段话,
    单行框会让用户以为只能填几个字。
    """

    def __init__(self, master: tk.Misc, theme: Theme, title: str = "编辑人设",
                 name: str = "", prompt: str = "") -> None:
        super().__init__(master)
        self.result = None
        self.title(title)
        self.configure(bg=theme_color(theme, "background"))

        panel = tk.Frame(self, bg=theme_color(theme, "panel"))
        panel.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(panel, text="名字", bg=theme_color(theme, "panel"),
                 fg=theme_color(theme, "text"),
                 font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=18,
                                                       pady=(14, 2))
        self.name_var = tk.StringVar(value=name)
        tk.Entry(panel, textvariable=self.name_var, width=48,
                 bg=theme_color(theme, "background"),
                 fg=theme_color(theme, "text"),
                 insertbackground=theme_color(theme, "text"),
                 relief="flat", bd=0, highlightthickness=1,
                 highlightbackground=theme_color(theme, "panel_light"),
                 font=("Microsoft YaHei UI", 11)).pack(padx=18, ipady=5, fill="x")

        tk.Label(panel, text="人设(发给老师的提示词)", bg=theme_color(theme, "panel"),
                 fg=theme_color(theme, "text"),
                 font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=18,
                                                       pady=(12, 2))
        tk.Label(panel, text="写得越具体,老师越像你想要的那个人。"
                             "但每长一点,每次调用 API 都要多花一点钱。",
                 bg=theme_color(theme, "panel"), fg=theme_color(theme, "text_dim"),
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=18)

        self.text = tk.Text(panel, height=10, wrap="word", bd=0,
                            highlightthickness=1,
                            highlightbackground=theme_color(theme, "panel_light"),
                            bg=theme_color(theme, "background"),
                            fg=theme_color(theme, "text"),
                            insertbackground=theme_color(theme, "text"),
                            font=("Microsoft YaHei UI", 11), padx=8, pady=6)
        self.text.pack(padx=18, pady=(6, 0), fill="both", expand=True)
        self.text.insert("1.0", prompt or "")

        buttons = tk.Frame(panel, bg=theme_color(theme, "panel"))
        buttons.pack(fill="x", padx=18, pady=14)
        primary_button(buttons, "保存", self._on_save, theme).pack(side="right")
        ghost_button(buttons, "取消", self.destroy, theme).pack(side="right", padx=8)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.transient(master.winfo_toplevel())
        self.grab_set()

    def _on_save(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            return
        self.result = (name, self.text.get("1.0", "end").strip())
        self.destroy()


# --------------------------------------------------------------------------
# 系统对话框的薄包装
# --------------------------------------------------------------------------

def owner_window(parent: tk.Misc):
    """弹窗的宿主窗口。

    接住 TclError 是因为调用方可能在页面切换(控件已销毁)之后才弹窗 ——
    那种情况下"弹不出来"是小事,不该反过来把程序带崩。

    名字不带下划线、而且放在这里,是因为 ui/prompts.py 也要用它:
    两个模块都需要的东西就不该还叫"私有"。
    """
    try:
        return parent.winfo_toplevel() if parent is not None else None
    except tk.TclError:
        return None


def center_on(window: tk.Misc, master: tk.Misc) -> None:
    """把弹窗摆在宿主窗口中间偏上。三个弹窗模块共用这一份。

    以前 WordEditor、prompts 和起点弹窗各写了一份几乎一样的居中,
    三份在"要不要接异常、宿主找不到怎么办"上已经开始长得不一样了 ——
    这种一模一样又各养各的逻辑,迟早有一份修了别的没修。
    """
    try:
        window.update_idletasks()
        host = owner_window(master)
        if host is None:
            return
        x = host.winfo_rootx() + max(0, (host.winfo_width()
                                         - window.winfo_width()) // 2)
        y = host.winfo_rooty() + max(0, (host.winfo_height()
                                         - window.winfo_height()) // 3)
        window.geometry("+%d+%d" % (x, y))
    except tk.TclError:
        return


def info(parent: tk.Misc, title: str, message: str) -> None:
    from tkinter import messagebox
    messagebox.showinfo(title, message, parent=owner_window(parent))


def warn(parent: tk.Misc, title: str, message: str) -> None:
    from tkinter import messagebox
    messagebox.showwarning(title, message, parent=owner_window(parent))


def error(parent: tk.Misc, title: str, message: str) -> None:
    from tkinter import messagebox
    messagebox.showerror(title, message, parent=owner_window(parent))


def confirm(parent: tk.Misc, title: str, message: str) -> bool:
    from tkinter import messagebox
    return bool(messagebox.askyesno(title, message, parent=owner_window(parent)))
