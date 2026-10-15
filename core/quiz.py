# -*- coding: utf-8 -*-
"""考试会话:抽题、判分、分类成熟词/模糊词/生词。

**为什么抽题要加权?**

如果纯随机抽 20 个词,一个已经背熟的词和一个错了五次的词被抽中的概率一样,
那考试对用户的帮助就很有限 —— 他大部分时间在重复已经会的东西。
所以按 `1 + 2*错次 + 模糊次` 加权,让薄弱词占主导。

但加权不能变成"只考错词":那样用户永远看不到自己的进步,
而且已经掌握的词也会慢慢忘掉。所以规则是"偏重"而不是"只考"。

要不要把某个词从抽题池里剔掉,考试自己不做主 —— 那
是「开始复习」(记忆曲线到期队列)的职责,两条通道各管一段。
"""

import random
from datetime import date
from typing import Dict, List, Optional, Set, Tuple

from .interfaces import JudgeResult
from .models import (
    BUCKET_FUZZY,
    BUCKET_KNOWN,
    BUCKET_NEW,
    Grade,
    Word,
)
from .packs import PACK_TYPE_EXAM, ExamResult, WordPack
from .scheduler import format_day


# --------------------------------------------------------------------------
# 抽题
# --------------------------------------------------------------------------

def sampling_weight(word: Word) -> float:
    """这个词被抽中考试的权重。

    权重随错误次数和模糊次数线性增长。错一次加 2,模糊一次加 1 ——
    错比模糊更该被重视,所以系数是 2 倍。

    刻意**不**再按"毕业/到期"过滤(2026-10-12 用户反馈):考试是用户
    主动发起的检验,选了什么就考什么,该不该复习由「开始复习」那条
    记忆曲线的路管,考试不替用户做主。加权仍然偏向错得多的词。
    """
    state = word.state
    return 1.0 + 2.0 * state.wrong_count + 1.0 * state.fuzzy_count


def weighted_sample(pool: List[Word], size: int,
                    rng: Optional[random.Random] = None) -> List[Word]:
    """按权重不放回地抽 size 个词。

    实现方式是**逐个抽**:每次抽走一个就从池子里删掉它,再抽下一个。
    这是"不放回加权抽样"最直白的写法 —— 比排序打乱之类的技巧好读得多,
    而几百个词的规模下性能完全不是问题(要抽 20 个,就是 20 次线性扫描)。

    池子不够 size 个时就返回全部,不报错 —— 新用户词库很小,
    不该因为"词不够"就没法考试。
    """
    if size <= 0:
        return []
    chooser = rng or random
    remaining = list(pool)
    if size >= len(remaining):
        # 池子不够就全给出去,只是打乱一下顺序 —— 不该因为"词太少"考不了试
        chooser.shuffle(remaining)
        return remaining

    chosen: List[Word] = []
    while remaining and len(chosen) < size:
        weights = [sampling_weight(word) for word in remaining]
        total = sum(weights)
        if total <= 0:                      # 理论上不会发生,但别让抽题崩掉
            picked = chooser.choice(remaining)
        else:
            picked = chooser.choices(remaining, weights=weights, k=1)[0]
        chosen.append(picked)
        remaining.remove(picked)
    return chosen


def mistake_words(index: Dict[str, Word]) -> List[Word]:
    """错题本。**实时算出来**,不读任何缓存字段。

    is_mistake() 是纯派生判断(见 models.WordState),所以这里不需要维护
    什么"错题列表"的副本 —— 副本迟早会和真实计数对不上。
    """
    return [word for word in index.values() if word.state.is_mistake()]


# --------------------------------------------------------------------------
# 分类
# --------------------------------------------------------------------------

# 判分结果的好坏排序,用来取"最差的一次"。答对最好,答错最差。
_GRADE_RANK = {Grade.WRONG: 0, Grade.FUZZY: 1, Grade.CORRECT: 2}


def classify(worst: Optional[Grade]) -> str:
    """把一个词在这次考试里的表现归到熟词/模糊词/生词。

    取的是**最差**的一次结果:一个词只要在这次考试里错过一次,
    就归到生词。这条规则偏严,但它是可解释的 ——
    "错了就是还不会",比"平均一下算半对"更容易跟用户讲清楚,
    也更能推动他去复习这个词。

    worst 为 None(还没答过)按生词算,因为没答过的词谈不上"熟"。
    """
    if worst == Grade.CORRECT:
        return BUCKET_KNOWN
    if worst == Grade.FUZZY:
        return BUCKET_FUZZY
    return BUCKET_NEW


# --------------------------------------------------------------------------
# 考试会话
# --------------------------------------------------------------------------

