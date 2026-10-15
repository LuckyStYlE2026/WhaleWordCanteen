# -*- coding: utf-8 -*-
"""词包模型。

**词包 = 一次批量录入的单词集合**,是"学习批次"的意思,不是"复习单元"。
它只记 word_ids,不持有任何单词的学习状态 —— 状态在 Word.state 里,
始终只有一份。所以同一个单词可以同时属于多个词包,
而它的掌握进度不会被复制成几份、互相矛盾。

这是规格里明确要求的:
"每个单词单独记录掌握状态、下次复习时间;词包只是新建学习批次。
 复习的时候,系统也可以自动筛选到期单词(跨词包),而不是强制整包复习。"
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# 词包类型
PACK_TYPE_STUDY = "study"   # 学习产生的词包
PACK_TYPE_EXAM = "exam"     # 考试产生的词包(一组三档之一,见下)
PACK_TYPE_VOCAB = "vocab"   # 用户导入/制作的词表包(学习材料本身,不是结果)

# 一天之内所有考试结果合成**一个**"考试包组",组里分三档。
#
# 为什么不再"每考一次落一个包"(2026-10-13 用户反馈):考三次就是三个包,
# 一周下来列表里几十个"某某考试",用户根本找不到想要的那个;而他想做的事
# ("把我今天错的词再看一遍")其实是**跨场次**的 —— 上午错的词和下午错的词
# 该在同一个包里。所以一天一组,同一组里多次考试**合并**。
#
# 注意:**组不是第四种 pack_type**。组里那三档仍然是 PACK_TYPE_EXAM,
# 靠下面两个字段认出彼此:
#
#   group_id   同一天同一个组("examgroup_20261013")
#   kind       组内是哪一档("known" / "fuzzy" / "wrong")
#
# 为什么不再单开一个 type:那会让存储、列表、勾选、进度判断全部多一个分支,
# 而三档本身就是一个普通词包 —— 用户勾中"今天的错题"去复习是完全正常的用法。
# 组的语义由 core/exam_group.py 负责,不散在类型判断里。

# 组内三档。值同时用作包 id 后缀、group 字段和显示用词的键 ——
# 存的是英文(命名约定),显示的中文在 UI 层(见 ui/views/exam_pick.py)。
PACK_KIND_KNOWN = "known"   # 全对
PACK_KIND_FUZZY = "fuzzy"   # 模糊
PACK_KIND_WRONG = "wrong"   # 错题

# 组的顺序:先全对(看一眼就行),再模糊,最后错题(要重点看的放最后,
# 用户滚到底就看到最该复习的)。同时它也是"合并时谁赢"的严重程度排序 ——
# 两者恰好一致不是巧合:越严重的越该留在更靠后的那一档里。
PACK_KINDS = (PACK_KIND_KNOWN, PACK_KIND_FUZZY, PACK_KIND_WRONG)

# 学习规律性(用于判断词包是否需要重学)
REGULARITY_ON_SCHEDULE = "on_schedule"   # 按时
REGULARITY_DELAYED = "delayed"           # 拖延了一点
REGULARITY_OVERDUE = "overdue"           # 严重逾期 → 触发重学


@dataclass
class SessionRecord:
    """一次学习/复习的记录。用来分析用户是否按计划学习。"""

    day: str
    on_time: bool
    correct: int = 0
    fuzzy: int = 0
    wrong: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.day,
            "on_time": self.on_time,
            "correct": self.correct,
            "fuzzy": self.fuzzy,
            "wrong": self.wrong,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionRecord":
        return cls(
            day=data.get("date", ""),
            on_time=bool(data.get("on_time", True)),
            correct=int(data.get("correct", 0)),
            fuzzy=int(data.get("fuzzy", 0)),
            wrong=int(data.get("wrong", 0)),
        )


@dataclass
class ExamResult:
    """一次考试的分类结果快照。

    为什么要单独存一份?因为单词的 bucket 会随后续考试变化,
    但用户可能想回看"10 号那次我错了哪些"。所以考试结果在词包里留档。
    """

    known: List[str] = field(default_factory=list)      # 熟词 id
    fuzzy: List[str] = field(default_factory=list)      # 模糊词 id
    newly: List[str] = field(default_factory=list)      # 生词 id
    wrong_ids: List[str] = field(default_factory=list)  # 答错的 id
    score: float = 0.0                                  # 正确率 0.0~1.0
    taken_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        # JSON 里用 "new" 作键(与规格用词一致),Python 侧叫 newly 避开内置名
        return {
            "known": list(self.known),
            "fuzzy": list(self.fuzzy),
            "new": list(self.newly),
            "wrong_ids": list(self.wrong_ids),
            "score": self.score,
            "taken_at": self.taken_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExamResult":
        return cls(
            known=list(data.get("known", [])),
            fuzzy=list(data.get("fuzzy", [])),
            newly=list(data.get("new", [])),
            wrong_ids=list(data.get("wrong_ids", [])),
            score=float(data.get("score", 0.0)),
            taken_at=data.get("taken_at", ""),
        )


@dataclass
class PackSchedule:
    """词包的学习计划与规律性。

    recommended_next 是"建议下次学习日期"。用户实际什么时候回来,
    与这个日期一对比,就能判断他是规律学习者还是拖延了 ——
    这正是规格里"能完美按照时间学习说明有规律,间隔过长则标记重学"的落点。
    """

    recommended_next: str = ""
    last_studied: str = ""
    sessions: List[SessionRecord] = field(default_factory=list)
    regularity: str = REGULARITY_ON_SCHEDULE
    needs_relearn: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommended_next": self.recommended_next,
            "last_studied": self.last_studied,
            "sessions": [s.to_dict() for s in self.sessions],
            "regularity": self.regularity,
            "needs_relearn": self.needs_relearn,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PackSchedule":
        return cls(
            recommended_next=data.get("recommended_next", ""),
            last_studied=data.get("last_studied", ""),
            sessions=[SessionRecord.from_dict(s) for s in data.get("sessions", [])],
            regularity=data.get("regularity", REGULARITY_ON_SCHEDULE),
            needs_relearn=bool(data.get("needs_relearn", False)),
        )


@dataclass
class PackProgress:
    """词表包的学习进度与书签。

    两个字段都存"第几个词"(0 起),**不是词 id**。理由:用户脑子里想的
    是"学到第 347 个" —— 起点弹窗、状态栏上写的全是这个数;而词包里删掉
    一个词时,位置只是整体前移一位,不会像 id 那样直接失效成"查无此人"。
    越界一律夹回合法范围(见 core/pack_progress.py),不做异常。

    `bookmark = -1` 表示"没标记过"。用 -1 而不是 0,是因为第 0 个词
    是完全合法的一个标记位置,拿 0 当"空"会分不清"标在第 1 个"和"没标"。
    """

    next_index: int = 0     # 下次从第几个词接着学
    bookmark: int = -1      # 手动标记的位置

    def to_dict(self) -> Dict[str, Any]:
        return {"next_index": self.next_index, "bookmark": self.bookmark}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PackProgress":
        return cls(
            next_index=int(data.get("next_index", 0)),
            bookmark=int(data.get("bookmark", -1)),
        )


@dataclass
class WordPack:
    """一个词包。字段含义见模块开头的说明。"""

    id: str
    pack_type: str                      # PACK_TYPE_STUDY / PACK_TYPE_EXAM / ...
    title: str
    created_at: str
    word_ids: List[str] = field(default_factory=list)
    source_mode: str = ""               # "sequential" / "random" / ""
    source_pack: Optional[str] = None   # 由哪个词包复习而来
    # 这个学习词包是从哪份**单词表**学来的。考试结果包要落到那份单词表名下
    # (见 core/exam_group.vocab_of),而这个关系不能靠 source_pack 推断 ——
    # 跨来源会话(今日复习)的 source_pack 是空的,它的词却确实属于某几份词表。
    source_vocab: str = ""
    # 属于哪个"组"。目前只有一天的考试包组用得上(见 PACK_TYPE_EXAM_GROUP),
    # 别的包留空。有了它,界面才能把同一天的三个档收在一起显示,
    # 而不是当成三个互不相干的包。
    group_id: str = ""
    kind: str = ""                      # 组内是哪一档:PACK_KINDS 之一
    schedule: PackSchedule = field(default_factory=PackSchedule)
    exam: Optional[ExamResult] = None
    mistakes: List[str] = field(default_factory=list)  # 缓存,打开词包时重建
    progress: PackProgress = field(default_factory=PackProgress)

    @property
    def word_count(self) -> int:
        """词包里有多少单词。

        派生自 word_ids 而不存进 JSON —— 存了就会有"数字和列表对不上"的风险。
        """
        return len(self.word_ids)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.pack_type,
            "title": self.title,
            "created_at": self.created_at,
            "word_ids": list(self.word_ids),
            "word_count": self.word_count,
            "source": {"mode": self.source_mode, "from_pack": self.source_pack,
                       "vocab": self.source_vocab},
            "group_id": self.group_id,
            "kind": self.kind,
            "schedule": self.schedule.to_dict(),
            "exam": self.exam.to_dict() if self.exam else None,
            "mistakes": list(self.mistakes),
            "progress": self.progress.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WordPack":
        source = data.get("source") or {}
        exam_data = data.get("exam")
        return cls(
            id=data["id"],
            pack_type=data.get("type", PACK_TYPE_STUDY),
            title=data.get("title", ""),
            created_at=data.get("created_at", ""),
            word_ids=list(data.get("word_ids", [])),
            source_mode=source.get("mode", ""),
            source_pack=source.get("from_pack"),
            source_vocab=source.get("vocab", ""),
            group_id=data.get("group_id", ""),
            kind=data.get("kind", ""),
            schedule=PackSchedule.from_dict(data.get("schedule", {})),
            exam=ExamResult.from_dict(exam_data) if exam_data else None,
            mistakes=list(data.get("mistakes", [])),
            progress=PackProgress.from_dict(data.get("progress") or {}),
        )


def make_vocab_pack(pack_id: str, title: str, word_ids: List[str],
                    created_at: str) -> WordPack:
    """造一个词表包(用户导入或制作的那种)。

    和学习/考试产生的词包用同一个 WordPack,只是 pack_type=vocab、
    没有 exam 快照、schedule 保持默认(词表包本身没有"下次复习"的安排 ——
    那是学习会话产生的结果包才有的事)。统一用一个类,存储和界面都不用分叉。
    """
    return WordPack(
        id=pack_id,
        pack_type=PACK_TYPE_VOCAB,
        title=title,
        created_at=created_at,
        word_ids=list(word_ids),
    )
