# -*- coding: utf-8 -*-
"""一场学习结束时的收尾流程。

从学习页搬出来单独成文件,有两个理由:

  1. **两条路要走同一段代码**。"学完了"和"点返回提前结束"的区别只有
     一句提示语,结果包怎么落、进度怎么写、回到哪一页全都一样。
     留在页面里就得写两遍,两遍迟早会漂移。
  2. 学习页本来就快顶到 300 行了(见 CLAUDE.md 的体积约定)。

**为什么不给"结束"和"返回"各留一条路?** 因为单词状态是每评一个就落盘的
(见 study.on_rate),到这一步"丢弃这一场"已经无从谈起 —— 那只会让用户
觉得白学了。返回就是"结束,但回上一级"。
"""

from typing import Dict, List, Optional, Tuple

from core.config import (RESULT_PACK_MERGE, RESULT_PACK_NONE,
                         RESULT_PACK_SEPARATE)
from core.pack_edit import attach_words, find_today_result_pack
from core.packs import WordPack
from core.stats import (build_diagnosis_payload, diagnosis_text, summarize)

from .dialogs import info
from .prompts import ask_choice
from .session import MODE_EXAM, SessionPlan

# 三种处理方式各自的那句说明。键同时也是"设置里存的值"(见 core/config)。
# 「设置里存了个不认识的值」因此会自动被 _result_mode 判成"没配好",
# 而不是当成某个模式照做。
PACK_NOTES = {
    RESULT_PACK_MERGE: "已并进今天的学习词包。",
    RESULT_PACK_SEPARATE: "已单独存成一个词包。",
    RESULT_PACK_NONE: "这一场没有生成词包。",
}

RESULT_OPTIONS = [
    ("合并进当天的词包", RESULT_PACK_MERGE),
    ("单独存一个新词包", RESULT_PACK_SEPARATE),
    ("不生成词包", RESULT_PACK_NONE),
]


def finish(view, plan: SessionPlan, tally: Dict[str, int],
           early: bool = False, dest: str = "",
           graded: Optional[List] = None) -> None:
    """收尾:落结果包 → 报一句总结 → 回 dest(空 = 回主菜单)。

    graded 是**这一场真正评过**的词。收尾用它而不是 plan.words,有两个原因:

    * 用户按「结束学习」提前走人时,plan 里没看过的词不该混进结果包;
    * 学习页的「下一组 / 标记」是按组记分的,结果包就该只装那些组。

    不传(或传空)时退回 plan.words —— 考试页和别的调用方走老路。

    进度写入不在这里,由学习页自己收尾(它才是唯一知道"评价到第几个"的)。
    """
    app = view.app
    correct = int(tally.get("correct", 0))
    fuzzy = int(tally.get("fuzzy", 0))
    wrong = int(tally.get("wrong", 0))
    rated = correct + fuzzy + wrong
    words = graded if graded else list(plan.words)

    if rated == 0:
        # 一个词都没评价过 —— 不建词包也不报总结,免得留下空记录。
        # 注意判据是**成绩单**,不是 words:跳过本组之后 words 可能非空,
        # 但一个词都没打分,那种情况同样不该落包。
        view.leave(dest)
        return

    pack, mode = _store_result(view, plan, words, correct, fuzzy, wrong)

    # 告别语交给**有对话框**的页面去说。
    #
    # 这一句以前是无条件调的,于是每个调用方都得养一个 say() ——
    # 学习页这一版把对话框整个去掉了,为了不让它炸还得留一个"什么都不做"
    # 的同名方法,那是一段只为骗过调用方而存在的代码。
    # 现在由"这一页有没有对话框"决定说不说(见 ui/views/base.py 的
    # scene_dialogue),没有框的页面就跳过这一句。
    if getattr(view, "scene_dialogue", False):
        emotion, line = app.speaker.farewell(correct, rated)
        view.say(emotion, line)

    # 诊断文案用词包标题做引子;没建包(选了"不生成")就退回会话标题
    title = pack.title if pack is not None else (plan.title or "临时会话")
    detail = ("这一轮评价了 %d 个词:记住 %d,模糊 %d,没见过 %d。\n\n%s\n\n%s"
              % (rated, correct, fuzzy, wrong,
                 diagnosis(app, session_summary(app, words), title),
                 PACK_NOTES[mode]))
    if early:
        detail = "提前结束了。\n\n" + detail
    info(view, "学习完成", detail)
    view.leave(dest)


