# -*- coding: utf-8 -*-
"""插件 API:所有可替换部件的抽象基类 + 相关数据类型。

**这是插件作者唯一必读的文件。** 想知道"我能替换什么",看这里就够了。

设计约定:
- 每个可替换部件都是一个 abc.ABC 子类。想替换行为,继承对应的基类。
- 基类里的方法就是契约,不多不少。插件不需要知道内核别的地方怎么写的。
- 想添加"内核里没有的新东西"(比如新的导入格式),同样继承这里的基类,
  然后到 registry.py 注册。

内置实现(离线判分、艾宾浩斯调度、CSV 导入……)也全部继承这些基类,
并且走同一个注册表。所以"插件能做到什么"和"内置怎么做的"是同一个答案 ——
这条接缝不会因为没人用而年久失修。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import SOURCE_OFFLINE, Grade, Word, WordState
from .packs import WordPack


# --------------------------------------------------------------------------
# 情绪常量
# --------------------------------------------------------------------------

# 立绘情绪的固定取值。AI 形象按这些名字提供图片,例如
# assets/ai/default/happy.png。
#
# 这份白名单有**两个**使用方,别只想着一个:
#   1. 本地台词(core/lines.py)—— 情绪由本地按判分结果决定,不经过模型。
#      这是"省 Token"设计的一部分:离线也要能换表情。
#   2. AI 回复(core/reply_format.py)—— 模型可以在回复开头写 [happy]
#      来选表情。它已经为这次回复付过钱了,捎带一个情绪词几乎不增加成本。
# 两边的取值必须来自这里,**别各写一份** —— 否则会出现"本地能显示的情绪
# 模型写了却不认"这种对不上的情况。
EMOTION_NORMAL = "normal"
EMOTION_HAPPY = "happy"
EMOTION_SAD = "sad"
EMOTION_CONFUSED = "confused"
EMOTION_THINKING = "thinking"
EMOTION_SURPRISED = "surprised"

ALL_EMOTIONS = (
    EMOTION_NORMAL,
    EMOTION_HAPPY,
    EMOTION_SAD,
    EMOTION_CONFUSED,
    EMOTION_THINKING,
    EMOTION_SURPRISED,
)


# --------------------------------------------------------------------------
# 词表导入的传递类型
# --------------------------------------------------------------------------

@dataclass
class RawWord:
    """从文件里读出来的原始词条,尚未分配 id、尚未合并进词库。

    与 Word 的区别:Word 是"已经进入词库、有稳定 id、有学习状态"的实体;
    RawWord 是"刚从文件里读出来、还什么都不是"的原始数据。
    两者分开,导入逻辑就不需要伪造 id 和空状态。
    """

    word: str
    translation: str
    phonetic: str = ""
    example: str = ""
    collocation: str = ""
    group: str = ""
    source_line: int = 0          # 来源行号,报错时告诉用户"第几行有问题"


@dataclass
class RowError:
    """一行导入失败的记录。收集起来一次性告诉用户,而不是遇到第一个错就中断。"""

    line: int
    raw: str
    message: str


@dataclass
class ImportResult:
    """一次导入的完整结果:成功读到的词 + 失败的行 + 识别出的格式。"""

    words: List[RawWord] = field(default_factory=list)
    errors: List[RowError] = field(default_factory=list)
    format: str = ""              # "json" / "csv" / "legacy_line" / "plain"

    @property
    def ok(self) -> bool:
        return bool(self.words) and not self.errors


# --------------------------------------------------------------------------
# 判分与对话的传递类型
# --------------------------------------------------------------------------
#
# 这几个原来是放在 models.py 的。挪过来的理由不是"想分层",而是它们
# 本来就不属于"单词长什么样"—— 它们是判分器(Judge)和 AI 后端
# (AIProvider)跟调用方**交换的数据**。契约和契约的入参出参放在一起,
# 插件作者读 Judge.judge 的签名时不用再跳一个文件。

@dataclass
class JudgeItem:
    """送进判分器的一项。批量判分时按列表传递。"""

    word_id: str
    word: str
    translation: str
    answer: str


@dataclass
class JudgeResult:
    """判分结果。

    source 字段很重要:界面上要能区分"这是本地判的"还是"AI 判的"。
    当 API 调用失败静默回退到本地时,这个字段就是唯一的线索。
    """

    grade: Grade
    score: float                        # 0.0 ~ 1.0 的匹配度
    source: str = SOURCE_OFFLINE
    feedback: str = ""                  # 面向用户的简短反馈

    @property
    def is_correct(self) -> bool:
        return self.grade == Grade.CORRECT


@dataclass
class Turn:
    """自由对话中的一轮。仅用于 L2 API 对话的历史裁剪。"""

    role: str        # "user" / "assistant"
    content: str


# --------------------------------------------------------------------------
# 可替换部件
# --------------------------------------------------------------------------

class Judge(ABC):
    """判分器:判断用户输入的答案对不对。

    内置实现:OfflineJudge(纯字符串比对,零成本)。
    可选实现:ApiJudge(调大模型做语义判断,只在歧义带才会被真正触发)。
    """

    @abstractmethod
    def judge(self, word: Word, answer: str) -> JudgeResult:
        """判断 answer 是否是 word 的正确释义。"""
        raise NotImplementedError


class Scheduler(ABC):
    """复习调度器:决定每个单词下次什么时候复习。

    内置实现:EbbinghausScheduler(1/2/4/7/15/30 天阶梯)。
    这正是插件能发挥想象力的地方 —— 想换成 SM-2、FSRS 或者你自己发明的算法,
    继承这个类注册进去即可,不用动内核任何代码。
    """

    @abstractmethod
    def grade(self, state: WordState, result: Grade, today: date) -> WordState:
        """根据本次作答结果,推进这个单词的复习状态。

        返回**新的** WordState(不要原地修改传入的对象,方便测试与回滚)。
        """
        raise NotImplementedError

    @abstractmethod
    def due_words(self, index: Dict[str, Word], today: date, limit: int = 0) -> List[Word]:
        """取出今天到期的单词。跨词包查询 —— 不按词包划分。

        limit 为 0 表示不限制数量。
        """
        raise NotImplementedError

    @abstractmethod
    def evaluate_pack_regularity(self, pack: WordPack, today: date) -> str:
        """判断用户是否按计划回来学习这个词包,返回 REGULARITY_* 之一。"""
        raise NotImplementedError

    @abstractmethod
    def relearn_pack(self, pack: WordPack, index: Dict[str, Word], today: date) -> List[str]:
        """把词包里的单词全部打回重学,返回受影响的单词 id 列表。"""
        raise NotImplementedError


class AIProvider(ABC):
    """大模型后端。

    这是唯一会联网的部件。**它必须随时可以被离线实现替换掉**,
    所以内核里不允许出现"没有 AI 就没法用"的路径。
    """

    @abstractmethod
    def judge_batch(self, items: List[JudgeItem], persona: str = "",
                    history: Optional[List[Turn]] = None) -> List[JudgeResult]:
        """批量判分。

        刻意设计成批量而不是单个 —— 20 个词一次请求,而不是 20 次请求。
        这是省 Token 的关键机制之一。

        ⚠️ **判分也带人设和历史**(用户 2026-10-17 的要求)。
        早先它用的是写死的"你是单词判分助手",于是判分和对话像两个人在说话;
        现在三件事(判分 / 对话 / 诊断)共用同一段人设和同一份历史对话,
        这样发给模型的**前缀完全一致,缓存命中率最高**。
        判分特有的输出约定(只回 JSON)跟着**这一次的最后一条消息**走,
        不进 system、不进历史,见 core/ai_client._build_messages。
        """
        raise NotImplementedError

    @abstractmethod
    def chat(self, persona: str, history: List[Turn], user_message: str) -> str:
        """带人设的自由对话。只在用户主动提问时调用。"""
        raise NotImplementedError

    @abstractmethod
    def diagnose(self, summary: Dict[str, Any], persona: str = "",
                 history: Optional[List[Turn]] = None) -> str:
        """根据学习统计生成一段个性化评语。每场学习只调一次。

        同样带人设和历史 —— 理由和 judge_batch 一样:三件事共用一个角色,
        而且共享前缀能命中缓存。
        """
        raise NotImplementedError


class WordPackImporter(ABC):
    """词表导入器。想支持一种新格式(Anki、欧路、词典文件……)就实现这个。"""

    name: str = ""

    @abstractmethod
    def can_handle(self, path: Path) -> bool:
        """能不能处理这个文件。导入时内核会按顺序问每个导入器。"""
        raise NotImplementedError

    @abstractmethod
    def load(self, path: Path) -> ImportResult:
        """读取文件。**不要在这里抛异常**处理不了的行请收进 ImportResult.errors,
        因为用户导入 500 行时,不该因为第 7 行有问题就看到一片空白。
        """
        raise NotImplementedError


class WordPackExporter(ABC):
    """词表导出器。想加一种导出格式就实现这个。

    实现完到注册表里登记一下(registry.register_exporter),
    它就会出现在「单词设置 → 导出」的格式列表里 —— 界面不用改一行代码。
    """

    name: str = ""            # 内部名,英文。界面按它找导出器
    title: str = ""           # 显示给用户的名字。留空就退回用 name

    @abstractmethod
    def export(self, words: List[Word], path: Path) -> Path:
        """把单词写出去,返回实际写入的文件路径。

        约定:path 是用户**没写后缀**的路径,导出器自己决定加什么后缀
        (见 CsvExporter 里的 with_suffix)。这样用户在保存对话框里
        打一个名字就够了,不需要知道该写 .csv 还是 .md。
        """
        raise NotImplementedError


@dataclass
class LinePack:
    """一套台词。这是 L1 层(零成本对话)的内容来源。

    lines 的键格式是 "{判分结果}:{情绪}",例如 "correct:happy"、"wrong:sad"。
    取值时如果精确键不存在,会回退到 "{判分结果}:normal";
    再不存在则回退到 "*:normal"。这样插件只写几条也能用。
    """

    name: str
    language: str = "zh-CN"
    lines: Dict[str, List[str]] = field(default_factory=dict)

    def lookup(self, grade: str, emotion: str) -> List[str]:
        """按优先级找台词组,找不到就逐级回退。"""
        for key in ("%s:%s" % (grade, emotion), "%s:%s" % (grade, EMOTION_NORMAL), "*:normal"):
            found = self.lines.get(key)
            if found:
                return found
        return []
