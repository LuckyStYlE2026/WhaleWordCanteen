# -*- coding: utf-8 -*-
"""考试结果包:**一个单词表恰好三个固定包**,跨场次累加,不随日期增长。

    我的词表                     ← 单词表(vocab),用户导入的
      ├── 2026-10-14 学习词包        ← 学习产生的(天天都可能多一个)
      └── 我的词表考试·掌握          ┐
          我的词表考试·模糊          ├ 考试结果,固定三个,永远只有三个
          我的词表考试·错题          ┘

**为什么挂在单词表下,而不是按日期。** 上一版一天一组三档。用户 2026-10-14
指出的问题是:真正会随时间增长的是**学习词包**(每天学一批就多一个),
考试结果不该跟着长 —— 他想看的是"这份词表里,现在哪些掌握了、哪些还错"。
所以以单词表为坐标:一份词表三个包,考多少次都还是这三个,名字直接说清
归属(「我的词表考试·错题」)。

**以这一场的结果为准,可升可降。** 答对了就从「错题」挪到「掌握」。
上一版用"当天最差归位",那在"一天一张快照"的语义下是对的;现在包的语义
是"**这份词表现在是什么状态**",状态必须能升能降 —— 否则用户答对之后会一直
挂在错题里,那个错题包就再也不代表"我现在不会的词"了。

**不参与记忆曲线。** 它的词和单词表 / 学习词包里的词是同一个 `Word` 对象
(状态只有一份,见 core/packs.py 开头),该复习的会被那些包排上;再给它排
一遍,同一个词会在「今日复习」里出现两次,复习量虚高。判据见 `is_reviewable()`。

**级联删除。** 单词表被删时这三个包一起删 —— 子包脱离父包就没有出处了。
"""

from datetime import date
from typing import Dict, Iterable, List, Optional

from .models import BUCKET_FUZZY, BUCKET_KNOWN, BUCKET_NEW, Word
from .packs import (
    PACK_KINDS,
    PACK_KIND_FUZZY,
    PACK_KIND_KNOWN,
    PACK_KIND_WRONG,
    PACK_TYPE_EXAM,
    PACK_TYPE_STUDY,
    PACK_TYPE_VOCAB,
    WordPack,
)

# 显示用的中文。放在 core 是因为**它也是标题的一部分**(标题要能独立读),
# 界面拿到的就是完整标题,不必再拼一次。
KIND_LABELS = {
    PACK_KIND_KNOWN: "掌握",
    PACK_KIND_FUZZY: "模糊",
    PACK_KIND_WRONG: "错题",
}

# 标题模板。样例:「我的词表考试·掌握」「sample考试·错题」。
TITLE_TEMPLATE = "%s考试·%s"

# 「显示用的分桶名」→「档位名」。
#
# ⚠️ **这两套名字必须翻译一次,不能混用。** core.quiz.classify 返回的是
# `BUCKET_*`(值是中文「熟词 / 模糊词 / 生词」,给界面看),而档位用的是
# `PACK_KIND_*`(英文,因为它同时是包 id 的一部分)。混着用会**静默**出大事:
# 名字对不上时 severity() 返回 -1,每个词都被当成"最轻的一档",
# 于是三档全挤进「掌握」里,而且不报任何错 —— 上一版踩过这个坑。
BUCKET_TO_KIND = {
    BUCKET_KNOWN: PACK_KIND_KNOWN,
    BUCKET_FUZZY: PACK_KIND_FUZZY,
    BUCKET_NEW: PACK_KIND_WRONG,
}


# --------------------------------------------------------------------------
# 认包
# --------------------------------------------------------------------------

def is_exam_pack(pack: WordPack) -> bool:
    """是不是"单词表名下的考试结果包"。

    旧存档里有上一版留下的、按日期的考试包 —— 它们没有 group_id,
    不算在这里面,会原样保留在列表里,由用户自己决定怎么处理。
    """
    return (pack.pack_type == PACK_TYPE_EXAM
            and bool(pack.group_id) and pack.kind in PACK_KINDS)


