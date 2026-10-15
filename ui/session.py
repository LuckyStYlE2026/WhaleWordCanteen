# -*- coding: utf-8 -*-
"""一次学习/考试的"计划":要背哪些词、用什么模式。

单独成模块,是因为"开始"页面负责**挑词**,学习页和考试页负责**用词**,
两边需要一个共同的载体。把挑词的逻辑塞进学习页,考试页就得再抄一遍。

放在 ui/ 而不是 core/,是因为这里面没有学习规则 —— 它只做三件事:
把勾选的词包翻译成单词列表、把单词按组合分页、从词库取到期的词。
真正的规则(什么算"到期"、答完怎么排下次复习)全在 core 里。
"""

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from core.models import Word
from core.pack_progress import study_range
from core.packs import WordPack
from core.quiz import weighted_sample

# 没有组合的单词一次展示几个。取 5 是因为一屏能舒服地放下 5 条释义,
# 再多就得滚动,而"要滚动才能看全"会让人干脆跳过不看。
UNGROUPED_PAGE_SIZE = 5

MODE_STUDY = "study"
MODE_EXAM = "exam"

# 考试的出题顺序(用户 2026-10-13 提的二次确认里选的):
#
#   ORDER_SEQUENTIAL  按词包 / 单词表里的原顺序
#   ORDER_RANDOM      把**这一次要考的那批词**打乱
#
# ⚠️ ORDER_RANDOM **绝不改动词包本身**。打乱发生在 SessionPlan.words 这份
# 副本上(见 shuffle_plan),词包里的 word_ids 一个都不动 —— 用户说了
# "做好分离,不改变外面的词包"。
ORDER_SEQUENTIAL = "sequential"
ORDER_RANDOM = "random"

ORDER_LABELS = {
    ORDER_SEQUENTIAL: "顺序考试(按词包里的顺序)",
    ORDER_RANDOM: "随机考试(把要考的词打乱)",
}


@dataclass
class SessionPlan:
    """一次学习或考试的全部输入。"""

    words: List[Word] = field(default_factory=list)
    mode: str = MODE_STUDY
    title: str = ""
    pack_id: str = ""            # 来自哪个词包;为空表示跨词包的临时会话
    pack: Optional[WordPack] = None
    # 这一轮从来源词包的第几个词开始(0 起)。学习页靠它把进度写回去 ——
    # 少了它,学习页只知道"我评价了 20 个",不知道"从哪里数的 20 个"。
    start_index: int = 0
    # 出题顺序。学习页不看它(学习必须按顺序背);考试页只看它来回答
    # "这一场是顺序还是随机",并把它写进结果包。
    order: str = ORDER_SEQUENTIAL

    def __len__(self) -> int:
        return len(self.words)


def merge_words(*groups: List[Word]) -> List[Word]:
    """把几批单词按顺序拼起来,按 id 去重。

    去重必须按 id 而不是按拼写:同一个单词可能既在"今日复习"里、
    又在你勾的词包里,而学习页拿到的每一页都必须是**同一个对象** ——
    重复的一页会让同一个词当场被评两次分,box 直接跳两级。
    """
    seen = set()
    words: List[Word] = []
    for group in groups:
        for word in group:
            if word.id in seen:
                continue
            seen.add(word.id)
            words.append(word)
    return words


def words_from_packs(packs: List[WordPack],
                     index: Dict[str, Word]) -> List[Word]:
    """把勾选的词包展开成单词列表,去掉重复。

    词库里找不到的 id 会被跳过 —— 用户删掉的单词在词包数据里还留着引用,
    这是设计上的取舍:删词时顺手清理词包会写很多文件,
    而在这里跳过一个不存在的 id 是零成本的。
    """
    frames = [[index[word_id] for word_id in pack.word_ids
               if word_id in index] for pack in packs]
    return merge_words(*frames)


