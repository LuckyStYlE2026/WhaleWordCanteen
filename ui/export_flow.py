# -*- coding: utf-8 -*-
"""导出的界面流程:问格式 → 问存哪儿 → 写盘 → 报告结果。

从 ui/views/wordset.py 拆出来的。拆的理由不是"那个文件太长了"这么简单:
这段流程**完全不认识"单词设置"这个页面** —— 给它一串 Word 和一个宿主窗口
就行。凡是这样的东西,留在页面里都会让页面显得比它实际复杂。

格式列表直接来自注册表(见 core/wordpack_export.py),
所以插件注册的导出格式会跟内置的并排出现在这个对话框里,
而这一整个文件不需要为插件改一行。
"""

import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog
from typing import List, Optional, Tuple

from core.models import Word
from core.paths import wordlist_dir
from core.wordpack_export import available_exporters, export_all, export_with

from .dialogs import error, info
from .prompts import ask_choice

# 格式选择列表里"全部格式"那一项的内部值。
# 用一个不可能和导出器重名的字符串 —— 导出器名都是英文单词。
EXPORT_ALL = "__all__"


def ask_and_export(parent: tk.Misc, theme, words: List[Word]) -> None:
    """问用户要什么格式、存到哪儿,然后写出去。用户取消就什么都不做。"""
    choice = ask_choice(parent, theme, "导出", "导出成什么格式?",
                        _format_options())
    if choice is None:
        return

    target = _ask_path(parent)
    if target is None:
        return

    try:
        if choice == EXPORT_ALL:
            written = export_all(words, target)
        else:
            written = [export_with(words, choice, target)]
    except OSError as exc:
        error(parent, "导出失败", "写文件时出错:%s" % exc)
        return

    info(parent, "导出完成",
         "导出了 %d 个单词:\n\n%s"
         % (len(words), "\n".join(str(item) for item in written)))


def _format_options() -> List[Tuple[str, str]]:
    """格式选择列表。

    只有一种格式时不追加"全部格式" —— 那个选项会变成和上面那一项
    完全等价的废话。
    """
    options = available_exporters()
    if len(options) > 1:
        options = options + [("全部格式(每个都写一份)", EXPORT_ALL)]
    return options


def _ask_path(parent: tk.Misc) -> Optional[Path]:
    """问用户存到哪儿。取消返回 None。

    默认文件名**不带后缀** —— 加什么后缀由导出器自己决定
    (见 core/interfaces.py 里 WordPackExporter.export 的说明)。
    所以用户在保存对话框里打一个名字就够了。
    """
    chosen = filedialog.asksaveasfilename(
        parent=parent, title="导出到", initialdir=str(wordlist_dir()),
        initialfile="词表_%s" % date.today().strftime("%Y%m%d"),
        filetypes=[("词表文件", "*.*")])
    return Path(chosen) if chosen else None