def vocab_of(pack: WordPack, packs: Iterable[WordPack] = ()) -> str:
    """这个词包属于哪份单词表。认不出来返回空串。

    三种输入:
      * 单词表自己 → 就是它;
      * 考试结果包 → 它的父单词表(group_id 就是单词表 id);
      * **学习词包** → 它来源的那份词表(建包时记在 source_vocab 里)。

    学习词包那一支很重要:用户考试时多半勾的是"今天的学习词包",
    而结果该落到那份**单词表**的考试包里 —— 否则每学一批就多一套考试包,
    又变回堆积了。
    """
    if pack.pack_type == PACK_TYPE_VOCAB:
        return pack.id
    if pack.pack_type == PACK_TYPE_EXAM:
        return pack.group_id
    if pack.pack_type == PACK_TYPE_STUDY:
        if pack.source_vocab:
            return pack.source_vocab
        # 老存档的学习词包没记 source_vocab,退回它记的"来自哪个包"。
        # 只有那一个恰好是单词表时才认 —— 认不出来比认错好。
        return _vocab_id_from(pack.source_pack, packs)
    return ""


def _vocab_id_from(pack_id: Optional[str], packs: Iterable[WordPack]) -> str:
    if not pack_id:
        return ""
    for pack in packs:
        if pack.id == pack_id and pack.pack_type == PACK_TYPE_VOCAB:
            return pack.id
    return ""


def exam_pack_id(vocab_id: str, kind: str) -> str:
    """某一档的包 id。

    **从单词表 id 派生,所以稳定** —— 这是"永远只有三个"的前提:
    用递增 id 的话,每考一次会再建一套三个包,收敛就无从谈起。
    """
    return "%s_exam_%s" % (vocab_id, kind)


def exam_packs_of(packs: Iterable[WordPack], vocab_id: str) -> List[WordPack]:
    """这份单词表名下的三个考试包(按档位顺序),缺的不补。"""
    found = {pack.kind: pack for pack in packs
             if pack.group_id == vocab_id and is_exam_pack(pack)}
    return [found[kind] for kind in PACK_KINDS if kind in found]


def summary_of(packs: Iterable[WordPack], vocab_id: str) -> Dict[str, int]:
    """三档各有几个词。没有的档记 0。"""
    counts = {kind: 0 for kind in PACK_KINDS}
    for pack in exam_packs_of(packs, vocab_id):
        counts[pack.kind] = pack.word_count
    return counts


def summary_text(packs: Iterable[WordPack], vocab_id: str) -> str:
    """一行小字,例如「掌握 21 · 模糊 6 · 错题 3」。空的档不写。"""
    counts = summary_of(packs, vocab_id)
    return " · ".join("%s %d" % (KIND_LABELS[kind], counts[kind])
                      for kind in PACK_KINDS if counts.get(kind))


def kind_label(pack: WordPack) -> str:
    """这一档叫什么(中文)。"""
    return KIND_LABELS.get(pack.kind, pack.kind)


# --------------------------------------------------------------------------
# 分档
# --------------------------------------------------------------------------

def kind_of(word, session) -> str:
    """这个词在**这一次**考试里归哪一档。

    复用 ExamSession 自己的分类(它取的是这次考试里最差的一次结果),
    界面和 core 因此不会各算一套。分类结果经 BUCKET_TO_KIND 翻译成档位名。
    """
    from .quiz import classify

    return BUCKET_TO_KIND.get(classify(session.worst_grade(word.id)),
                              PACK_KIND_KNOWN)


# --------------------------------------------------------------------------
# 写入
# --------------------------------------------------------------------------

def ensure_packs(packs: List[WordPack], vocab_id: str, title: str,
                 order: str = "sequential") -> Dict[str, WordPack]:
    """把这份单词表的三个考试包准备好(缺的补上),返回 {档位: 包}。"""
    built: Dict[str, WordPack] = {pack.kind: pack
                                  for pack in exam_packs_of(packs, vocab_id)}
    for kind in PACK_KINDS:
        if kind not in built:
            pack = WordPack(id=exam_pack_id(vocab_id, kind),
                            pack_type=PACK_TYPE_EXAM,
                            title=TITLE_TEMPLATE % (title, KIND_LABELS[kind]),
                            created_at=date.today().isoformat(),
                            group_id=vocab_id, kind=kind, source_mode=order)
            packs.append(pack)
            built[kind] = pack
        built[kind].source_mode = order
    return built


