# -*- coding: utf-8 -*-
"""词包内编辑:打开一个词表包,加 / 改 / 删里面的单词。

和单词设置页(词包列表)分开,是因为「管词包」和「改某一个词」是两件
粒度不同的事,放一个文件里两边都会变长。这一页只管一个包里的词。

单词本身仍存在全局 words_index.json 里,词包只存 id —— 所以这里的
「删除」是从这个词包摘掉 id;只有当这个词不再属于任何包时,才连
学习记录一起删,避免留下看不见的孤儿词。

新建单词走 apply_import(传 pack_id)而不是手 new 一个 Word:那条路上
有去重、有 id 分配、有拼写键归一化,绕过它两处规则迟早不一致 ——
用户加一个已存在的词,导入会把释义合并进包,手写却会凭空多出第二个。
"""

import tkinter as tk
from typing import List

from core.interfaces import RawWord
from core.pack_edit import detach_word
from core.pack_progress import (bookmark_index, clear_bookmark, progress_label,
                                set_bookmark)
from core.packs import PACK_TYPE_VOCAB
from core.textio import spelling_key
from core.wordpack_import import apply_import

from ..dialogs import WordEditor, confirm, info, warn
from ..forms import flat_button
from ..tables import WordTable
from ..widgets import ghost_button, primary_button, theme_color
from .base import View


