# -*- coding: utf-8 -*-
"""判分:L0 离线字面比对,外加一条受控的 L2 升级通道。

**离线层刻意保持"笨"。** 它只做字符串比对,不尝试理解语义。
碰到似是而非的答案,它就老老实实返回"模糊",绝不自作聪明去猜 ——
因为它的职责是"零成本地处理掉绝大多数情况",不是"判得跟人一样准"。

真正的语义理解交给 L2(大模型),但 L2 **只在歧义带才被调用**。
这个"阈值网关"是省 Token 最有效的一招:明确答对、明确答错都不花钱,
只有落在 0.55~0.85 之间那薄薄一层才需要问模型。

另外两道保险:
  · 缓存  同一个(单词, 答案)只问一次,答错两次只花一次钱
  · 预算  单场学习最多调 max_api_calls_per_session 次,超了自动降级为纯离线
"""

import difflib
import re
import unicodedata
from typing import Dict, List, Optional

from .interfaces import Judge, JudgeItem, JudgeResult
from .models import (
    SOURCE_AI,
    SOURCE_CACHE,
    SOURCE_OFFLINE,
    Grade,
    Word,
)

# 词性前缀。注意它带一个点号,所以**必须在去掉标点之前**剥掉 ——
# 这个顺序是踩过坑的:先去掉点号,这个正则就永远匹配不上,
# 义项里会残留 "n 大气层",导致精确匹配退化成包含匹配。
_POS_PATTERN = re.compile(
    r"^\s*(?:n|v|vt|vi|adj|adv|prep|conj|pron|num|art|int|aux|abbr)\s*\.\s*",
    re.IGNORECASE,
)

# 义项分隔符:中英文逗号、分号、顿号、斜杠
_SENSE_SEPARATORS = re.compile(r"[;,、/]")

# 需要清除的标点
_PUNCTUATION = re.compile(r"[.。!！?？\"'“”‘’()（）\[\]【】]")

_WHITESPACE = re.compile(r"\s+")

# 判定阈值
CORRECT_THRESHOLD = 0.85
FUZZY_THRESHOLD = 0.55

# 包含关系(答案只是某个义项的一部分,例如"大气"之于"大气层")的得分。
# 定在阈值之上,所以算答对。
CONTAINMENT_SCORE = 0.88

# 同字异序(例如"氛气"之于"气氛")的得分。
# 故意定在正确阈值之下、模糊阈值之上 —— 明显是手滑,不该判对,也不该判全错。
ANAGRAM_SCORE = 0.80

# 单字答案不走"包含即正确"的捷径,否则输入一个"气"就能过。
MIN_CONTAINMENT_LENGTH = 2


def _clean(text: str) -> str:
    """归一化文本:统一宽度、转小写、去标点、压空白。"""
    text = unicodedata.normalize("NFKC", text)   # 全角 → 半角,兼容字符折叠
    text = text.lower()
    text = _PUNCTUATION.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


def normalize_answer(text: str) -> str:
    """把用户输入归一化。缓存键也用它,保证"大气层"和"大气层!"命中同一条。"""
    return _clean(text)


def split_senses(translation: str) -> List[str]:
    """把一条翻译拆成若干独立义项。

    顺序很重要:**先按分隔符切开,再逐个剥词性前缀,最后清标点**。
    反过来做的话,词性后面那个点号会先被清掉,前缀就剥不掉了。

    "n. 大气层, 大气圈; 气氛" → ["大气层", "大气圈", "气氛"]
    """
    normalized = unicodedata.normalize("NFKC", translation)
    senses: List[str] = []
    for piece in _SENSE_SEPARATORS.split(normalized):
        without_pos = _POS_PATTERN.sub("", piece)
        cleaned = _clean(without_pos)
        if cleaned:
            senses.append(cleaned)
    return senses


def _is_anagram(left: str, right: str) -> bool:
    """两个字是否是同一批字的重排(例如"氛气"与"气氛")。

    中文输入里顺序颠倒是很常见的手滑,单独识别出来判"模糊"比判"错"更合理。
    """
    return left != right and sorted(left) == sorted(right)


