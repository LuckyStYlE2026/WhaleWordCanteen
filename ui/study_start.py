# -*- coding: utf-8 -*-
"""「从哪开始学」这一个弹窗:看着单词列表挑起点。

为什么不是一个"从第()个开始"的输入框?因为用户不知道第 347 个是什么词 ——
让用户填一个自己看不见的数字,等于让他猜。这里把整包的词按顺序摆成一张表
(和「单词设置-打开词包」同一种表格),再配一个搜索框:记得位置的直接点行,
只记得单词的先搜再点。

**打开时默认选中"接着上次"的那一行**(没学过就选第一个),所以大多数时候
确认一眼、点一下按钮就走;要换地方的人才需要滚动或搜索。

这个弹窗是**只读**的:它不改词包、不写存档,选出来的只是"这一轮的起点"。
进度仍然由学习页按实际评价的词去推(只进不退,见 core.pack_progress);
要增删改词,去「单词设置」打开词包 —— 那边才是编辑的地方。

单独成文件,是因为它是唯一一处同时要知道两件事的地方:词包学到第几个了
(core.pack_progress)和设置里一次学多少(core.config)。塞进挑词页或学习页
都会让那两页多背一层与它们无关的知识。
"""

import tkinter as tk
from typing import Dict, List, Optional, Tuple

from core.models import Word
from core.pack_progress import bookmark_index, clamp_index
from core.packs import WordPack

from .dialogs import center_on, owner_window
from .tables import WordTable
from .theme import Theme
from .widgets import ghost_button, primary_button, theme_color


def _parse(text: str, default: int, total: int, allow_zero: bool = False) -> int:
    """把用户输入的一行字变成一个合理的整数。

    看不懂就退回默认值,**不弹错误框**:这个弹窗的目的是"赶紧开始学",
    为了一次手滑把用户拦在这里不值得。上限夹到词数,超出部分没有意义。
    """
    try:
        value = int(str(text).strip())
    except (TypeError, ValueError):
        return default
    if value < 0 or (value == 0 and not allow_zero):
        return default
    return min(value, total)


def ask_start_point(parent: tk.Misc, theme: Theme, pack: WordPack,
                    batch_size: int,
                    index: Dict[str, Word]) -> Optional[Tuple[int, int]]:
    """问这一轮从哪开始学、学多少个。返回 (起点, 数量);取消返回 None。

    弹出的是 StartPointDialog:整包的词摆成一张只读的表,默认选中
    "接着上次"的那一行。起点/数量只是**这一轮**的输入,不写进词包。
    """
    if not pack.word_ids:
        return None
    dialog = StartPointDialog(parent, theme, pack, batch_size, index)
    parent.wait_window(dialog)
    return dialog.result


