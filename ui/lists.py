# -*- coding: utf-8 -*-
"""列表零件:词包勾选列表、人设单选列表、形象九宫格。

三者都遵循同一条原则:**只负责显示和选中,不做任何判断**。
"这个词该不该今天复习""这个词包算不算逾期"都由 core 算好了再传进来。
界面里出现 if 判断学习规则就是分层漏了,那种代码最难改 ——
因为它把"规则"藏在了"长得像界面"的地方。

单词表格(ttk.Treeview 那种)在 tables.py,不在这里 ——
它是另一种实现(多列、可排序),混在一起要不停切换心智模型。
"""

import tkinter as tk
from typing import Callable, Dict, List, Optional, Tuple

from .theme import Theme
from .widgets import theme_color


def normalize_groups(groups) -> List[Tuple[str, list]]:
    """把两个列表控件共用的入参统一成 [(分区标题, [条目]), ...]。

    兼容两种入参:老的扁平 [条目, ...] 和新的 [(标题, [条目]), ...]。
    靠「第一项是不是 tuple 且第二项是 list」来分辨 —— 不靠类型标注,
    因为运行时拿不到标注。
    """
    if not groups:
        return []
    first = groups[0]
    if isinstance(first, tuple) and len(first) == 2:
        return groups            # 已经是分组形式
    return [("", list(groups))]  # 扁平列表 → 一个匿名组


def section_label(parent: tk.Misc, theme: Theme, title: str) -> None:
    """一个分区的标题行。和条目行不同色,让用户一眼分出两组。"""
    tk.Label(parent, text=title, bg=theme_color(theme, "background"),
             fg=theme_color(theme, "text_dim"),
             font=("Microsoft YaHei UI", 10, "bold"), anchor="w"
             ).pack(fill="x", pady=(10, 4), padx=2)


class PackCheckList(tk.Frame):
    """词包勾选列表。

    规格里"用户可以勾选词包进行考试,或者勾选词包进行复习"指的就是它。
    """

    def __init__(self, master: tk.Misc, theme: Theme, height: int = 10) -> None:
        super().__init__(master, bg=theme_color(theme, "background"))
        from .panels import ScrollFrame

        self.theme = theme
        self._vars: Dict[str, tk.BooleanVar] = {}
        self._packs: List[object] = []

        self.scroller = ScrollFrame(self, theme)
        self.scroller.pack(fill="both", expand=True)

    def fill(self, groups, describe, subtitle_of, leading=None,
             leading_title: str = "") -> None:
        """重建整个列表。

        groups 的形式是 [(分区标题, [词包]), ...]。分成几组而不是一条
        扁平列表,是因为「我导入的词表」和「学习/考试产生的结果包」
        是两类东西,混在一起用户分不清哪些是自己的资料、哪些是产物。
        但**勾选是跨组连续的** —— 用户要能同时勾选几个词表包 + 几个
        结果包一起考,所以仍是一个滚动区、一个状态。

        describe(pack) 由调用方提供,用来把词包渲染成一个标题 ——
        文字怎么写是界面的事,不该让这个控件去猜。

        leading 是 [(key, 标题, 说明), ...],画在所有分组之前;
        leading_title 非空时给它们加一个分区标题(比如「今日复习」)。

        置顶行给"今日复习"这类**按条件圈出来、但不落盘**的伪条目用:
        它们要能和真词包一样被勾选(所以登记进 _vars),
        但不能出现在 checked_packs 里(所以不进 _packs)——
        checked_packs 的语义是"用户勾了哪些存档里的词包",伪条目没有存档。

        groups 兼容老的扁平列表(见 normalize_groups)。
        """
        for child in self.scroller.body.winfo_children():
            child.destroy()
        self._vars = {}
        self._packs = []

        if leading and leading_title:
            section_label(self.scroller.body, self.theme, leading_title)
        for key, title, subtitle in (leading or []):
            self._add_row(key, title, subtitle)

        for section_title, packs in normalize_groups(groups):
            if section_title:
                section_label(self.scroller.body, self.theme, section_title)
            for pack in packs:
                self._packs.append(pack)
                self._add_row(getattr(pack, "id", ""), describe(pack),
                              subtitle_of(pack))

        if not self._packs:
            tk.Label(self.scroller.body, text="还没有词包。去「单词设置」导入词表,或在「开始」里学一遍。",
                     bg=theme_color(self.theme, "background"),
                     fg=theme_color(self.theme, "text_dim"),
                     font=("Microsoft YaHei UI", 10)).pack(pady=20)

    def _add_row(self, key: str, title: str, subtitle: str) -> None:
        """画一行勾选项,并把它登记进 _vars。key 就是勾选时拿到的那个 id。"""
        row = tk.Frame(self.scroller.body, bg=theme_color(self.theme, "panel"))
        row.pack(fill="x", pady=3, padx=2)

        var = tk.BooleanVar(value=False)
        self._vars[key] = var

        box = tk.Frame(row, bg=theme_color(self.theme, "panel"))
        box.pack(side="left", fill="x", expand=True, padx=10, pady=7)
        tk.Checkbutton(box, text=title, variable=var,
                       bg=theme_color(self.theme, "panel"),
                       fg=theme_color(self.theme, "text"),
                       activebackground=theme_color(self.theme, "panel"),
                       activeforeground=theme_color(self.theme, "text"),
                       selectcolor=theme_color(self.theme, "background"),
                       font=("Microsoft YaHei UI", 11), anchor="w",
                       relief="flat", bd=0, highlightthickness=0,
                       cursor="hand2").pack(anchor="w")
        tk.Label(box, text=subtitle, bg=theme_color(self.theme, "panel"),
                 fg=theme_color(self.theme, "text_dim"), anchor="w",
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=(22, 0))

    # ---- 选中 ------------------------------------------------------------

    def checked_ids(self) -> List[str]:
        return [pack_id for pack_id, var in self._vars.items() if var.get()]

    def checked_packs(self) -> List[object]:
        chosen = set(self.checked_ids())
        return [p for p in self._packs if getattr(p, "id", "") in chosen]

    def check_all(self, value: bool = True) -> None:
        for var in self._vars.values():
            var.set(value)


