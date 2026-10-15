# -*- coding: utf-8 -*-
"""容器类零件:可滚动区域、对话记录、ttk 样式。

和 widgets.py 的分工:那边是"放在页面上的东西"(按钮、卡片、场景),
这边是"用来装东西的东西"。后者通常一次写对就不用再改,
前者会随界面改版反复调整 —— 混在一个文件里,改界面时总要翻过一堆
不会再动的容器代码,很烦。
"""

import tkinter as tk

from .theme import Theme
from .widgets import theme_color


class ScrollFrame(tk.Frame):
    """可滚动的容器。往 inside 里 pack 东西就行。

    Tkinter 没有现成的可滚动 Frame,标准做法是"Canvas + 内嵌 Frame + 滚轮绑定",
    本身不难但要写对几个细节(滚轮事件在 Windows 上是 <MouseWheel> 且
    delta 是 120 的倍数)。包成一个类,别的地方就不用重复踩这些坑。
    """

    def __init__(self, master: tk.Misc, theme: Theme, **kwargs) -> None:
        # 调用方可以覆盖底色:坐在"画进场景图的底板"上的页面要跟着底板走
        # (见 ui/widgets.py 的 panel_palette),用主题背景色会在浅色底板上
        # 露出一块突兀的深色方块。没说就沿用主题色。
        background = kwargs.pop("bg", theme_color(theme, "background"))
        super().__init__(master, bg=background, **kwargs)
        self.theme = theme

        self.canvas = tk.Canvas(self, bg=background,
                                highlightthickness=0, bd=0)
        self.scrollbar = tk.Scrollbar(self, orient="vertical",
                                      command=self.canvas.yview,
                                      bg=theme_color(theme, "panel"),
                                      troughcolor=theme_color(theme, "background"),
                                      bd=0, highlightthickness=0)
        # 内层容器叫 body 而不是 inside —— 调用方写 self.scroller.body 更顺
        self.body = tk.Frame(self.canvas, bg=background)

        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.body.bind("<Configure>", self._on_body_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        # 滚轮只有指针在容器上时才该生效,否则整页的滚动都会打架
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)
        # 兜底:切页时 canvas 被销毁而 <Leave> 不一定触发,全局 <MouseWheel>
        # 就会仍指向这个已死的控件,导致之后整页滚轮失灵。销毁时主动解掉。
        self.canvas.bind("<Destroy>", lambda _e: self._unbind_wheel())

    def _on_body_configure(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        # 让内容跟着画布一起变宽,否则文字会挤在左边一小条里
        self.canvas.itemconfigure(self._window, width=event.width)

    def _bind_wheel(self, _event=None) -> None:
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _unbind_wheel(self, _event=None) -> None:
        self.canvas.unbind_all("<MouseWheel>")

    def _on_wheel(self, event) -> None:
        # canvas 已被销毁却仍收到滚轮事件(切页竞态)—— 直接放过,
        # 顺便把全局绑定解掉,免得后面每滚一下都报一次错
        if not self.canvas.winfo_exists():
            self._unbind_wheel()
            return
        # Windows 上 delta 是 120 的整数倍,除以 120 得到"滚几格"
        self.canvas.yview_scroll(int(-event.delta / 120), "units")


class DialogueLog(tk.Frame):
    """可滚动的对话历史。

    只读(用 state="disabled" 关掉输入),但**仍要保留 Tk 的 Text 控件**,
    因为要支持选中复制 —— 用户想把老师说的话复制出去查一下是合理需求。

    考试页用它显示"刚才那几题我问了什么、老师怎么说的":
    对话框一次只显示一句话,上一句在翻页时就被覆盖了,
    而"我上一题到底答的什么"恰恰是用户最想回看的东西。
    """

    def __init__(self, master: tk.Misc, theme: Theme, height: int = 10,
                 surface: str = "", text_color: str = "", **kwargs) -> None:
        """
        surface / text_color 是给"坐在图里的底板上"的页面用的:
        底色和字色要跟着那块底走(见 ui/widgets.py 的 panel_palette),
        否则这个面板会在浅色底板上变成一块突兀的深色方块。
        不传就沿用主题色 —— 独立弹出的用法不受影响。
        """
        background = surface or theme_color(theme, "panel")
        foreground = text_color or theme_color(theme, "text")
        super().__init__(master, bg=background, **kwargs)
        self.theme = theme
        self.max_lines = 400          # 一屏留这么多行就够,再多的删掉

        self.text = tk.Text(
            self, height=height, wrap="word", bd=0, highlightthickness=0,
            bg=background, fg=foreground,
            insertbackground=foreground,
            font=("Microsoft YaHei UI", 10), padx=10, pady=8)
        scrollbar = tk.Scrollbar(self, command=self.text.yview,
                                 bg=background,
                                 troughcolor=theme_color(theme, "background"),
                                 bd=0, highlightthickness=0)
        self.text.configure(yscrollcommand=scrollbar.set)

        self.text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 用 tag 区分"老师说的"和"你说的",比在文字前面加前缀干净
        self.text.tag_configure("teacher", foreground=theme_color(theme, "accent"))
        self.text.tag_configure("you", foreground=foreground)
        self.text.configure(state="disabled")

    def append(self, speaker: str, message: str) -> None:
        """追加一条。自动滚到最底下。"""
        role = "teacher" if speaker else "you"
        # 关掉只读才能写,写完立刻关回去
        self.text.configure(state="normal")
        self.text.insert("end", "%s:%s\n" % (speaker or "你", message), role)
        self._trim()
        self.text.configure(state="disabled")
        self.text.see("end")

    def _trim(self) -> None:
        """超出上限就从头删掉一些。

        不删的话,一场几百道题的考试会把 Tk 的 Text 撑到几十万字符,
        滚动和重绘都会肉眼可见地变慢 —— 而用户根本不会往回翻那么远。
        """
        total = int(self.text.index("end-1c").split(".")[0])
        if total > self.max_lines:
            self.text.delete("1.0", "%d.0" % (total - self.max_lines))

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")


def apply_ttk_style(root: tk.Misc, theme: Theme) -> None:
    """让 ttk 控件(表格、滚动条、下拉框)也用上主题色。

    **必须先把 ttk 主题切成 clam** —— Windows 默认的 vista 主题不允许
    改背景色,configure 会静默失效,于是深色界面里会突然出现一片
    刺眼的白色表格。这个失败方式很讨厌:不报错,只是难看。
    """
    from tkinter import ttk

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        return

    style.configure("Treeview",
                    background=theme_color(theme, "panel"),
                    fieldbackground=theme_color(theme, "panel"),
                    foreground=theme_color(theme, "text"),
                    rowheight=26, borderwidth=0)
    style.configure("Treeview.Heading",
                    background=theme_color(theme, "panel_light"),
                    foreground=theme_color(theme, "text"),
                    relief="flat")
    style.map("Treeview",
              background=[("selected", theme_color(theme, "accent"))],
              foreground=[("selected", theme_color(theme, "accent_text"))])

    style.configure("TCombobox",
                    fieldbackground=theme_color(theme, "background"),
                    background=theme_color(theme, "panel_light"),
                    foreground=theme_color(theme, "text"),
                    arrowcolor=theme_color(theme, "text"))
    style.configure("Vertical.TScrollbar",
                    background=theme_color(theme, "panel_light"),
                    troughcolor=theme_color(theme, "background"),
                    borderwidth=0)
