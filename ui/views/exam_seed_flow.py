# -*- coding: utf-8 -*-
"""随机考试的"加考试词"这一层:问一句、把抽出来的词混进这一场。

从 ui/views/exam_pick.py 拆出来 —— 那一页同时装着三道闸(词量、顺序、加词),
已经超过 300 行的体积约定;而"加词"这一支是**独立的一小段流程**:
它问、它抽、它追加,和另外两道闸没有耦合。

**它只在子集范围时才有意义。** 勾整份单词表时,那些错词本来就在范围里,
再抽一遍等于把同一个词考第二次 —— 所以整表时不问也不加
(用户 2026-10-16 的要求)。
"""

from typing import List

from core.exam_seed import seed_words

# ⚠️ 用**模块**引用而不是 `from ..dialogs import info`。
#
# 直接 import 名字的话,这个模块拿到的是"当时那个函数对象";而测试(以及
# 将来任何替换对话框的地方)改的是 `exam_seed_flow.info`,那个赋值**不会**
# 影响这里的旧引用 —— 于是测试里会弹出真弹窗,把测试静默**卡死**
# (不是失败,是卡住:Tk 的模态框在等一个永远不会来的点击,看起来像死循环)。
# 走 `dialogs.info(...)` 就没有这个问题。
from .. import dialogs
from ..prompts import ask_choice
from .. import exam_pick_text as text


def ask_and_mix(view, plan, vocab_id: str, available: int,
                summary: str) -> bool:
    """问一句要不要加考试词,要就抽一批混进 plan.words。

    view        调 `dialogs.info` / `ask_choice` 用的宿主控件
    plan        这一场的计划(会就地改它的 words)
    vocab_id    这份单词表的 id(考试词包挂在它名下)
    available   考试词包里一共有多少词(0 表示还没考过)
    summary     考试词包的一行小字,例如「掌握 12 · 错题 4」

    返回 False 表示用户取消了(调用方**不要发车**)。
    """
    if not vocab_id:
        # 认不出归属(比如勾的是没有来源的老学习词包)就没有考试词可抽。
        # 这时**不问** —— 问一个注定没结果的选项比不问更糟。
        return True

    if not available:
        dialogs.info(view, "还没有考试词",
             "这份词表还没有考过,所以没有「掌握 / 模糊 / 错题」可抽。\n\n"
             "先考一次,以后的随机考试就能把薄弱词随机混进来了。")
        return True

    chosen = ask_choice(
        view, view.theme, "随机考试",
        "这份词表的考试词包里有 %d 个词:\n%s\n\n"
        "要不要随机抽一批混进这一场?" % (available, summary),
        text.SEED_OPTIONS, initial=text.SEED_NONE)
    if chosen is None:
        return False
    if chosen == text.SEED_ALL:
        mix_in(view, plan, vocab_id)
    return True


def mix_in(view, plan, vocab_id: str) -> List:
    """按 3 : 4 : 5 抽一批考试词,追加到这一场,返回加进去的那些词。

    **追加而不是替换**:用户勾的那些词才是这一场的主体,考试词是加料 ——
    所以加题量取"这一场题量的一半",再受设置里的「随机加题上限」约束
    (那是这个设置项现在**唯一**的用途;考试题量本身不受它影响)。

    抽出来的词本来就来自随机抽样,顺序上是乱的;已经在这一场里的不重复加
    (同一个词考两次等于多扣一次分)。
    """
    want = max(1, int(len(plan.words) * text.SEED_SHARE))
    cap = int(getattr(view.app.settings.study, "exam_size", 0) or 0)
    if cap > 0:
        want = min(want, cap)
    picked = seed_words(view.app.packs, vocab_id, view.app.words, want)
    existing = {word.id for word in plan.words}
    fresh = [word for word in picked if word.id not in existing]
    plan.words.extend(fresh)
    return fresh


__all__ = ["ask_and_mix", "mix_in"]
