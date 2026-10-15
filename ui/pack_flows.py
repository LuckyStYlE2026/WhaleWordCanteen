# -*- coding: utf-8 -*-
"""新建词包的界面流程:导入文件 / 逐条填 / 粘贴多行。

从 ui/views/wordset.py 拆出来,理由和 export_flow.py 一样:这段流程
**不认识"单词设置"这个页面**,给它一个宿主窗口就行 —— 它只需要
view.app(数据)、view.theme(配色)和 view.refresh()(建完刷新列表)。

两个流程都遵守同一条存储规矩:**先 append 进内存列表,再落盘**。
反过来(先 save_pack 再 append)有个坑:如果 app.packs 的缓存恰好是空的,
读它会先从磁盘重载,刚存的那个包就被读回来加第二遍了。
"""

from pathlib import Path
from tkinter import filedialog
from typing import List

from core import storage
from core.packs import PACK_TYPE_VOCAB, make_vocab_pack
from core.paths import wordlist_dir
from core.wordpack_import import apply_import, import_as_pack, parse_plain_lines

from .dialogs import info
from .prompts import ask_choice, ask_text, ask_text_block

# 新建词包可选的录入方式。(显示文字, 内部值)
# 留成清单而不是写死 if/else,是为了将来加第三种方式只改这一处。
CREATE_METHODS = [
    ("逐条填(一条一条录入)", "form"),
    ("粘贴多行文本(单词<TAB>翻译)", "paste"),
]


def run_import(view) -> None:
    """选文件 → 每个文件建一个词表包。整批做完再报一次结果。"""
    paths = filedialog.askopenfilenames(
        parent=view, title="选择词表文件",
        initialdir=str(wordlist_dir()),
        filetypes=[("词表文件", "*.txt *.csv *.json"), ("全部文件", "*.*")])
    if not paths:
        return

    app = view.app
    today = app.today()
    added = updated = skipped = 0
    problems = []
    # 只取一次缓存列表,后面都往它里面加 —— 见模块开头说的那个坑
    packs = app.packs
    for raw_path in paths:
        path = Path(raw_path)
        pack_id = storage.new_pack_id(PACK_TYPE_VOCAB, today)
        pack, result, stats = import_as_pack(app.words, path, pack_id, today)
        if not result.words:
            problems.append("%s: %s" % (path.name,
                                        result.errors[0].message
                                        if result.errors
                                        else "没有读到任何词条"))
            continue
        # 先落盘:下一个 new_pack_id 要扫磁盘才知道这个 id 已被占
        storage.save_pack(pack)
        packs.append(pack)
        added += stats["added"]
        updated += stats["updated"]
        skipped += stats["skipped"]
        for row_error in result.errors:
            problems.append("%s 第 %d 行:%s"
                            % (path.name, row_error.line, row_error.message))

    app.save_words()
    app.save_packs()
    view.refresh()

    message = "新增 %d 个,更新 %d 个" % (added, updated)
    if skipped:
        message += ",跳过 %d 个(单词为空)" % skipped
    if updated:
        message += "\n\n已经存在的单词只更新释义,学习进度保留。"
    if problems:
        message += "\n\n有 %d 行没能读进来:\n%s" % (
            len(problems), "\n".join(problems[:8]))
    info(view, "导入完成", message)


def run_new_pack(view) -> None:
    """问名字 → 问录入方式 → 建包。"""
    name = ask_text(view, view.theme, "新建词包", "词包名字:")
    if not name or not name.strip():
        return
    name = name.strip()
    method = ask_choice(view, view.theme, "新建词包", "怎么录入单词?",
                        CREATE_METHODS)
    if method is None:
        return

    app = view.app
    today = app.today()
    pack_id = storage.new_pack_id(PACK_TYPE_VOCAB, today)
    word_ids = []
    if method == "paste":
        word_ids = create_by_paste(view, pack_id, today)
        if not word_ids:
            info(view, "新建词包", "没识别到任何词,词包未创建。")
            return

    pack = make_vocab_pack(pack_id, name, word_ids, today.isoformat())
    app.packs.append(pack)
    app.save_words()
    app.save_packs()
    view.refresh()

    if method == "paste":
        info(view, "新建词包",
             "「%s」建好了,共 %d 个词。" % (name, len(word_ids)))
    else:
        # 逐条填:进包内编辑,用户在那里一条一条加
        info(view, "新建词包", "「%s」建好了,进去一条条加吧。" % name)
        app.show("wordpack_editor", pack_id=pack.id)


def create_by_paste(view, pack_id: str, today) -> List[str]:
    """弹一个多行粘贴框,把文本切成单词写进词库,返回新词的 id。

    切分走 core/textio 里那份和"导入文件"**完全相同**的逻辑 ——
    两处各写一份的话,粘贴能认的格式和导入能认的格式迟早会不一样。
    """
    text = ask_text_block(view, view.theme, "粘贴词表",
                          "每行一个,格式「单词<TAB>翻译」"
                          "或「单词 翻译」:")
    if text is None:
        return []
    result = parse_plain_lines(text.splitlines())
    if not result.words:
        if result.errors:
            info(view, "没识别到词", result.errors[0].message)
        return []
    _, ids = apply_import(view.app.words, result.words, pack_id=pack_id,
                          today=today, return_ids=True)
    # 粘贴的文本里可能有重复拼写,去重保序,免得一个词在包里出现两次
    return list(dict.fromkeys(ids))