class SelectableTextList(tk.Frame):
    """单选列表:一行一个标题 + 一行说明。

    AI 选择页右边的人设列表用它。和角色九宫格的区别是不带图 ——
    人设就是一段文字,给它配个缩略图反而会让人以为那里该有张画。
    """

    def __init__(self, master: tk.Misc, theme: Theme,
                 on_select: Optional[Callable[[str], None]] = None,
                 height: int = 10, empty_text: str = "") -> None:
        super().__init__(master, bg=theme_color(theme, "background"))
        from .panels import ScrollFrame

        self.theme = theme
        self.on_select = on_select
        self.empty_text = empty_text
        self._rows: Dict[str, tk.Frame] = {}
        self._selected = ""

        self.scroller = ScrollFrame(self, theme)
        self.scroller.pack(fill="both", expand=True)

    def fill(self, items, selected: str = "") -> None:
        """items 的形式是 [(id, 标题, 说明), ...],也可以是分组的
        [(分区标题, [(id, 标题, 说明), ...]), ...]。

        分组只是多一行分区标题。**选中仍是全局单选**:两组共用一个
        当前项 —— 这里的语义是"接下来操作哪一个",不存在"每组各选一个"。
        """
        for child in self.scroller.body.winfo_children():
            child.destroy()
        self._rows = {}
        self._selected = selected

        count = 0
        for section_title, group in normalize_groups(items):
            if section_title:
                section_label(self.scroller.body, self.theme, section_title)
            for item_id, title, subtitle in group:
                self._add_row(item_id, title, subtitle)
                count += 1
        self._paint()

        # 空列表时给一句话,别让用户对着一片空白猜"是不是没加载出来"
        if not count and self.empty_text:
            tk.Label(self.scroller.body, text=self.empty_text,
                     bg=theme_color(self.theme, "background"),
                     fg=theme_color(self.theme, "text_dim"),
                     font=("Microsoft YaHei UI", 10)).pack(pady=20)

    def _add_row(self, item_id: str, title: str, subtitle: str) -> None:
        row = tk.Frame(self.scroller.body, bg=theme_color(self.theme, "panel"),
                       cursor="hand2")
        row.pack(fill="x", pady=3, padx=2)

        title_label = tk.Label(row, text=title,
                               bg=theme_color(self.theme, "panel"),
                               fg=theme_color(self.theme, "text"),
                               font=("Microsoft YaHei UI", 12, "bold"), anchor="w")
        title_label.pack(fill="x", padx=10, pady=(8, 0))

        subtitle_label = tk.Label(row, text=subtitle or "(没有内容)",
                                  bg=theme_color(self.theme, "panel"),
                                  fg=theme_color(self.theme, "text_dim"),
                                  font=("Microsoft YaHei UI", 9), anchor="w",
                                  justify="left", wraplength=380)
        subtitle_label.pack(fill="x", padx=10, pady=(0, 8))

        self._rows[item_id] = row

        # 记住每行的子控件,换选中色的时候要一起改
        row._children = (title_label, subtitle_label)   # type: ignore[attr-defined]
        for widget in (row, title_label, subtitle_label):
            widget.bind("<Button-1>", lambda _e, i=item_id: self.select(i))

    def select(self, item_id: str) -> None:
        self._selected = item_id
        self._paint()
        if self.on_select is not None:
            self.on_select(item_id)

    def selected_id(self) -> str:
        return self._selected

    def _paint(self) -> None:
        for item_id, row in self._rows.items():
            color = theme_color(self.theme, "panel_light" if item_id == self._selected
                                else "panel")
            # type: ignore[attr-defined]
            for widget in (row,) + row._children:
                widget.configure(bg=color)

