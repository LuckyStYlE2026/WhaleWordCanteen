# -*- coding: utf-8 -*-
"""学习页那一行标题的文字。

从 ui/views/study.py 拆出来,原因是那一页已经快顶到 300 行的体积约定,
而"标题怎么写"是**纯字符串逻辑**:它只认识"这一屏有哪几个词、一共几屏、
标记落在哪",不认识任何控件 —— 所以能单独读、也能脱离窗口测。

三个模板合起来说清三件事(见下面各自的说明):
谁(组合名 / 第几组)、多少(几个词)、以及**这是这个组合的第几段**。
"""

from typing import List

PAGE_TITLE_GROUPED = "组合 %s · %d 个词"
PAGE_TITLE_PLAIN = "第 %d 组 · %d 个词"
MARKED_TITLE = "%s  ·  ★ 标记在第 %d 个"
# 组合被切开时用这个。只写"组合 1 · 5 个词"会让人以为这个组合一共就 5 个词;
# 写成"第 1/3 段"才说清了"后面还有"。
GROUP_PART = "%s · 第 %d/%d 段 · %d 个词"


def group_name_of(word) -> str:
    """这个词属于哪个组合。没组合返回空串。"""
    return (word.group or "").strip()


def page_title(words: List, pages: List[List], page_index: int,
               page_size: int, mark_position: int = 0) -> str:
    """这一屏的标题。

    words        这一屏的词
    pages        全部屏(用来数"这个组合已经出现过几屏")
    page_index   当前是第几屏(0 起)
    page_size    一屏几个词(算出这个组合一共几段)
    mark_position 书签落在这一屏的第几个词(0 表示不在这一屏)
    """
    if not words:
        return ""

    group_name = group_name_of(words[0])
    if not group_name:
        title = PAGE_TITLE_PLAIN % (page_index + 1, len(words))
    else:
        total = sum(1 for word in _flatten(pages) if group_name_of(word) == group_name)
        if total > len(words) and page_size > 0:
            part = _part_of(pages, page_index, group_name)
            parts = max(1, -(-total // page_size))
            title = GROUP_PART % (group_name, part, parts, len(words))
        else:
            title = PAGE_TITLE_GROUPED % (group_name, len(words))

    if mark_position > 0:
        title = MARKED_TITLE % (title, mark_position)
    return title


def _flatten(pages: List[List]) -> List:
    """所有屏合起来(为了数"这个组合一共有几个词")。

    数的是**屏里实际出现的词**,不是 plan 里的 —— 两者应当一致,
    但屏是唯一被显示的东西,按它数才不会出现"标题说 13 个、
    实际只翻得出 10 个"这种自相矛盾。
    """
    return [word for page in pages for word in page]


def _part_of(pages: List[List], page_index: int, group_name: str) -> int:
    """当前这一屏是这个组合的第几段(1 起)。"""
    seen = 0
    for index in range(page_index + 1):
        page = pages[index]
        if page and group_name_of(page[0]) == group_name:
            seen += 1
    return max(1, seen)


__all__ = ["GROUP_PART", "MARKED_TITLE", "PAGE_TITLE_GROUPED",
           "PAGE_TITLE_PLAIN", "group_name_of", "page_title"]