def score_against_sense(answer: str, sense: str) -> float:
    """算答案与单个义项的匹配度,0.0 ~ 1.0。"""
    if answer == sense:
        return 1.0
    if len(answer) >= MIN_CONTAINMENT_LENGTH and (answer in sense or sense in answer):
        return CONTAINMENT_SCORE
    if _is_anagram(answer, sense):
        return ANAGRAM_SCORE
    return difflib.SequenceMatcher(None, answer, sense).ratio()


def best_score(answer: str, senses: List[str]) -> float:
    """取与所有义项比对中的最高分。释义答对任意一个义项就算对。"""
    if not senses:
        return 0.0
    return max(score_against_sense(answer, sense) for sense in senses)


def grade_from_score(score: float) -> Grade:
    if score >= CORRECT_THRESHOLD:
        return Grade.CORRECT
    if score >= FUZZY_THRESHOLD:
        return Grade.FUZZY
    return Grade.WRONG


class OfflineJudge(Judge):
    """内置判分器:纯本地,零成本,永不联网。"""

    def judge(self, word: Word, answer: str) -> JudgeResult:
        cleaned = normalize_answer(answer)

        if not cleaned:
            return JudgeResult(Grade.WRONG, 0.0, SOURCE_OFFLINE, "还没有输入答案哦~")

        # 用户把要背的那个词本身打出来了。这几乎必然发生在"没看清题目"的时候,
        # 单独给一句提示比笼统地说"答错了"有用得多。
        if _clean(word.word) == cleaned:
            return JudgeResult(
                Grade.WRONG, 0.0, SOURCE_OFFLINE,
                "你输入的是单词本身,说说它的中文意思吧~",
            )

        senses = split_senses(word.translation)
        score = best_score(cleaned, senses)
        grade = grade_from_score(score)

        if grade == Grade.CORRECT:
            feedback = ""
        elif grade == Grade.FUZZY:
            feedback = "沾边了,但不完全对。"
        else:
            feedback = "正确答案:%s" % word.translation

        return JudgeResult(grade, score, SOURCE_OFFLINE, feedback)


def cache_key(word: Word, answer: str) -> str:
    """缓存键。用归一化后的答案,保证"大气层"和"大气层!"共用一条记录。"""
    return "%s|%s" % (word.id, normalize_answer(answer))


# 判分结果写进对话历史时用的说法。
#
# 单独放一个映射而不是内联在函数里:它是**给用户看的文字**(会出现在对话记录
# 里),值得一眼能改;而且换措辞不该碰到判分逻辑。
_JUDGE_VERDICT_LABELS = {
    Grade.CORRECT: "答对了。",
    Grade.FUZZY: "沾点边,但不够准。",
    Grade.WRONG: "答错了,回头再看一眼。",
}