class StartPointDialog(tk.Toplevel):
    """选起点的模态窗口:搜索框 + 只读词表 + 数量输入。

    只读是刻意的:起点选择是"这一轮从哪里开始",不是编辑。窗口里
    不提供任何改词包的入口,选完即走,什么都不落盘。
    """

    def __init__(self, master: tk.Misc, theme: Theme, pack: WordPack,
                 batch_size: int, index: Dict[str, Word]) -> None:
        super().__init__(master)
        self.theme = theme
        self.pack = pack
        self.index = index
        self.result: Optional[Tuple[int, int]] = None
        # 当前选中的词 id。搜索过滤会重画表格、清掉表格自己的选中,
        # 所以"选了哪个词"必须记在自己身上,不依赖表格还记得。
        self._selected = ""
        self._default_count = batch_size if batch_size > 0 else 0

        self.title("从哪里开始学?")
        self.configure(bg=theme_color(theme, "background"))
        self.geometry("780x520")
        self.minsize(560, 400)      # 词多的包要能拉大看,但不许小到没法用

        panel = tk.Frame(self, bg=theme_color(theme, "panel"))
        panel.pack(fill="both", expand=True, padx=14, pady=14)

        tk.Label(panel, text="「%s」共 %d 个单词。点一行选中起点,"
                             "双击那一行就直接开始。"
                 % (pack.title, len(pack.word_ids)),
                 bg=theme_color(theme, "panel"), fg=theme_color(theme, "text"),
                 justify="left", wraplength=700,
                 font=("Microsoft YaHei UI", 11)).pack(anchor="w", padx=14,
                                                       pady=(12, 6))

        # ---- 搜索行:每敲一个字就重过滤,不用按回车 ------------------------
        search_bar = tk.Frame(panel, bg=theme_color(theme, "panel"))
        search_bar.pack(fill="x", padx=14)
        tk.Label(search_bar, text="搜索", bg=theme_color(theme, "panel"),
                 fg=theme_color(theme, "text_dim"),
                 font=("Microsoft YaHei UI", 10)).pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_e: self._apply_filter())
        search = tk.Entry(search_bar, textvariable=self.search_var, width=30,
                          bg=theme_color(theme, "background"),
                          fg=theme_color(theme, "text"),
                          insertbackground=theme_color(theme, "text"),
                          relief="flat", bd=0, highlightthickness=1,
                          highlightbackground=theme_color(theme, "panel_light"),
                          highlightcolor=theme_color(theme, "accent"),
                          font=("Microsoft YaHei UI", 10))
        search.pack(side="left", padx=(8, 0), ipady=4)
        search.focus_set()
        self.match_label = tk.Label(search_bar, text="",
                                    bg=theme_color(theme, "panel"),
                                    fg=theme_color(theme, "text_dim"),
                                    font=("Microsoft YaHei UI", 9))
        self.match_label.pack(side="left", padx=(10, 0))

        # ---- 词表:和「单词设置-打开词包」同一张表,只是只读 ----------------
        self.table = WordTable(panel, theme, height=13,
                               on_select=self._on_row_selected)
        self.table.pack(fill="both", expand=True, padx=14, pady=(8, 0))
        # 双击一行 = 选中并立刻开始。想快走的人两下就出门,
        # 不必再把视线挪到底部找按钮。
        self.table.tree.bind("<Double-1>", lambda _e: self._on_confirm())

        # ---- 数量行 ----------------------------------------------------------
        count_bar = tk.Frame(panel, bg=theme_color(theme, "panel"))
        count_bar.pack(fill="x", padx=14, pady=(8, 0))
        tk.Label(count_bar, text="这一轮学多少个", bg=theme_color(theme, "panel"),
                 fg=theme_color(theme, "text"),
                 font=("Microsoft YaHei UI", 10)).pack(side="left")
        self.count_var = tk.StringVar(value=str(self._default_count))
        tk.Entry(count_bar, textvariable=self.count_var, width=8,
                 bg=theme_color(theme, "background"),
                 fg=theme_color(theme, "text"),
                 insertbackground=theme_color(theme, "text"),
                 relief="flat", bd=0, highlightthickness=1,
                 highlightbackground=theme_color(theme, "panel_light"),
                 highlightcolor=theme_color(theme, "accent"),
                 font=("Microsoft YaHei UI", 10)).pack(side="left", padx=10,
                                                       ipady=3)
        tk.Label(count_bar, text="0 表示一直学到这个词包的最后一个",
                 bg=theme_color(theme, "panel"), fg=theme_color(theme, "text_dim"),
                 font=("Microsoft YaHei UI", 9)).pack(side="left")

        # ---- 按钮行 ----------------------------------------------------------
        buttons = tk.Frame(panel, bg=theme_color(theme, "panel"))
        buttons.pack(fill="x", padx=14, pady=12)
        # 按钮文字刻意固定为「开始学习」:用户找的是"开始/下一步"这样的
        # 动词。以前按钮上写的是"从第 347 个开始",读起来像一句状态说明
        # 而不是按钮,选完词找不到下一步在哪,卡在这一步(2026-10-12 反馈)。
        # "从第几个"是状态信息,挪到左边那行灰字里。
        self.preview_label = tk.Label(
            buttons, text="", bg=theme_color(theme, "panel"),
            fg=theme_color(theme, "text_dim"),
            font=("Microsoft YaHei UI", 9))
        self.preview_label.pack(side="left")
        self.confirm_button = primary_button(buttons, "", self._on_confirm, theme)
        self.confirm_button.pack(side="right")
        ghost_button(buttons, "取消", self.destroy, theme).pack(side="right",
                                                                padx=8)

        self.bind("<Escape>", lambda _e: self.destroy())

        # 整包的行只建一次,搜索过滤只是从里面挑几行。默认选中"接着上次"
        # 的那行(没学过/学完了就选第一个)—— 大多数时候用户就是要接着学。
        self._rows = self._build_rows()
        self._apply_filter()
        resume = clamp_index(pack, pack.progress.next_index)
        if not 0 < resume < len(pack.word_ids):
            resume = 0
        self._select_word(pack.word_ids[resume])

        self.transient(owner_window(master))
        self.grab_set()
        self.after_idle(lambda: center_on(self, master))

    # ---- 数据 ------------------------------------------------------------

    def _build_rows(self) -> List[Tuple[str, Tuple[str, str, str, str, str],
                                         int, str]]:
        """整包的行,一次建好。返回 (词 id, 五列文字, 原始位置, 搜索串)。

        「序」显示的是**词包里的原始位置**(0 起存储,+1 显示),不是
        "可见行里的第几个":「从第 N 个开始」喂给 study_range 切的就是
        word_ids[N-1:],两个数字必须同源。词库里找不到的 id(包里留着
        引用、词已被删)不显示 —— 那种词本来就学不了,序号留洞是诚实的。
        """
        marked = bookmark_index(self.pack)
        rows = []
        for position, word_id in enumerate(self.pack.word_ids):
            word = self.index.get(word_id)
            if word is None:
                continue
            order = ("★ %d" % (position + 1) if position == marked
                     else str(position + 1))
            values = (order, word.word, word.phonetic, word.translation,
                      word.group)
            blob = " ".join(field.casefold() for field in values)
            rows.append((word_id, values, position, blob))
        return rows

    def _apply_filter(self) -> None:
        """按搜索框重画表格。选中的词若还在可见行里,把它选回去。"""
        query = self.search_var.get().strip().casefold()
        rows = [(word_id, values) for word_id, values, _pos, blob in self._rows
                if not query or query in blob]
        if query:
            self.match_label.configure(text="匹配 %d / 共 %d 个"
                                       % (len(rows), len(self._rows)))
        else:
            self.match_label.configure(text="共 %d 个" % len(rows))
        self.table.fill(rows)
        if self._selected:
            self.table.select(self._selected)

    # ---- 选中 ------------------------------------------------------------

    def _select_word(self, word_id: str) -> None:
        """选中某一行。重画之后恢复选中也走这里。

        确认按钮在这里**直接**刷新,不等 <<TreeviewSelect>> 回调 ——
        那是排队触发的虚拟事件,依赖它意味着"弹窗刚打开的一瞬间,
        按钮上可能还没有起点文字"。
        """
        self._selected = word_id
        self.table.select(word_id)
        self._update_confirm()

    def _on_row_selected(self, word_id: str) -> None:
        """表格点了一行(用户点的,或 _select_word 引发的)。"""
        self._selected = word_id
        self._update_confirm()

    def _update_confirm(self) -> None:
        """按钮和左侧灰字跟着选中行走 —— 按下之前就看到将要发生的事。

        按钮只负责"这是个能开始的动作"(开始学习 / 先选一个词),
        具体起点写在灰字里 —— 两种信息混在一个按钮上,前一种会被淹没。
        """
        position = self._position_of(self._selected)
        if position < 0:
            self.confirm_button.configure(text="先在列表里选一个词",
                                          state="disabled")
            self.preview_label.configure(text="")
            return
        word = self.index[self._selected]
        self.confirm_button.configure(text="开始学习", state="normal")
        self.preview_label.configure(
            text="将从第 %d 个「%s」开始" % (position + 1, word.word))

    def _position_of(self, word_id: str) -> int:
        """词在包里的原始位置(0 起);不在表里返回 -1。"""
        for row_id, _values, position, _blob in self._rows:
            if row_id == word_id:
                return position
        return -1

    # ---- 确认 ------------------------------------------------------------

    def _on_confirm(self) -> None:
        """确认。数量填错(空/负数/超词数)退回默认或夹回,见 _parse。

        起点**优先读表格此刻的选中**,读不到再退回记在自己身上的那份:
        双击的时序是 Button-1(改了选中,但 <<TreeviewSelect>> 还在
        事件队列里)→ Double-1(这里)—— 只认记忆的那份会拿到上一行的词。
        """
        word_id = self.table.selected_id() or self._selected
        position = self._position_of(word_id)
        if position < 0:
            return
        count = _parse(self.count_var.get(), self._default_count,
                       len(self.pack.word_ids), allow_zero=True)
        self.result = (position, count)
        self.destroy()
