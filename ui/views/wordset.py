# -*- coding: utf-8 -*-
"""单词设置:管理词包(导入 / 制作 / 重命名 / 删除 / 导出)。

第一版这里是全局散表,改一个词要在几百行里翻。现在以**词包**为单位:
导入一个文件 = 建一个词包,包里的词要增删改就点「打开」进包内编辑
(见 wordpack_editor.py)。

**这一页列出全部词包,不只是你导入的。** 学习、考试跑完会自动攒出
结果包,它们以前只出现在「开始」页,在别处看不见 —— 于是只进不出,
越堆越多还删不掉。管理词包的地方就该能管所有的词包,所以两组都列在这里。

存储不变:词仍全局存在 words_index.json,词包只存 word_ids ——
所以「删整个词包」会把它独有的词连记录一起删,共用词只摘引用。
结果包的词基本都和来源词表包共用,所以删结果包通常只摘引用、
不会碰到学习记录。

导入与新建的流程在 ui/pack_flows.py —— 那两段不认识这一页,只借它当宿主。
"""

import tkinter as tk
from typing import List

from core import storage
from core import exam_group
from core.pack_edit import remove_pack_and_children
from core.packs import PACK_TYPE_VOCAB

from ..dialogs import confirm, info
from ..export_flow import ask_and_export
from ..forms import flat_button
from ..lists import SelectableTextList
from ..pack_flows import run_import, run_new_pack
from ..prompts import ask_text
from ..widgets import primary_button, theme_color
from .base import View