def _auto_title(labels: List[str], unit: str) -> str:
    """按"选了几样"生成会话标题。

    用户勾了三样东西,界面上总得显示点什么,而他一眼想看的是"我勾了几个",
    不是全名。所以只选一样时用它的名字,多选时用「甲 等 N <单位>」。
    """
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    return "%s 等 %d %s" % (labels[0], len(labels), unit)


def plan_from_packs(packs: List[WordPack], index: Dict[str, Word],
                    mode: str) -> SessionPlan:
    """把勾选的词包变成一个计划。"""
    return SessionPlan(
        words=words_from_packs(packs, index), mode=mode,
        title=_auto_title([p.title for p in packs], "个词包"),
        pack_id=packs[0].id if len(packs) == 1 else "",
        pack=packs[0] if len(packs) == 1 else None)


def plan_from_parts(parts: List[tuple], mode: str) -> SessionPlan:
    """把 [(标题, [单词]), ...] 拼成一个计划 —— 给"词包 + 今日复习"这类混合选择用。

    跨来源的会话刻意不带 pack_id:它的来源本来就不是某一个词包,
    硬记一个会让学习结束时把结果包挂到一个并不准确的"来源"上
    (见 study.py 写 source_pack 的地方)。
    """
    words = merge_words(*[group for _title, group in parts])
    return SessionPlan(words=words, mode=mode,
                       title=_auto_title([t for t, group in parts if group], "项"))


def plan_from_pack_range(pack: WordPack, index: Dict[str, Word], mode: str,
                         start: int, count: int) -> SessionPlan:
    """从词包里切一段出来,做成一个计划。

    只在"恰好勾中一个词包"时用得着 —— 跨来源的会话(今日复习那种)
    根本没有"第几个"这个坐标,见 plan_from_parts 的说明。
    start 越界会被 study_range 夹回合法范围,所以调用方不必自己判断。
    """
    begin, word_ids = study_range(pack, start, count)
    return SessionPlan(
        words=[index[word_id] for word_id in word_ids if word_id in index],
        mode=mode, title=pack.title, pack_id=pack.id, pack=pack,
        start_index=begin)


def plan_random_exam(index: Dict[str, Word]) -> SessionPlan:
    """随机考试的**候选池**:全库。

    这里刻意不抽样 —— 抽几个、按什么权重抽,统一交给
    resample_for_exam 在发车前做一次。以前这里抽一遍、发车时又抽一遍,
    第二次因为池子已经缩到题量、走的只是打乱顺序的分支,
    第一次算出来的加权等于白算了。
    """
    return SessionPlan(words=list(index.values()), mode=MODE_EXAM,
                       title="随机考试")


def shuffle_plan(plan: SessionPlan, rng=None) -> SessionPlan:
    """把这一场要考的词打乱。**只动 plan.words 这份副本。**

    用户明确要求:"把词包/单词表内的单词乱序(**做好分离,不改变外面的
    词包**)"。所以这里 shuffle 的是从词包展开出来的那个列表 ——
    它是一次会话自己的数据,词包里的 word_ids 顺序一个都不动。

    这也意味着"随机考试"是**每次发车现算**的:同一场考试退出来再考一次,
    顺序会不一样;而词包里的顺序始终是用户导入时的那个顺序。
    """
    chooser = rng or random
    chooser.shuffle(plan.words)
    return plan