class ExamSession:
    """一次考试的进行状态。

    刻意做成一个**纯内存对象**,不认识界面也不认识文件:
    界面负责显示 current 并在 submit 里喂入用户输入,
    存档由 finish() 生成的词包承载。这样整个考试流程可以脱离 GUI 测试。

    判分结果**立刻**写回 word.state,而不是等考完再统一结算 ——
    用户中途关掉窗口的话,已经答过的题不该白答。
    """

    def __init__(self, words: List[Word], judge, scheduler, today: date,
                 title: str = "", order: str = "sequential") -> None:
        """
        words      本次要考的单词,顺序就是出题顺序
        judge      JudgeService(带阈值网关的那个),不是裸的 OfflineJudge
        scheduler  Scheduler 实例,负责推进复习状态
        order      这一场是顺序还是随机(原样写进结果包,供以后回看)
        """
        self.words = list(words)
        self._judge = judge
        self._scheduler = scheduler
        self.today = today
        self.title = title
        self.order = order

        self._position = 0
        self.answers: Dict[str, str] = {}
        # 每个词的**最后一次**判分结果,用来在界面上回看"我刚才答了什么"
        self.results: Dict[str, JudgeResult] = {}
        # 每个词的**最差**一次结果,用来分桶。两者分开是因为同一个词
        # 有可能在考试里出现两次(词库里被重复选入),而"先答错后答对"
        # 和"先答对后答错"应该得到同样严格的评价。
        self.worst: Dict[str, Grade] = {}

    # ---- 出题 ------------------------------------------------------------

    @property
    def current(self) -> Optional[Word]:
        """当前这道题。考完了返回 None。"""
        if self._position >= len(self.words):
            return None
        return self.words[self._position]

    @property
    def total(self) -> int:
        return len(self.words)

    @property
    def answered_count(self) -> int:
        return self._position

    @property
    def is_finished(self) -> bool:
        return self._position >= len(self.words)

    # ---- 作答 ------------------------------------------------------------

    def submit(self, answer: str) -> Optional[JudgeResult]:
        """判一次分并前进到下一题。考完了返回 None。

        返回 None 而不是抛异常:界面可能在最后一题后多触发一次,
        那不该是个错误。
        """
        word = self.current
        if word is None:
            return None

        result = self._judge.judge(word, answer)
        self.answers[word.id] = answer
        self.results[word.id] = result
        previous = self.worst.get(word.id)
        if previous is None or _GRADE_RANK[result.grade] < _GRADE_RANK[previous]:
            self.worst[word.id] = result.grade

        # 立刻推进复习状态。注意用的是**新状态**,不是原地改 ——
        # 这条约定见 interfaces.Scheduler.grade 的说明。
        word.state = self._scheduler.grade(word.state, result.grade, self.today)

        self._position += 1
        return result

    # ---- 结算 ------------------------------------------------------------

    def worst_grade(self, word_id: str) -> Optional[Grade]:
        return self.worst.get(word_id)

    def buckets(self) -> Tuple[List[str], List[str], List[str]]:
        """返回 (熟词id, 模糊词id, 生词id),顺序与出题顺序一致。

        同一个词只出现一次 —— 这些列表是给界面列出来看的,
        重复的 id 没有意义。词在 words 里出现两次是调用方传重了,
        不该表现成"用户看到两行一模一样的词"。

        同时把分类写回 word.state.bucket —— 那是"最近一次考试分到哪一档",
        只用于展示,下次考试会被覆盖。
        """
        known: List[str] = []
        fuzzy: List[str] = []
        new: List[str] = []
        seen: Set[str] = set()
        for word in self.words:
            if word.id in seen:
                continue
            seen.add(word.id)

            bucket = classify(self.worst_grade(word.id))
            word.state.bucket = bucket
            if bucket == BUCKET_KNOWN:
                known.append(word.id)
            elif bucket == BUCKET_FUZZY:
                fuzzy.append(word.id)
            else:
                new.append(word.id)
        return known, fuzzy, new

    def score(self) -> float:
        """正确率,0.0 ~ 1.0。

        定义就是字面意思:**完全答对的题数 ÷ 答题总数**。
        模糊的答案计入分母但不计入分子 —— 它确实不是一次完整的成功,
        把它从分母里摘出去会让数字虚高,那是在骗自己。

        一次都没作答时返回 0.0,而不是制造除零。
        """
        judged = [r.grade for r in self.results.values()]
        if not judged:
            return 0.0
        correct = sum(1 for grade in judged if grade == Grade.CORRECT)
        return correct / float(len(judged))

    def summary(self) -> ExamResult:
        """生成这次考试的结果快照,留档进词包。"""
        known, fuzzy, new = self.buckets()
        wrong_ids = [word_id for word_id, result in self.results.items()
                     if result.grade == Grade.WRONG]
        return ExamResult(
            known=known, fuzzy=fuzzy, newly=new, wrong_ids=wrong_ids,
            score=self.score(), taken_at=format_day(self.today),
        )

    def build_pack(self, index: Dict[str, Word], pack_id: str) -> WordPack:
        """生成考试词包。内容很轻 —— 只记 id 和这一次的结果快照。

        单词状态的真相始终在 words_index.json 里,词包不复制它。
        所以这里即使存了一份 wrong_ids,也只是"这一次考试的快照",
        不会和真实状态产生矛盾。

        ⚠️ **正常情况下不要直接调它。** 考试结果现在并进"当天的考试包组"
        (见 core/exam_group.py),那边负责合并三档和稳定 id。这个函数留着
        是给"单场考试包"这条老路用的,core/exam_group 里用不到它。
        """
        pack = WordPack(
            id=pack_id,
            pack_type=PACK_TYPE_EXAM,
            title=self.title or ("%s 考试" % format_day(self.today)),
            created_at=format_day(self.today),
            word_ids=[word.id for word in self.words],
            source_mode=self.order,
            exam=self.summary(),
        )
        pack.mistakes = rebuild_mistakes(index)
        pack.schedule.last_studied = format_day(self.today)
        return pack


def rebuild_mistakes(index: Dict[str, Word]) -> List[str]:
    """按当前真实状态重算易错词 id 列表。

    词包里的 mistakes 字段只是**缓存** —— 打开词包时调这个函数刷新,
    免得出现"缓存说它是易错词,但用户后来答对了好几次"的过期显示。
    """
    return [word.id for word in mistake_words(index)]