class JudgeService:
    """判分调度:先本地,必要时(且允许时)才升级到 AI。

    这是整个"省 Token"设计的闸门所在地,所以逻辑都集中在这一个类里,
    不要在别处再判断"要不要调 API" —— 两处判断迟早会不一致。
    """

    def __init__(self, settings, ai_provider=None, cache: Optional[Dict] = None,
                 conversation=None):
        """
        settings     config.Settings,决定语义匹配开关与调用预算
        ai_provider  AIProvider 实例;为 None 表示纯离线运行
        cache        判分缓存字典(通常来自 storage.load_ai_cache())
        conversation 共用的对话上下文(人设 + 历史),见 core/ai_context.py

        ⚠️ **判分也读同一份人设和历史**(用户 2026-10-17 的要求)。
        早先判分挂着写死的"你是单词判分助手",于是判分和对话像两个人在说话;
        而它一条历史都不记,每次升级都是冷启动,缓存也用不上。
        """
        self.settings = settings
        self.ai_provider = ai_provider
        self.cache = cache if cache is not None else {}
        self.conversation = conversation
        self.offline = OfflineJudge()
        self.api_calls_made = 0
        self.api_calls_saved_by_cache = 0

    # ---- 闸门判断 --------------------------------------------------------

    def _may_call_api(self) -> bool:
        """能不能调 API。三个条件缺一不可。"""
        if self.ai_provider is None:
            return False
        if not self.settings.ai.is_configured:
            return False
        # 规格里的"强制语义匹配"开着 = 只走本地对照。名字容易读反,这里写清楚。
        if self.settings.study.force_semantic_match:
            return False
        budget = self.settings.study.max_api_calls_per_session
        return budget <= 0 or self.api_calls_made < budget

    def _should_escalate(self, result: JudgeResult) -> bool:
        """是否落在歧义带。

        明确答对(>=0.85)和明确答错(<0.55)都直接采纳本地判定,不花钱。
        只有中间那层"好像对又好像不对"才值得问模型。
        """
        return FUZZY_THRESHOLD <= result.score < CORRECT_THRESHOLD

    # ---- 对外入口 --------------------------------------------------------

    def judge(self, word: Word, answer: str) -> JudgeResult:
        """判一个词。绝大多数情况在本地就结束了。"""
        local = self.offline.judge(word, answer)

        if not self._should_escalate(local) or not self._may_call_api():
            return local

        key = cache_key(word, answer)
        cached = self.cache.get(key)
        if cached is not None:
            self.api_calls_saved_by_cache += 1
            return JudgeResult(
                grade=Grade(cached["grade"]),
                score=float(cached.get("score", local.score)),
                source=SOURCE_CACHE,
                feedback=cached.get("feedback", ""),
            )

        refined = self._ask_api(word, answer)
        return refined if refined is not None else local

    def _ask_api(self, word: Word, answer: str) -> Optional[JudgeResult]:
        """问一次模型。任何异常都安静地放弃,让调用方用本地结果顶上。

        软件绝不硬依赖网络 —— 断网时功能完整,只是"话少一点"。

        人设和历史一起带上:这样判分请求的前缀和对话、诊断**完全一样**,
        缓存能复用,而且判分时说话的是同一个角色(用户 2026-10-17 的要求)。
        """
        persona, history = self._context()
        try:
            item = JudgeItem(word_id=word.id, word=word.word,
                             translation=word.translation, answer=answer)
            results = self.ai_provider.judge_batch([item], persona, history)
        except Exception as exc:  # noqa: BLE001 —— 故意兜住一切网络异常
            from . import storage
            storage.log_error("调用 AI 判分失败,已回退到本地判分: %s" % exc)
            return None

        self.api_calls_made += 1
        if not results:
            return None

        result = results[0]
        self.cache[cache_key(word, answer)] = {
            "grade": result.grade.value,
            "score": result.score,
            "feedback": result.feedback,
        }
        # ⚠️ 判分也记进共用历史,而且**只记人话**:
        # 用户答了什么 + 老师怎么反应的。那份 {"w":..., "v":...} 的机器数据
        # 不进历史 —— 用户翻对话记录时看到的应该是对话,不是一堆 JSON;
        # 而且历史里内容一致,前缀缓存才稳定(见 core/ai_context.py)。
        self._remember_judgement(word, answer, result)
        return JudgeResult(result.grade, result.score, SOURCE_AI, result.feedback)

    def _context(self):
        """取当前的人设和历史。没有上下文对象时给空值(纯离线也能跑)。"""
        if self.conversation is None:
            return "", []
        return self.conversation.persona(), self.conversation.snapshot()

    def _remember_judgement(self, word: Word, answer: str, result: JudgeResult) -> None:
        """把这一次判分记成一轮"人话"对话。

        老师那一边只写**判定结果**("答对了 / 沾点边 / 答错了"),不写 JSON、
        也不写反馈原文 —— 理由:

        * 用户翻对话记录时看到的是这个,应该是人话;
        * 模型下一次看到历史时,知道上一题判成了什么(这本身就是有用的语境);
        * 历史里内容稳定,前缀缓存才不会被一次判分就打掉。
        """
        if self.conversation is None:
            return
        self.conversation.remember(
            "%s的意思是?我答:%s" % (word.word, answer),
            _JUDGE_VERDICT_LABELS.get(result.grade, "看过了"))

    # ---- 统计(界面上要给用户看"这场省了多少") --------------------------

    def stats(self) -> Dict[str, int]:
        return {
            "api_calls": self.api_calls_made,
            "cache_hits": self.api_calls_saved_by_cache,
        }