class WordPackEditorView(View):
    """一个词表包的内部编辑页。"""

    title_text = "词包"
    subtitle_text = "包内的单词可增删改"

    def build(self) -> None:
        # 骨架先空着,on_enter 收到 pack_id 后才喂数据。
        # 这样「打开一个已被删掉的包」这种竞态能干净地退回列表。
        self.pack_id = ""
        self.table = None

    def on_enter(self, pack_id: str = "", **kwargs) -> None:
        if not pack_id:
            self.app.back_to_menu()
            return
        self.pack_id = pack_id
        self._build()

    # ---- 界面 ------------------------------------------------------------

    def _build(self) -> None:
        for child in self.winfo_children():
            child.destroy()

        pack = self._pack()
        # back=False:header 默认的「← 返回」回主菜单,而这一页要回词包列表,
        # 所以返回按钮自己摆(见下面的工具栏行)
        self.header(self, title=(pack.title if pack else "词包"),
                    subtitle="包内的单词可增删改", back=False)

        body = tk.Frame(self, bg=theme_color(self.theme, "background"))
        body.pack(fill="both", expand=True, padx=24, pady=(0, 18))

        toolbar = tk.Frame(body, bg=theme_color(self.theme, "background"))
        toolbar.pack(fill="x")
        ghost_button(toolbar, "← 词包列表", self._back,
                     self.theme).pack(side="left")
        primary_button(toolbar, "新建单词", self.on_add_word,
                       self.theme).pack(side="left", padx=14)
        flat_button(toolbar, self.theme, "修改", self.on_edit_word).pack(
            side="left", padx=6)
        flat_button(toolbar, self.theme, "删除", self.on_delete_word).pack(
            side="left")
        # 「标记此处」只给词表包 —— 结果包的进度不参与「接着上次」,
        # 给它一个标记按钮等于许下一个兑现不了的承诺
        if pack is not None and pack.pack_type == PACK_TYPE_VOCAB:
            flat_button(toolbar, self.theme, "标记此处", self.on_mark).pack(
                side="left", padx=6)

        self.table = WordTable(body, self.theme, height=16,
                               on_select=lambda _id: None)
        self.table.pack(fill="both", expand=True, pady=(8, 0))

        self.status = tk.Label(body, text="", bg=theme_color(self.theme,
                               "background"),
                               fg=theme_color(self.theme, "text_dim"),
                               font=("Microsoft YaHei UI", 9), anchor="w")
        self.status.pack(fill="x", pady=(6, 0))
        self.refresh()

    def _back(self) -> None:
        self.app.show("wordset")

    # ---- 数据 ------------------------------------------------------------

    def _pack(self):
        for pack in self.app.packs:
            if pack.id == self.pack_id:
                return pack
        return None

    def _words(self) -> List[object]:
        pack = self._pack()
        if pack is None:
            return []
        return [self.app.words[wid] for wid in pack.word_ids
                if wid in self.app.words]

    def refresh(self) -> None:
        if self.table is None:
            return
        pack = self._pack()
        marked = bookmark_index(pack) if pack is not None else -1
        rows = []
        for position, word in enumerate(self._words(), start=1):
            order = "★ %d" % position if position - 1 == marked else str(position)
            rows.append((word.id, (order, word.word, word.phonetic,
                                   word.translation, word.group)))

        # 重画会把选中状态清掉,而每次标记/修改之后都要重画 ——
        # 选回来才能"按下标记、觉得不对、再按一次取消",不然用户得摸黑再点一次。
        previous = self.table.selected_id()
        self.table.fill(rows)
        self.table.select(previous)

        # 状态栏带上"学到哪了 / 标记在哪",打开包就能看到进度
        if pack is not None:
            detail = progress_label(pack)
        else:
            detail = "共 %d 个单词" % len(rows)
        self.status.configure(text="%s · %s" % (pack.title if pack else "词包",
                                                detail))

    # ---- 操作 ------------------------------------------------------------

    def on_add_word(self) -> None:
        pack = self._pack()
        if pack is None:
            return
        editor = WordEditor(self, self.theme, title="新建单词")
        self.wait_window(editor)
        if not editor.result:
            return
        raw = RawWord(word=editor.result["word"],
                      translation=editor.result["translation"],
                      phonetic=editor.result["phonetic"],
                      example=editor.result["example"],
                      collocation=editor.result["collocation"],
                      group=editor.result["group"])
        stats, ids = apply_import(self.app.words, [raw], pack_id=pack.id,
                                  today=self.app.today(), return_ids=True)
        wid = ids[0] if ids else ""
        if wid and wid not in pack.word_ids:
            pack.word_ids.append(wid)
        self._save()
        self.refresh()
        if stats["updated"]:
            info(self, "已加入本包",
                 "词库里已有「%s」,已把它加进本包,释义更新、学习进度保留。"
                 % raw.word)

    def on_edit_word(self) -> None:
        wid = self.table.selected_id() if self.table else ""
        if not wid:
            info(self, "修改单词", "先在列表里选中一个单词。")
            return
        word = self.app.words.get(wid)
        if word is None:
            return
        values = {"word": word.word, "translation": word.translation,
                  "phonetic": word.phonetic, "example": word.example,
                  "collocation": word.collocation, "group": word.group}
        editor = WordEditor(self, self.theme, title="修改单词", values=values)
        self.wait_window(editor)
        if not editor.result:
            return
        new_key = spelling_key(editor.result["word"])
        clash = self._find_by_spelling(new_key, skip_id=wid)
        if clash is not None:
            warn(self, "拼写重复",
                 "词库里已经有「%s」了。\n\n要改的话请去那个词,而不是把它"
                 "改成一模一样的拼写。" % clash.word)
            return
        # 原地改字段,不走 apply_import —— 见模块头说明,改拼写不该丢进度
        r = editor.result
        word.word = r["word"]
        word.spelling_key = new_key
        word.translation = r["translation"]
        word.phonetic = r["phonetic"]
        word.example = r["example"]
        word.collocation = r["collocation"]
        word.group = r["group"]
        self._save()
        self.refresh()

    def on_mark(self) -> None:
        """把选中的词标成"下次从这里开始"。再按一次同一行就是取消标记。

        标记记的是**位置**不是词 id:用户脑子里想的是"学到第 347 个",
        而包里删掉一个词时位置只是整体前移一位,不像 id 那样当场失效。
        """
        pack = self._pack()
        wid = self.table.selected_id() if self.table else ""
        if pack is None or not wid:
            info(self, "标记此处", "先在列表里选中一个单词。")
            return
        if wid not in pack.word_ids:
            return

        position = pack.word_ids.index(wid)
        if bookmark_index(pack) == position:
            clear_bookmark(pack)
            title, message = "已取消标记", "这个词不再是起点了。"
        else:
            set_bookmark(pack, position)
            word = self.app.words.get(wid)
            title = "已标记"
            message = ("下次可以从这里开始:「%s」(第 %d 个)。\n\n"
                       "回到「开始」勾上这个词表包,点「开始学习」时就会"
                       "问你从哪开始。" % (word.word if word else wid,
                                           position + 1))
        self._save()
        self.refresh()
        info(self, title, message)

    def on_delete_word(self) -> None:
        wid = self.table.selected_id() if self.table else ""
        if not wid:
            info(self, "删除单词", "先在列表里选中一个单词。")
            return
        pack = self._pack()
        word = self.app.words.get(wid)
        if pack is None or word is None:
            return
        if not confirm(self, "从词包移除",
                       "把「%s」从「%s」里移除吗?\n\n"
                       "它只属于这个词包的话,学习记录会一起删掉。"
                       % (word.word, pack.title)):
            return
        detach_word(self.app.words, self.app.packs, pack, wid)
        self._save()
        self.refresh()

    # ---- helpers ---------------------------------------------------------

    def _find_by_spelling(self, key: str, skip_id: str = ""):
        for word in self.app.words.values():
            if word.id != skip_id and word.spelling_key == key:
                return word
        return None

    def _save(self) -> None:
        # 先存词库(可能新增/删除了词),再存词包(本包的 word_ids 变了)。
        # 内存里的 app.packs 才是真相来源,**不要**把它丢掉从磁盘重载 ——
        # 那样刚加进包的 id 就白加了。
        self.app.save_words()
        self.app.save_packs()
