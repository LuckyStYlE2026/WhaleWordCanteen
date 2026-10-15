# -*- coding: utf-8 -*-
"""考试收尾:把这一场并进"来源单词表"名下的三个固定考试包,然后说一句。

从 ui/views/exam.py 拆出来,和 ui/study_flow.py 是同一个理由和同一个位置:
**页面负责搭界面和收按键,收尾负责结算和落盘**。考试页已经超过项目 300 行
的体积约定,而这一段和界面无关 —— 它只在"这场结束了"时被调一次。

归属判断在 ui/exam_target(和挑词页共用一份,见那里的说明);合并规则在
core/exam_group。这里只负责"存盘 + 说一句"。
"""

from typing import List, Tuple

from core import exam_group

# ⚠️ 这个文件在 ui/ 里(不是 ui/views/),所以相对 import 只用**一个点**。
# 写成 `from .. import ...` 会变成"超出顶层包",程序一启动就
# `ValueError: attempted relative import beyond top-level package` ——
# 不是某个功能坏掉,是**根本起不来**。
from . import exam_target
from .session import ORDER_SEQUENTIAL


def store_results(app, plan, session) -> Tuple[List, str]:
    """把这一场并进**来源单词表**名下那三个固定考试包。

    返回 (三档, 提示语)。

    认不出归属时**不落考试包** —— 那种词包没有坐标(比如没有 source_vocab
    的老学习词包),硬塞一个只会让它变成一个看不懂的孤儿。成绩仍然记在
    单词自己的学习状态里,所以不算白考。
    """
    vocab_id = exam_target.plan_vocab_id(plan, app.packs)
    if not vocab_id:
        app.save_words()
        return [], ("这次考试没有可归属的单词表,结果只记在单词本身的学习"
                    "状态里(没有生成考试结果包)。")

    parts = exam_group.merge_exam(
        app.packs, vocab_id, exam_target.vocab_title(app.packs, vocab_id),
        session, app.words, order=getattr(session, "order", ORDER_SEQUENTIAL))
    # 单词自己的状态(答对/答错的记忆曲线)和考试包是两笔账,都要落盘
    app.save_words()
    app.save_packs()
    return parts, exam_target.result_note(app.packs, parts)


def farewell(session, note: str) -> str:
    """考试结束后那段话。

    `note` 是 store_results 给的那句"结果落到哪儿"(可能是"已记入三个考试包",
    也可能是"这份词表认不出来,只记在单词状态里")—— 不能让文案写死成前者,
    否则认不出归属时又会说一句和事实不符的话。

    单独成函数:它是**纯文案**,不该混在"摘会话、落包、切页"那串动作里 ——
    改一句话不该碰到收尾流程。
    """
    result = session.summary()
    return ("答了 %d 个词,正确率 %.0f%%。\n\n"
            "熟词 %d 个 · 模糊词 %d 个 · 生词 %d 个\n\n"
            "%s\n\n"
            "答错的词已经记进错题本,下次会优先出现。"
            % (session.answered_count, result.score * 100,
               len(result.known), len(result.fuzzy), len(result.newly),
               note))


__all__ = ["farewell", "store_results"]