class WordSetView(View):
    """词包列表页。"""

    title_text = "单词设置"
    subtitle_text = "导入、制作、管理你的词包"

    def build(self) -> None:
        self.refresh()

    # ---- 界面 ------------------------------------------------------------

    def refresh(self) -> None:
        """重建整页。词包列表变了就调它。"""
        for child in self.winfo_children():
            child.destroy()
        self.header(self)
        body = tk.Frame(self, bg=theme_color(self.theme, "background"))
        body.pack(fill="both", expand=True, padx=24, pady=(0, 18))

        self._build_toolbar(body)
        self._build_list(body)
        self._build_actions(body)

    def _build_toolbar(self, parent: tk.Misc) -> None:
        bar = tk.Frame(parent, bg=theme_color(self.theme, "background"))
        bar.pack(fill="x")
        primary_button(bar, "导入词表", lambda: run_import(self),
                       self.theme).pack(side="left")
        flat_button(bar, self.theme, "新建词包",
                    lambda: run_new_pack(self)).pack(side="left", padx=8)

    def _build_list(self, parent: tk.Misc) -> None:
        self.pack_list = SelectableTextList(
            parent, self.theme, on_select=lambda _id: None, height=14,
            empty_text="还没有词包。点上面的「导入词表」或「新建词包」开始。")
        self.pack_list.pack(fill="both", expand=True, pady=(10, 0))
        self._fill_list()

    def _build_actions(self, parent: tk.Misc) -> None:
        bar = tk.Frame(parent, bg=theme_color(self.theme, "background"))
        bar.pack(fill="x", pady=(8, 0))
        flat_button(bar, self.theme, "打开", self.on_open).pack(side="left")
        flat_button(bar, self.theme, "重命名",
                    self.on_rename).pack(side="left", padx=6)
        flat_button(bar, self.theme, "删除",
                    self.on_delete_pack).pack(side="left")
        flat_button(bar, self.theme, "导出",
                    self.on_export).pack(side="left", padx=6)

    def _fill_list(self) -> None:
        groups = []
        for title, packs in self._packs_by_group():
            if packs:
                groups.append((title, [(p.id, p.title, self._row_subtitle(p))
                                       for p in packs]))
        self.pack_list.fill(groups)

    def _row_subtitle(self, pack) -> str:
        """一行小字:多少词、建于何时。结果包再补一句它是怎么来的。

        结果包只写"建于 10-12"会让人以为是词表包,所以补上类型 ——
        这一页现在两类包都在,不区分的话用户不敢删。
        """
        parts = ["%d 个词" % pack.word_count,
                 "建于 %s" % (pack.created_at or "未知")]
        if pack.pack_type != PACK_TYPE_VOCAB:
            parts.append("学习/考试产生的结果包")
        if pack.schedule.recommended_next:
            parts.append("建议下次 %s" % pack.schedule.recommended_next)
        return " · ".join(parts)

    # ---- 数据 ------------------------------------------------------------

    def _packs_by_group(self) -> List[tuple]:
        """全部词包,分两组:用户导入的词表 vs 学习/考试结果。"""
        vocab, results = [], []
        for pack in self.app.packs:
            (vocab if pack.pack_type == PACK_TYPE_VOCAB else results).append(pack)
        return [("我的词表", vocab), ("学习/考试结果", results)]

    def _selected_pack(self):
        if not hasattr(self, "pack_list"):
            return None
        sid = self.pack_list.selected_id()
        if not sid:
            return None
        for pack in self.app.packs:
            if pack.id == sid:
                return pack
        return None

    # ---- 词包级操作 ------------------------------------------------------

    def on_open(self) -> None:
        pack = self._require_pack("打开词包")
        if pack is None:
            return
        self.app.show("wordpack_editor", pack_id=pack.id)

    def on_rename(self) -> None:
        pack = self._require_pack("重命名")
        if pack is None:
            return
        name = ask_text(self, self.theme, "重命名", "新名字:", pack.title)
        if name is None or not name.strip():
            return
        pack.title = name.strip()
        # 单词表改名时,它名下三个考试结果包的标题要跟上 ——
        # 它们叫「某某考试·掌握」,里面带着词表名。不跟着改的话,用户改完
        # 名字会看到三个还叫着旧名字的包,像是没删干净。
        exam_group.retitle(self.app.packs, pack.id, pack.title)
        self._save_packs()
        self._fill_list()

    def on_delete_pack(self) -> None:
        pack = self._require_pack("删除词包")
        if pack is None:
            return
        if not confirm(self, "删除词包",
                       "确定删除「%s」吗?\n\n"
                       "它独有的词会连同学习记录一起删掉;和别的词包共用的词"
                       "只摘掉引用。" % pack.title):
            return
        self._delete_pack(pack)
        self.app.save_words()
        self._save_packs()
        self.refresh()

    def _delete_pack(self, pack) -> None:
        """摘掉本包对每个词的引用,删掉词包文件,再从内存列表移除。

        必须真的删文件 —— 只从内存列表里移除的话,下次从磁盘重载
        (重启、或任何一次 invalidate)它又会冒出来,表现成"删不掉"。

        删单词表时**连它名下的三个考试结果包一起删**:那些包是它的子包
        (见 core/exam_group.py),父包没了它们就没有出处,标题里的
        「某某考试·」也不再有任何含义。
        """
        children = remove_pack_and_children(self.app.words, self.app.packs, pack)
        storage.delete_pack(pack.id)
        for child in children:
            storage.delete_pack(child.id)
        if children:
            self._deleted_children = len(children)

    def on_export(self) -> None:
        pack = self._require_pack("导出")
        if pack is None:
            return
        words = [self.app.words[wid] for wid in pack.word_ids
                 if wid in self.app.words]
        if not words:
            info(self, "导出", "这个包是空的。")
            return
        ask_and_export(self, self.theme, words)

    # ---- helpers ---------------------------------------------------------

    def _require_pack(self, action: str):
        """拿到当前选中的词包,没选就提示一句。"""
        pack = self._selected_pack()
        if pack is None:
            info(self, action, "先在列表里选一个词包。")
        return pack

    def _save_packs(self) -> None:
        # 只落盘,不 invalidate —— 内存里的 app.packs 才是真相来源,
        # invalidate 会把它丢弃并从磁盘重载,那样刚改的标题/词表就没了
        self.app.save_packs()
