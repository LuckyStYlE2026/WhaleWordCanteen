# -*- coding: utf-8 -*-
"""词表包的学习进度与书签:切范围、记进度、设标记。

单拎一个文件,而不是塞进 pack_edit.py:那边管的是"词包里有几个词"
(增删改),这边管的是"这个词包学到哪了"(位置)。两边的调用方也不同 ——
编辑页改词,学习页读位置,混在一个文件里改一边得把另一边也读一遍。

**显示一律 +1。** 存储用 0 起的下标(切片要它),而界面上说的"第 347 个"
指的是 `word_ids[346]`。这个换算只在本模块里做一次,
别的地方(弹窗、状态栏)一律只拿算好的文字或位置,不许再自己减一。
"""

from typing import List, Tuple

from .models import Word
from .packs import WordPack


def clamp_index(pack: WordPack, index: int) -> int:
    """把位置夹进 `0..词数` 的合法范围。

    上界是**词数**而不是"词数 - 1":`next_index` 的语义是"下次从第几个
    开始学",学完最后一个词之后它正好等于词数,表示"这一包学到头了"。
    如果按"词数 - 1"夹,那个状态就没地方放了。
    """
    return max(0, min(int(index), len(pack.word_ids)))


def bookmark_index(pack: WordPack) -> int:
    """标记的位置,-1 表示没标记过。

    读的时候顺手夹一次:标记是用户点出来的,但存档可能被手工改大,
    与其在各个调用方到处判断越界,不如在这一处收敛。
    """
    if pack.progress.bookmark < 0:
        return -1
    return clamp_index(pack, pack.progress.bookmark)


def study_range(pack: WordPack, start: int, count: int) -> Tuple[int, List[str]]:
    """切出这一轮要学的 word_ids,返回 (实际起点, id 列表)。

    起点越界一律夹回合法范围,**不报错**:起点是用户自己填的数字,
    "填了 9999"该看到的是"没有更多词了"或"从头开始",不是一个错误框。
    `count <= 0` 表示学到包尾 —— 设置里"每次学习数量"填 0 就是这个意思。
    """
    total = len(pack.word_ids)
    begin = clamp_index(pack, start)
    end = total if count <= 0 else min(begin + int(count), total)
    return begin, list(pack.word_ids[begin:end])


def note_words(pack: WordPack, noted: int, words: List[Word]) -> int:
    """把"进度推到这批词之后",返回新的位置。

    按**词在包里的位置**算,不按"这一屏是第几屏":学习页的分屏会把同一组合
    的词拉到一起(见 ui/session.group_pages),屏序和包里的先后并不一致,
    按屏号累加会一路算到错的词头上,而且看不出错。

    跳过本组的那些词不在 words 里,所以进度不会越过它们 —— 这是对的:
    没评价过的词不算学过。words 里不属于这个词包的 id 一律忽略。
    """
    positions = [pack.word_ids.index(word.id) + 1
                 for word in words if word.id in pack.word_ids]
    return max([noted] + positions)


def record_progress(pack: WordPack, next_index: int) -> None:
    """把"下次从第几个开始"记到词包上。

    **只允许往前推,不允许倒退。** 用户回头复习前面的部分是常事
    (点一次"从头开始"再看一遍),那不该把进度打回第一课 ——
    否则「接着上次」会莫名其妙地永远停在原地,而且用户看不出是为什么。
    """
    target = clamp_index(pack, next_index)
    if target > pack.progress.next_index:
        pack.progress.next_index = target


def set_bookmark(pack: WordPack, index: int) -> None:
    """把书签设在第几个词上。"""
    pack.progress.bookmark = clamp_index(pack, index)


def clear_bookmark(pack: WordPack) -> None:
    """取消标记。"""
    pack.progress.bookmark = -1


def progress_label(pack: WordPack) -> str:
    """给状态栏用的一句话,例如:

        标记在第 347 个 · 下次从第 348 个开始 · 共 1000 个单词

    没标记 / 没进度时对应的那一段就不出现 —— 一行里塞三个"无"的提示
    比不提示更让人迷惑。
    """
    total = len(pack.word_ids)
    parts: List[str] = []
    position = clamp_index(pack, pack.progress.next_index)
    if total and position >= total:
        parts.append("这一包已经学到头了")
    elif position > 0:
        parts.append("下次从第 %d 个开始" % (position + 1))

    mark = bookmark_index(pack)
    if mark >= 0:
        parts.append("标记在第 %d 个" % (mark + 1))

    parts.append("共 %d 个单词" % total)
    return " · ".join(parts)