def session_summary(app, words):
    """给诊断用的**这一场**汇总。

    ⚠️ 必须抹掉两个字段,它们说的都不是"这一场":

    * **反复出错**:`WordState.is_mistake()` 看的是**累积的** wrong_count
      (错两次、或者错过一次且还没连对)。而**学习模式根本没有答错这条路**
      (「下一组」= 记住了,没有"不会"这个选项),所以一个词只要**上一次考试
      错过**,这次只是被看过一遍 —— 而"看过"不增加连对次数,它就仍然被算成
      "反复出错"。于是用户学完 20 个词,却被告知"有 N 个词你反复出错"
      (用户 2026-10-17 又报了一次,这是同一个根的另一个面)。
    * **今天到期**:那是"该复习"的提醒,属于「开始复习」那条路,不该混进
      "这一场学得怎么样"的总结里。

    这两条在学习语境下都是**翻旧账**。留下的 known / total 仍然反映真实状态
    (学完之后有几个算掌握了),所以"掌握率"那句是对的。
    """
    subset = {word.id: word for word in words if word.id in app.words}
    summary = summarize(subset, app.today())
    summary.mistakes = 0
    summary.due_today = 0
    return summary


def diagnosis(app, summary, title: str) -> str:
    """给这一场配一句评语。

    这是三个受控触发点里的第三个:**每场会话只调一次**,不是每个词一次。
    没配 API 时 chat.diagnose 会把离线文案原样返回,不会抛异常、不会联网。
    """
    offline = diagnosis_text(summary)
    return app.chat.diagnose(build_diagnosis_payload(summary, title), offline)


def ask_result_mode(parent, theme) -> str:
    """问一句这一场的结果怎么存。取消按"单独存"走。

    取消时给的是 v1.2 的老行为(每次单独落一个包):用户按了取消,
    不该因此丢掉结果包,而三选一里最不意外的就是"和以前一样"。
    """
    chosen = ask_choice(parent, theme, "这一场学完了",
                        "结果要存成词包吗?(单词的学习状态已经记好了,"
                        "这一句只决定要不要攒一个包)", RESULT_OPTIONS)
    return chosen or RESULT_PACK_SEPARATE


# ---- 内部 ----------------------------------------------------------------

def _result_mode(view) -> str:
    """这一场用哪种处理方式。

    设置里选了 ask 以外的值就不再弹窗 —— 每学完一场都弹一次会把
    "再多学一会儿"变得很烦,而这个选择本来就是用户要求"记住"的。
    """
    configured = view.app.settings.study.result_pack_mode
    if configured in PACK_NOTES:
        return configured
    return ask_result_mode(view, view.theme)


def _store_result(view, plan: SessionPlan, words: List,
                  correct: int, fuzzy: int,
                  wrong: int) -> Tuple[Optional[WordPack], str]:
    """落结果包,返回 (词包或 None, 用到的模式)。

    只装 words(这一场真正评过的词),不是 plan 里全部词 —— 见 finish 的说明。

    「合并」找的是**今天那一个**学习结果包(见 core.pack_edit):昨天的包
    和考试包都不参与,否则用户抱怨的"词包堆积"会换个形式回来。
    """
    app = view.app
    today = app.today()
    mode = _result_mode(view)
    if mode == RESULT_PACK_NONE:
        return None, mode

    target = None
    if mode == RESULT_PACK_MERGE:
        target = find_today_result_pack(app.packs, today)

    if target is None:
        pack = app.scheduler.build_study_pack(
            words, today,
            source_mode="random" if plan.mode == MODE_EXAM else "sequential",
            source_pack=plan.pack_id or None,
            # 记下"这批词是从哪份单词表学来的" —— 以后考这些词,结果要落到
            # 那份单词表名下的三个考试包里(见 core/exam_group.vocab_of)
            source_vocab=_source_vocab(app, plan))
        app.packs.append(pack)
    else:
        pack = target
        attach_words(pack, words)

    app.scheduler.record_session(pack, today, correct, fuzzy, wrong)
    app.save_packs()
    return pack, mode


def _source_vocab(app, plan: SessionPlan) -> str:
    """这一场学的词属于哪份单词表。认不出来返回空串。

    只勾了一个词包时,plan.pack 就是它,直接问 core 要答案;
    跨来源会话(今日复习那种)勾了好几个包,plan.pack 是空的 ——
    这时从**单词表**里挑一份:这些词多半来自某个词表,
    落在那份的考试包里总比无处可落好。都没有就空着。
    """
    from core.exam_group import vocab_of
    from core.packs import PACK_TYPE_VOCAB

    if plan.pack is not None:
        found = vocab_of(plan.pack, app.packs)
        if found:
            return found

    wanted = {word.id for word in plan.words}
    best, best_hits = "", 0
    for pack in app.packs:
        if pack.pack_type != PACK_TYPE_VOCAB:
            continue
        hits = len(wanted & set(pack.word_ids))
        if hits > best_hits:
            best, best_hits = pack.id, hits
    return best