def merge_exam(packs: List[WordPack], vocab_id: str, title: str, session,
               index: Dict[str, Word], order: str = "sequential"
               ) -> List[WordPack]:
    """把这一场考试并进这份单词表的三个考试包,返回三档(按档位顺序)。

    **以这一场的结果为准**:每个词按这次的表现挪到对应的档,可以升也可以降。
    三档加起来 = 这份词表里考过的全部词。

    `session` 只要有 `worst_grade()` 和 `words` 就够(见 core/quiz.ExamSession),
    所以这里能脱离界面测。
    """
    built = ensure_packs(packs, vocab_id, title, order)

    # ⚠️ **只重排"这一场真的判过分的词"。** `session.words` 是整份题单,
    # 提前结束(点「结束」/「返回」)时后面那些题还没答,它们**没有分数** ——
    # 而 kind_of 对"没答过"返回的是最差的那一档(见 core/quiz.classify:
    # worst 为 None 按生词算,因为没答过的词谈不上"熟")。照单全收的话,
    # 一次提前结束的考试会把所有没考的题一次性倒进「错题」里。
    decided: Dict[str, str] = {}
    for word in session.words:
        if word.id not in index:
            continue                  # 词库里没有的词不进包,免得列表里点不开
        if session.worst_grade(word.id) is None:
            continue                  # 这一场没答到它,保持原样
        decided[word.id] = kind_of(word, session)

    # ⚠️ 这一节有两个必须同时成立的约束,少一个都会静默出错:
    #
    # 1. **这一场没考到的词要留在原来的档里。** 只按"这一场考过的词"重排的话,
    #    "这场只考了 2 个词"会把另外 4 个词从各自的档里抹掉 —— 考试包的语义是
    #    "这份词表的状态",没考到的词状态没变,不该被动。
    #
    # 2. **不能写成"先删后加"**(`pack.word_ids = [留下的]; attach_words(...)`)。
    #    attach_words 会**跳过已经在 word_ids 里的**词,而别的档这时还没被处理、
    #    那批词还留在里面 —— 于是每一批都被当成"已存在"跳过,三档一个字都没动。
    #    整体赋值没有这个歧义。
    #
    # 两段的顺序也不能反:老词在前(用户对那个顺序有印象),新词追加在后面
    # (一眼看得出"这次多了几个")。
    for kind, pack in built.items():
        newly = [word_id for word_id, target in decided.items() if target == kind]
        # 这一场没考到的词留在原位 —— 它们的状态没变
        stayed = [word_id for word_id in pack.word_ids if word_id not in decided]
        # 一句话说清三件事:没考到的留在前面、这一场考过且归这一档的排后面、
        # **从这一档挪走的词自然就不在里面了**(它只出现在 decided 指向的那一档)
        pack.word_ids = stayed + newly

    return [built[kind] for kind in PACK_KINDS]


def retitle(packs: List[WordPack], vocab_id: str, title: str) -> None:
    """单词表改名之后,把它名下三个考试包的标题跟上。

    标题里带着单词表名(「我的词表考试·错题」),不跟着改的话,用户改完
    名字会看到三个还叫着旧名字的包,像是没删干净。
    """
    for pack in exam_packs_of(packs, vocab_id):
        pack.title = TITLE_TEMPLATE % (title, KIND_LABELS.get(pack.kind, ""))


def drop_for_vocab(packs: List[WordPack], vocab_id: str) -> List[WordPack]:
    """把这份单词表名下的三个考试包从列表里摘掉,返回被摘掉的那些。

    级联删除 —— 子包脱离父单词表就没有出处了。调用方负责连它们独占的词
    一起清理(见 ui/pack_flows.py)。
    """
    doomed = [pack for pack in packs
              if pack.group_id == vocab_id and is_exam_pack(pack)]
    for pack in doomed:
        packs.remove(pack)
    return doomed


# --------------------------------------------------------------------------
# 给界面用的描述
# --------------------------------------------------------------------------

def is_reviewable(pack: WordPack) -> bool:
    """这个词包参不参与记忆曲线 / 今日复习。

    考试结果包不参与:它的词和单词表 / 学习词包里的词是同一个对象,
    该复习的会被那些包排上;再给考试包排一遍,同一个词会在「今日复习」里
    出现两次,复习量虚高(用户 2026-10-14 明确要求剔除)。

    判据是 **pack_type,不是"算不算这一套的三个包"** —— 上一版留下的
    按日期考试包(没有 group_id)同样是考试结果,同样会重复计数。
    """
    return pack.pack_type != PACK_TYPE_EXAM


__all__ = [
    "BUCKET_TO_KIND", "KIND_LABELS", "TITLE_TEMPLATE",
    "drop_for_vocab", "ensure_packs", "exam_pack_id",
    "exam_packs_of", "is_exam_pack", "is_reviewable", "kind_label", "kind_of",
    "merge_exam", "retitle",
    "summary_of", "summary_text", "vocab_of",
]