def resample_for_exam(plan: SessionPlan, count: int, rng=None) -> SessionPlan:
    """考试会话的抽样收口 —— **全工程唯一调用 weighted_sample 的地方**。

    学习计划原样返回:学习是"把这一包按顺序背一遍",缩水就少背了词。

    `count` 的约定(和 core/quiz.weighted_sample 一致):**<= 0 表示全部**。
    这一点要紧 —— 考试页在"词量极大"那一问里选"考全部"时传的就是 0,
    如果这里当成"无效题量"给个空列表,用户会看到"无法开始:题数不是正数",
    而那句提示明明说着"考全部 100 个词"。

    考试按 `plan.order` 分两条路:

    * **顺序考试**:取**前 count 个**,顺序原样保留。刻意不走
      weighted_sample —— 那个函数第一个就按权重抽,抽出来天然是乱的,
      "顺序考试"会名不副实。
    * **随机考试**:按 `1 + 2*错 + 模糊` 加权抽 count 个(全部时只打乱顺序)。
      加权让薄弱词占主导,但仍然是"偏重"不是"只考"(见 core/quiz 开头)。

    刻意**不**按"毕业/到期"过滤(2026-10-12 用户反馈):考试是用户
    主动发起的检验,选了什么词包就考什么 —— 该复习什么由「开始复习」
    那条按记忆曲线走的路负责。池子全"毕业"也不该返回空,直接考。
    """
    if plan.mode != MODE_EXAM:
        return plan

    pool = list(plan.words)
    if count <= 0:                     # 全部:顺序考试原样留,随机考试打乱
        if plan.order == ORDER_RANDOM:
            plan.words = weighted_sample(pool, len(pool), rng)
        else:
            plan.words = pool
        return plan

    if plan.order == ORDER_RANDOM:
        plan.words = weighted_sample(pool, count, rng)
    else:
        plan.words = pool[:count]
    return plan


def target_view(plan: SessionPlan) -> str:
    """这个计划该进哪个板块。"""
    return "exam" if plan.mode == MODE_EXAM else "study"


# --------------------------------------------------------------------------
# 学习模式的分页
# --------------------------------------------------------------------------

def chunk(words: List[Word], size: int) -> List[List[Word]]:
    """把一串词按 size 切开。size <= 0 表示不切(整串一屏)。

    单独一个函数而不是在 group_pages 里内联:它有自己的边界(空列表、
    非正数、最后一个不足 size 的尾块),而这几个边界是测试最爱漏的地方。
    """
    if size <= 0 or len(words) <= size:
        return [list(words)] if words else []
    return [list(words[start:start + size]) for start in range(0, len(words), size)]


def group_pages(words: List[Word], page_size: int = UNGROUPED_PAGE_SIZE
                ) -> List[List[Word]]:
    """把单词切成"一屏一屏"。

    规格:有组合的按组合一起显示,没有组合的按顺序显示多个。

    **每个组合内部也要按 page_size 切**(用户 2026-10-15 的要求):
    组合是**导入词表时给的**,可能是课本的一个单元(十几个词),也可能
    被人当成"整本书"打成一组。不做上限的话,一屏塞进上百张卡片,
    用户根本不知道从哪看起。所以"组合 1 有 13 个词"会切成 5 + 5 + 3,
    第 4 次「下一组」才进入组合 2。

    顺序仍然**保持原样**:一整串单词按顺序扫过去,碰到某个组的第一个词
    就把它那个组按 page_size 依次吐出来,碰到没组的就先攒着、攒满一屏再吐。
    这样"第 1 组、第 2 组、中间几个散词、第 3 组"的原始次序不会被打乱 ——
    用户导入词表时的顺序往往是有意义的(课本的单元顺序),
    重排它等于把那份信息丢了。
    """
    grouped: Dict[str, List[Word]] = {}
    for word in words:
        key = (word.group or "").strip()
        if key:
            grouped.setdefault(key, []).append(word)

    pages: List[List[Word]] = []
    pending: List[Word] = []          # 攒着的无组单词
    done: set = set()                 # 已经吐过的组,避免重复

    for word in words:
        key = (word.group or "").strip()
        if key:
            if key in done:
                continue
            done.add(key)
            if pending:
                pages.extend(chunk(pending, page_size))
                pending = []
            pages.extend(chunk(grouped[key], page_size))
        else:
            pending.append(word)
            if page_size > 0 and len(pending) == page_size:
                pages.append(pending)
                pending = []

    if pending:
        pages.extend(chunk(pending, page_size))
    return pages
