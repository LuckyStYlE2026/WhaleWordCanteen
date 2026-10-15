# -*- coding: utf-8 -*-
"""核心数据模型:单词、单词的复习状态、判分结果。

本模块只回答"一条数据长什么样",不含任何读写逻辑(那是 storage.py 的事),
也不含任何业务规则(那是 scheduler.py / quiz.py / judge.py 的事)。
词包相关的模型在 packs.py。

所有模型都提供 to_dict() / from_dict()。JSON 持久化统一走这两个方法,
这样将来改字段时只需要改一个地方 —— 这是刻意不用自动序列化的原因:
显式写出来虽然啰嗦,但改起来不会有"魔法藏在哪"的困惑。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------
# 枚举与常量
# --------------------------------------------------------------------------

class Grade(str, Enum):
    """一次作答的结果。

    继承 str 是为了让它能直接和 JSON 里的字符串比较、直接写进 JSON,
    省掉一层来回转换。
    """

    CORRECT = "correct"   # 答对
    FUZZY = "fuzzy"       # 模糊:沾边但不完全对
    WRONG = "wrong"       # 答错


class Mastery(str, Enum):
    """单词的长期掌握状态。

    注意:这个状态挂在**单词自己**身上,与词包无关。
    词包只是"一次批量录入",复习时可以跨词包抽取到期单词。

    NEW     从未复习过,或答错过但此前也没掌握
    FUZZY   在学,但还没到"掌握"
    KNOWN   已掌握(需要连续答对,把间隔推到 7 天以上)
    RELEARN 曾经掌握,但答错了,或所在词包严重逾期 —— 需要重学
    """

    NEW = "new"
    FUZZY = "fuzzy"
    KNOWN = "known"
    RELEARN = "relearn"


# 考试分类用的中文桶名。规格里写死了「熟词/模糊词/生词」这三个词,
# 所以单独定义,不与 Mastery 合并 —— 两者含义不同:
# Mastery 是长期真相,bucket 只是"最近一次考试把它分到了哪一档"。
BUCKET_KNOWN = "熟词"
BUCKET_FUZZY = "模糊词"
BUCKET_NEW = "生词"

# 判分来源,用于在界面上告诉用户"这是本地判的还是 AI 判的"
SOURCE_OFFLINE = "offline"
SOURCE_AI = "ai"
SOURCE_CACHE = "cache"


# --------------------------------------------------------------------------
# 单词与它的复习状态
# --------------------------------------------------------------------------

@dataclass
class HistoryEntry:
    """一条复习记录。

    保留历史是为了两件事:画记忆曲线时叠上真实的复习点,
    以及分析用户的学习规律性。所以只存"哪天、什么结果",不存多余信息。
    """

    day: str          # ISO 日期,'YYYY-MM-DD'
    result: Grade

    def to_dict(self) -> Dict[str, Any]:
        return {"t": self.day, "r": self.result.value}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HistoryEntry":
        return cls(day=data["t"], result=Grade(data["r"]))


@dataclass
class WordState:
    """单词的复习状态。这是整个记忆曲线系统的核心数据。

    box 是艾宾浩斯阶梯的下标(0..6),interval_days 是当前间隔天数。
    两者是冗余的 —— interval_days 恒等于阶梯[box] —— 但它们冗余得值得:
    词包逾期重学时会把 box 打回 1,此时直接读 interval_days 比反查阶梯更清楚。

    ease 在本版(MVP)不参与计算,但先写入文件。
    将来若要升级成 SM-2 算法,老存档里已经有这个字段,不需要做数据迁移。

    ⚠️ 本类**不自己维护计数器**。box / interval / mastery / 各种 count
    全部由 scheduler.py 在判分时统一改写。这样"状态怎么变"只有一个出处,
    不会出现两处代码各改一半的情况。
    """

    mastery: Mastery = Mastery.NEW
    bucket: str = BUCKET_NEW           # 最近一次考试的分类,仅供展示
    box: int = 0                       # 艾宾浩斯阶梯下标 0..6
    interval_days: int = 0             # 当前间隔天数
    ease: float = 2.5                  # 预留给 SM-2,本版不计算
    last_review: Optional[str] = None  # ISO 日期
    next_review: Optional[str] = None  # ISO 日期;None 表示还没安排
    review_count: int = 0
    correct_count: int = 0
    fuzzy_count: int = 0
    wrong_count: int = 0
    streak_correct: int = 0            # 连续答对次数,用于"毕业"出考试池
    lapses: int = 0                    # 遗忘次数(掌握后又答错)
    history: List[HistoryEntry] = field(default_factory=list)

    # 历史记录上限。超出后丢最旧的,避免文件无限膨胀。
    HISTORY_LIMIT = 20

    def clone(self) -> "WordState":
        """复制一份,history 也复制成新列表。

        调度器判分时必须返回**新的**状态而不是原地改,
        这样测试可以拿旧状态和新状态对比,出问题时也能回滚。
        只需浅拷贝 history:HistoryEntry 本身不会再被改动。
        """
        duplicate = WordState(
            mastery=self.mastery, bucket=self.bucket, box=self.box,
            interval_days=self.interval_days, ease=self.ease,
            last_review=self.last_review, next_review=self.next_review,
            review_count=self.review_count, correct_count=self.correct_count,
            fuzzy_count=self.fuzzy_count, wrong_count=self.wrong_count,
            streak_correct=self.streak_correct, lapses=self.lapses,
            history=list(self.history),
        )
        return duplicate

    def append_history(self, day: str, result: Grade) -> None:
        """追加一条复习记录,并维护环形缓冲上限。

        ⚠️ 只动 history,不动任何计数器。计数器是 scheduler 的职责。
        这个方法单独拎出来,就是为了让"谁改了什么"一目了然。
        """
        self.history.append(HistoryEntry(day=day, result=result))
        if len(self.history) > self.HISTORY_LIMIT:
            self.history = self.history[-self.HISTORY_LIMIT:]

    def is_mistake(self) -> bool:
        """是否算"易错词"。

        这是**派生**判断,不单独存字段 —— 避免出现"缓存说它是易错词,
        但计数已经变了"的不一致。错题本就是靠这个函数实时算出来的。
        """
        return self.wrong_count >= 2 or (self.wrong_count >= 1 and self.streak_correct == 0)

    def is_graduated(self, required_streak: int) -> bool:
        """是否已从考试池"毕业"(连续答对足够多次)。

        毕业的词不再被随机抽中考试,但到了复习日期依然会被安排复习。
        """
        return self.streak_correct >= required_streak

    def is_never_studied(self) -> bool:
        """这个词是不是**一次都没学过**。

        判据是 review_count == 0,不能看 next_review 或 mastery:
        · next_review 不行 —— 新建的词一进来就被设成"今天到期"
          (见 scheduler.initial_state),那是"随时可以开始学"的意思,
          不是"今天该复习"。
        · mastery 也不行 —— 答错过的词会被打回 NEW,但它显然学过。

        只看 review_count:它由 scheduler.grade 在每次判分时加一,
        是"这个词进过考场"的唯一可靠证据。
        """
        return self.review_count == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mastery": self.mastery.value,
            "bucket": self.bucket,
            "box": self.box,
            "interval_days": self.interval_days,
            "ease": self.ease,
            "last_review": self.last_review,
            "next_review": self.next_review,
            "review_count": self.review_count,
            "correct_count": self.correct_count,
            "fuzzy_count": self.fuzzy_count,
            "wrong_count": self.wrong_count,
            "streak_correct": self.streak_correct,
            "lapses": self.lapses,
            "history": [entry.to_dict() for entry in self.history],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WordState":
        """从字典还原。缺字段一律回退到默认值。

        这样设计是为了向前兼容:老存档缺了新加的字段也能读进来,
        不需要写迁移脚本。
        """
        return cls(
            mastery=Mastery(data.get("mastery", Mastery.NEW.value)),
            bucket=data.get("bucket", BUCKET_NEW),
            box=int(data.get("box", 0)),
            interval_days=int(data.get("interval_days", 0)),
            ease=float(data.get("ease", 2.5)),
            last_review=data.get("last_review"),
            next_review=data.get("next_review"),
            review_count=int(data.get("review_count", 0)),
            correct_count=int(data.get("correct_count", 0)),
            fuzzy_count=int(data.get("fuzzy_count", 0)),
            wrong_count=int(data.get("wrong_count", 0)),
            streak_correct=int(data.get("streak_correct", 0)),
            lapses=int(data.get("lapses", 0)),
            history=[HistoryEntry.from_dict(e) for e in data.get("history", [])],
        )


@dataclass
class Word:
    """一个单词条目。

    只有 word(单词)和 translation(翻译)是必填,其余都可为空字符串。
    group 是"组合":同一组合的词在学习模式下会一起展示。一个词最多属于一个组合,
    所以这里就是一个字符串字段(空串表示不分组),而不是列表。
    """

    id: str                            # 稳定标识,一经生成永不改变
    spelling_key: str                  # 归一化拼写,仅用于导入时去重
    word: str
    translation: str
    phonetic: str = ""
    example: str = ""
    collocation: str = ""
    group: str = ""
    created_at: str = ""
    source_packs: List[str] = field(default_factory=list)
    state: WordState = field(default_factory=WordState)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "spelling_key": self.spelling_key,
            "word": self.word,
            "phonetic": self.phonetic,
            "translation": self.translation,
            "example": self.example,
            "collocation": self.collocation,
            "group": self.group,
            "created_at": self.created_at,
            "source_packs": list(self.source_packs),
            "state": self.state.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Word":
        return cls(
            id=data["id"],
            spelling_key=data.get("spelling_key", ""),
            word=data.get("word", ""),
            translation=data.get("translation", ""),
            phonetic=data.get("phonetic", ""),
            example=data.get("example", ""),
            collocation=data.get("collocation", ""),
            group=data.get("group", ""),
            created_at=data.get("created_at", ""),
            source_packs=list(data.get("source_packs", [])),
            state=WordState.from_dict(data.get("state", {})),
        )
