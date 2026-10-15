# -*- coding: utf-8 -*-
"""表格零件:基于 ttk.Treeview 的单词表格。

从 lists.py 拆出来的直接原因:那个文件攒了四种列表零件,加上"分组标题"
之后要过 300 行,而表格和那几个列表本来就不是一回事 ——
表格是 ttk.Treeview(自带排序、多列、滚动条),那几个是纯 Frame 拼的行,
把两种实现放在一个文件里,读的时候要不停切换心智模型。

和 lists.py 一样的原则:**只负责显示和选中,不做任何判断。**
"""

import tkinter as tk
from typing import Callable, List, Optional, Tuple

from .theme import Theme
from .widgets import theme_color


class WordTable(tk.Frame):
    """单词表格。基于 ttk.Treeview —— 它自带排序、选中、滚动条。"""

    # 「序」那一列是这一包里的第几个(1 起),被标记的那一行显示成「★ 347」。
    # 顺序即词包里的先后,用户靠它和「从第几个开始学」对上号 ——
    # 没有这一列,他在弹窗里填"从第 347 个开始"时根本无从知道自己填的是谁。
    COLUMNS: List[Tuple[str, str, int]] = [
        ("index", "序", 60),
        ("word", "单词", 160),
        ("phonetic", "发音", 150),
        ("translation", "翻译", 300),
        ("group", "组合", 80),
    ]

    def __init__(self, master: tk.Misc, theme: Theme, height: int = 14,
                 on_select: Optional[Callable[[str], None]] = None) -> None:
        super().__init__(master, bg=theme_color(theme, "background"))
        from tkinter import ttk

        self.theme = theme
        self.on_select = on_select
        self._ids: List[str] = []        # 行序 → 单词 id

        columns = [key for key, _title, _width in self.COLUMNS]
        self.tree = ttk.Treeview(self, columns=columns, show="headings",
                                 height=height, selectmode="browse")
        for key, title, width in self.COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="w",
                             stretch=(key == "translation"))

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self._on_select)

    def _on_select(self, _event=None) -> None:
        if self.on_select is None:
            return
        word_id = self.selected_id()
        if word_id:
            self.on_select(word_id)

    # ---- 填充 ------------------------------------------------------------

    def fill(self, rows: List[Tuple[str, Tuple[str, str, str, str, str]]]) -> None:
        """rows 的形式是 [(单词 id, (五个字段的文字)), ...]。

        让调用方把文字整理好再传进来,而不是把 Word 对象丢进来 ——
        这样这个控件永远不需要 import core,换数据结构时它不用改。
        """
        self.tree.delete(*self.tree.get_children())
        self._ids = []
        for word_id, values in rows:
            self.tree.insert("", "end", values=values)
            self._ids.append(word_id)

    def selected_id(self) -> str:
        selection = self.tree.selection()
        if not selection:
            return ""
        index = self.tree.index(selection[0])
        if 0 <= index < len(self._ids):
            return self._ids[index]
        return ""

    def select(self, word_id: str) -> None:
        """选中某一行。找不到就什么都不做 —— 调用方常常是"重画之后把
        原来选中的那行再选回来",而那一行可能刚被删掉。"""
        if word_id not in self._ids:
            return
        item = self.tree.get_children()[self._ids.index(word_id)]
        self.tree.selection_set(item)
        self.tree.see(item)

    def clear(self) -> None:
        self.fill([])


class PackTable(tk.Frame):
    """词包一览表。记忆曲线页底部用它。

    和 WordTable 是同一个套路,只是列不同。单独一个类而不是参数化 WordTable,
    是因为列的**含义**不一样:这里每行的 id 是词包,不是单词,
    混用一个类会让"selected_id 到底返回什么"变得要靠上下文猜。
    """

    COLUMNS: List[Tuple[str, str, int]] = [
        ("title", "词包", 240),
        ("count", "词数", 70),
        ("known", "已掌握", 80),
        ("due", "到期", 70),
        ("status", "状态", 140),
    ]

    def __init__(self, master: tk.Misc, theme: Theme, height: int = 8) -> None:
        super().__init__(master, bg=theme_color(theme, "background"))
        from tkinter import ttk

        self.theme = theme
        self._ids: List[str] = []        # 行序 → 词包 id

        columns = [key for key, _title, _width in self.COLUMNS]
        self.tree = ttk.Treeview(self, columns=columns, show="headings",
                                 height=height, selectmode="browse")
        for key, title, width in self.COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="w",
                             stretch=(key == "title"))

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def fill(self, rows: List[Tuple[str, Tuple[str, str, str, str, str]]]) -> None:
        """rows 的形式是 [(词包 id, (五列文字)), ...]。

        和 WordTable 一样,由调用方把文字整理好再传进来 ——
        这个控件永远不需要 import core。
        """
        self.tree.delete(*self.tree.get_children())
        self._ids = []
        for pack_id, values in rows:
            self.tree.insert("", "end", values=values)
            self._ids.append(pack_id)

    def clear(self) -> None:
        self.fill([])

