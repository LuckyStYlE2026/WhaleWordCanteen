# -*- coding: utf-8 -*-
"""学习页对**这一场学习**做的动作:记分、标书签、推进度。

**为什么从页面里拆出来。** 这几件事只认"词、词包、调度器",不认任何控件 ——
放在学习页里,那一页就同时装着"版面怎么摆"和"学习状态怎么变",
而后者才是这个软件的核心逻辑,值得单独读、单独测。

页面负责的是"什么时候调它"(按了哪个按钮),这里负责"调了之后世界变成什么样"。

一条贯穿的规矩:**这里所有函数都不碰控件、不弹窗**,只改数据并返回结果。
所以它们可以脱离图形环境测(见 tests/test_study_flow.py 里的纯逻辑用例)。
"""

from typing import List

from core import tally as tally_module
from core.models import Grade, Word
from core.pack_progress import bookmark_index, note_words, record_progress, set_bookmark
from core.packs import PACK_TYPE_VOCAB


def grade_words(app, words: List[Word], grade: Grade) -> None:
    """把一批词按同一个分档记分并存盘。

    学习页是**一组一起评**的:规格说同组的词"一起出现",评价自然也一起给 ——
    分开评价的话,用户在学新词时还没有任何依据去区分同组的几个词。
    """
    today = app.today()
    for word in words:
        word.state = app.scheduler.grade(word.state, grade, today)
    app.save_words()


def advance_progress(plan, noted: int, words: List[Word]) -> int:
    """把"下次从第几个接着学"推到这批词之后,返回新位置。

    只给**词表包**记:跨来源会话没有"第几个"这个坐标,而结果包(study/exam)
    是产物,不参与"接着上次" —— 它下面的词都属于某个词表包,在那边的进度里
    已经算过了。不记的时候原样返回,调用方那次写回也就是个空操作。
    """
    pack = plan.pack
    if pack is None or pack.pack_type != PACK_TYPE_VOCAB:
        return noted
    return note_words(pack, noted, words)


def commit_progress(app, plan, next_index: int) -> None:
    """把进度写回词包。

    record_progress 只前进不后退(见 core/pack_progress),所以重复调是安全的 ——
    用户回头复习前面的部分不会把进度打回去。
    """
    if plan.pack is None:
        return
    record_progress(plan.pack, next_index)
    app.save_packs()


def mark_position(plan, words: List[Word]) -> int:
    """这一组最后一个词是不是书签所在处。返回 **1 起**的位置,0 表示不是。

    判据是"这一组最后一个词在包里的位置 == 书签位置":书签只有一个,
    而组是按顺序过的,所以这个等式足以说明"标记的就是这一组"。
    显示一律 +1(见 core/pack_progress 开头的约定),越界由 bookmark_index 夹。
    """
    pack = plan.pack
    if pack is None or pack.pack_type != PACK_TYPE_VOCAB or not words:
        return 0
    last = words[-1]
    if last.id not in pack.word_ids:
        return 0
    position = pack.word_ids.index(last.id)
    return position + 1 if bookmark_index(pack) == position else 0


def toggle_bookmark(app, plan, words: List[Word]) -> bool:
    """把书签设到这一组的最后一个词上,已经是它就取消。返回"现在标记了吗"。

    和词包编辑页的「标记此处」是**同一个书签**(pack.progress.bookmark),
    所以两边天然联动:这里按一下,去编辑页能看到 ★。

    取消时只摘书签,**不撤销已经记下的学习状态** —— 用户只是不想让它当起点了,
    不是要否认刚学过的词。
    """
    pack = plan.pack
    if pack is None or pack.pack_type != PACK_TYPE_VOCAB or not words:
        return False

    if mark_position(plan, words) > 0:
        pack.progress.bookmark = -1
        app.save_packs()
        return False

    last = words[-1]
    if last.id in pack.word_ids:
        # 书签记的是**位置**不是词 id:用户想的是"学到第 347 个",
        # 而包里删掉一个词时位置只是前移一位(理由见 core/pack_progress)
        set_bookmark(pack, pack.word_ids.index(last.id))
    app.save_packs()
    return True


def add_to_tally(tally: dict, grade: Grade, count: int) -> None:
    """成绩单加一笔(转手 core.tally,让页面不必 import 那个模块)。"""
    tally_module.add(tally, grade, count)


def has_grades(tally: dict) -> bool:
    return tally_module.total(tally) > 0


# --------------------------------------------------------------------------
# 一屏的翻页语义
# --------------------------------------------------------------------------
#
# 学习页那四个翻页动作各自"记什么"是这一版的**规则**,不是排版细节,
# 所以放在这里而不是页面里 —— 页面只管接按钮和重画。

def grade_page(app, plan, state, words: List[Word], grade: Grade) -> None:
    """给这一屏的词记分、累进成绩单、推进度。

    state 是页面的那几个计数器(有 tally / graded / progress_to)。
    做成"传一个状态对象"而不是让页面自己拼这四步,是为了让**顺序和口径**
    只有一份 —— 少记一步、或者记两遍,都会静默出错。
    """
    grade_words(app, words, grade)
    add_to_tally(state.tally, grade, len(words))
    # 结果包只收**真正评过**的词 —— 见 ui/study_flow.finish 的说明
    state.graded.extend(words)
    state.progress_to = advance_progress(plan, state.progress_to, words)


def commit_current_page(app, plan, state, pages, page_index: int) -> bool:
    """把**当前这一屏**也记成"记住了",返回有没有真记。

    ⚠️ **这是用户 2026-10-15 报的那个 bug 的修法。**「下一组」是
    "先给这一屏记分、再翻页",所以用户**正在看的那一屏从没被记过** ——
    他在这一屏上点「结束」,这一屏的词就白看了:

        20 词,点一次下一组然后结束,应当保存 10 词,实际只保存 5 词。

    为什么按「记住了」记:「下一组」的含义就是"这一屏我记住了",
    而用户在这一屏**停留过**。同一批词不该因为"点结束还是点下一组"
    有两种结局。

    「跳过本组」不在此列 —— 它明确表示"我还没准备好评价它",
    点完已经翻页,不会停在那一屏上。
    """
    if not pages or page_index >= len(pages):
        return False
    words = pages[page_index]
    if not words:
        return False
    # 已经记过的不要记第二遍(同一个词被评两次会让 box 跳两级)
    already = {word.id for word in state.graded}
    if all(word.id in already for word in words):
        return False
    grade_page(app, plan, state, words, Grade.CORRECT)
    return True
