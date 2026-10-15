# -*- coding: utf-8 -*-
"""把"这一场考试属于哪份单词表"收敛到一处。

**为什么单独一个模块。** 这个判断有**两个**调用点,而且它们必须是同一个答案:

* 考试页收尾时要知道"结果落到哪三个包"(ui/views/exam.py);
* 考试挑词页要知道"从哪份词表的考试包里抽词"(ui/views/exam_ick.py 的加题)。

两处各写一份的话,迟早会漂移 —— 表现是"加进来的词来自 sample,
结果却落到别的词表",而且不报错。所以这里只留一份。

判断本身在 core(core/exam_group.vocab_of),这一层补的是**跨来源会话**:
勾了好几个包时没有单一来源,只能从单词表里挑命中最多的一份。
"""

from typing import Iterable, List

from core.exam_group import vocab_of as _vocab_of
from core.packs import PACK_TYPE_VOCAB


def plan_vocab_id(plan, packs: Iterable) -> str:
    """这一场考的词属于哪份单词表。认不出来返回空串。

    两种情况:
      * 勾中的是**一个**词包 → 直接问 core(它会处理学习词包、考试包
        各自指向哪份词表);
      * 勾了**好几个**(跨来源会话)→ 从所有单词表里挑命中最多的一份。
        这些词多半来自某份词表,落在那份的考试包里总比无处可落好。
    """
    pack = getattr(plan, "pack", None)
    if pack is not None:
        found = _vocab_of(pack, packs)
        if found:
            return found

    words = getattr(plan, "words", None) or []
    wanted = {word.id for word in words}
    if not wanted:
        return ""

    best, best_hits = "", 0
    for candidate in packs:
        if candidate.pack_type != PACK_TYPE_VOCAB:
            continue
        hits = len(wanted & set(candidate.word_ids))
        if hits > best_hits:
            best, best_hits = candidate.id, hits
    return best


def vocab_title(packs: Iterable, vocab_id: str,
                fallback: str = "单词表") -> str:
    """单词表的显示名。找不到时返回 fallback。

    提示语里要写「已更新「sample」的考试结果包」,所以这个名字必须有 ——
    空着会让那句话读起来像"更新了某个不知道什么东西"。
    """
    for pack in packs:
        if pack.id == vocab_id:
            return pack.title
    return fallback


def result_note(packs: Iterable, parts: List) -> str:
    """考完那一句提示:结果进了哪份词表的三个包、现在各有多少。

    **必须说清归属**,因为用户看不到磁盘上多了几个文件。不说的话,
    他下次打开列表发现考试包数量没变,反而会以为这次考试没记上。
    """
    from core.exam_group import KIND_LABELS

    if not parts:
        return ""
    title = vocab_title(packs, parts[0].group_id)
    detail = " · ".join("%s %d" % (KIND_LABELS.get(pack.kind, pack.kind),
                                   pack.word_count) for pack in parts)
    return "已更新「%s」的考试结果包:%s。" % (title, detail)


def exam_word_total(packs: Iterable, vocab_id: str) -> int:
    """这份词表的考试包里一共有多少个词(三档相加)。"""
    from core.exam_group import summary_of

    return sum(summary_of(packs, vocab_id).values())


__all__ = ["exam_word_total", "plan_vocab_id", "result_note", "vocab_title"]
