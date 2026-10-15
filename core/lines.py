# -*- coding: utf-8 -*-
"""L1 台词层:零成本的角色发言。

**这一层是省 Token 的主力。** AI 教师说的绝大多数话都来自这里,
一次网络请求都不发。大模型只在三个受控点被调用(见 judge.py 和
AIProvider.diagnose 的说明),其余全由本地台词库 + 本地情绪规则顶上。

两个刻意的设计:

1. **情绪由本地规则决定,不问模型。** "答对→开心,答错→难过"这种判断
   不需要大模型,用规则既免费又稳定。把情绪交给模型还会带来不确定性:
   同一个答案有时被判定为"鼓励",有时被判定为"失望",用户会觉得这老师精神状态不稳定。

2. **同一组台词不连续重复。** 每个键下存多条变体,取用时排队抽取,
   一轮抽完再重新洗牌 —— 保证"复读感"不会在短时间内出现。

台词键的格式是 "{话题}:{情绪}",例如 "correct:happy"。
LinePack.lookup() 会自动回退:精确键 → {话题}:normal → *:normal,
所以插件作者只写几条也能用。
"""

import random
from typing import Dict, List, Optional, Tuple

from .interfaces import (
    EMOTION_CONFUSED,
    EMOTION_HAPPY,
    EMOTION_NORMAL,
    EMOTION_SAD,
    EMOTION_SURPRISED,
    EMOTION_THINKING,
    LinePack,
)
from .interfaces import JudgeResult
from .models import Grade, Mastery, Word

# 除判分结果之外,还有几个"话题"用同一套台词机制。
# 它们不是判分结果,所以单独起名,免得和 "correct"/"wrong" 混淆。
TOPIC_GREETING = "greeting"          # 进入学习/考试时说的一句
TOPIC_SESSION_END = "session_end"    # 一场学习结束后
TOPIC_EMPTY = "empty"                # 用户什么都没输入就回车
TOPIC_IDLE = "idle"                  # 停顿太久
TOPIC_ASK = "ask"                    # 用户主动提问时,老师准备回答
# 在别的页面上点老师时的一句反应。它和 TOPIC_ASK 不同:那个是"我要回答了",
# 这个是"你怎么突然戳我" —— 用户点在立绘上,而不是在问问题。
TOPIC_CHAT_OPEN = "chat_open"


# --------------------------------------------------------------------------
# 情绪规则(本地,零成本)
# --------------------------------------------------------------------------

def emotion_for(result: JudgeResult, word: Optional[Word], answer: str) -> str:
    """根据判分结果挑一个立绘情绪。

    answer 是**必填**的,不给默认值 —— 因为"用户什么都没输入"和
    "调用方没传这个参数"会导出完全不同的情绪,用一个默认空串把两者
    混在一起,迟早会有人忘记传,然后得到一张莫名其妙的困惑脸。

    ⚠️ 调用时机是**判分之后**,此时 word.state 已经推进过了。
    这一点对"遗忘"的判断很关键:一个原本 KNOWN 的词答错后,
    state.mastery 会变成 RELEARN —— 正是在这个时刻我们才知道
    "哦,这个词他以前是会背的"。所以这里读的是新状态,不是旧状态。
    """
    if not (answer or "").strip():
        return EMOTION_CONFUSED

    if result.grade == Grade.CORRECT:
        return EMOTION_HAPPY

    if result.grade == Grade.FUZZY:
        return EMOTION_THINKING

    # 答错。如果这是"掌握过又忘了"的词,值得表现出惊讶 ——
    # 这比单纯说"答错了"更能提示用户"这个词该重新过一遍了"。
    if word is not None and word.state.mastery == Mastery.RELEARN:
        return EMOTION_SURPRISED
    return EMOTION_SAD


# --------------------------------------------------------------------------
# 默认台词库
# --------------------------------------------------------------------------

def default_zh_lines() -> Dict[str, List[str]]:
    """简体中文台词。键的写法与回退规则见模块开头。"""
    return {
        # ---- 答对 ----
        "correct:happy": [
            "答对了!这个词你已经很稳了~",
            "漂亮,就是这个意思。",
            "嗯嗯,完全正确!",
            "对的,继续保持这个感觉。",
            "很好,这个词可以放心了。",
        ],
        "correct:normal": [
            "正确。",
            "对的。",
            "嗯,答对了。",
        ],
        # ---- 模糊 ----
        "fuzzy:thinking": [
            "沾边了,但还差一点点,再想想?",
            "方向对,不过意思没答全。",
            "嗯……很接近了,但还不太一样。",
            "差不多是这个意思,可惜不够准确。",
        ],
        "fuzzy:confused": [
            "有点接近,但我不太确定你指的是哪一层意思。",
        ],
        # ---- 答错 ----
        "wrong:sad": [
            "不太对哦,再看看正确释义。",
            "这个词还没记住呢,记下来。",
            "咦,好像记错了。没关系,错一次记得更牢。",
            "答案是另一个意思,再读一遍。",
        ],
        "wrong:surprised": [
            "咦?这个词你之前是背下来的,现在忘了,要重新过一遍了。",
            "我记得你以前会这个词的……看来得复习一下了。",
        ],
        # ---- 空输入 ----
        "empty:confused": [
            "还没输入答案呢~",
            "嗯?你好像什么都没写。",
            "先写点什么再回稿吧。",
        ],
        # ---- 开场 ----
        "greeting:normal": [
            "那我们开始吧~",
            "准备好了吗?开始今天的学习。",
            "先来看看今天要背的词。",
        ],
        "greeting:happy": [
            "今天状态看起来不错,开始吧!",
        ],
        # ---- 结束 ----
        "session_end:happy": [
            "这一轮完成得很好,去休息一下吧~",
            "今天表现很棒,记得明天按时回来哦。",
        ],
        "session_end:normal": [
            "这一轮结束啦,记忆曲线已经帮你安排好下次复习。",
            "辛苦了,到期的词我们明天再见。",
        ],
        "session_end:sad": [
            "这一轮错得有点多,不过没关系,错的词已经排进复习计划了。",
            "别灰心,难词多过几遍就熟了。",
        ],
        # ---- 提问 ----
        "ask:thinking": [
            "让我想想怎么跟你讲……",
        ],
        # ---- 在别的页面上戳了老师一下 ----
        # 语气是"你又来",而不是"我在听" —— 用户点的是立绘,不是在提问
        "chat_open:normal": [
            "看我干什么,背单词啊。",
            "怎么了?想聊天的话点我一下就行。",
            "嗯?是这页有哪里看不懂吗。",
            "我在这儿呢。要聊天就说一声。",
        ],
        # ---- 兜底:任何话题、任何情绪都能取到这里 ----
        "*:normal": [
            "嗯,我在这儿。",
        ],
    }


def default_en_lines() -> Dict[str, List[str]]:
    """English lines. Deliberately short — it exists so the language switch
    isn't a lie, not to be a full translation."""
    return {
        "correct:happy": ["Correct! Nicely done.", "That's right!"],
        "fuzzy:thinking": ["Close, but not quite. Try again?"],
        "wrong:sad": ["Not quite — have another look.", "Not yet, but that's fine."],
        "wrong:surprised": ["You knew this one before. Let's review it again."],
        "empty:confused": ["You haven't typed anything yet."],
        "greeting:normal": ["Let's begin, shall we?"],
        "session_end:normal": ["That's the end of this round. See you tomorrow."],
        "chat_open:normal": ["What are you looking at me for? Go memorise words."],
        "*:normal": ["I'm here."],
    }


def default_linepack(language: str = "zh-CN") -> LinePack:
    """默认台词包。language 不认识时一律给中文 —— 主用户是中文用户,
    宁可给中文也不要给一份空台词导致老师一言不发。"""
    if language == "en":
        return LinePack(name="default_en", language="en", lines=default_en_lines())
    return LinePack(name="default_zh", language="zh-CN", lines=default_zh_lines())


# --------------------------------------------------------------------------
# 取台词
# --------------------------------------------------------------------------

class LineSelector:
    """从台词包里取话,并保证不会连续重复。

    为什么不直接 random.choice?因为台词一组只有 4~5 条,
    随机取的话连着两次抽到同一句的概率相当高(20%),用户立刻就会觉得
    "这老师在复读"。改成"排队抽"之后,一轮之内绝不重复,
    抽完才重新洗牌 —— 代价是零,体验差别却很明显。
    """

    def __init__(self, pack: LinePack, rng: Optional[random.Random] = None) -> None:
        self.pack = pack
        self._rng = rng or random.Random()
        self._queues: Dict[str, List[str]] = {}
        self._last: Dict[str, str] = {}

    def line(self, grade: str, emotion: str = EMOTION_NORMAL) -> str:
        """取一句台词。找不到任何可用台词时返回空串(界面应当能容忍不显示)。"""
        group = self.pack.lookup(grade, emotion)
        if not group:
            return ""

        key = "%s:%s" % (grade, emotion)
        queue = self._queues.get(key)
        if not queue:
            queue = list(group)
            self._rng.shuffle(queue)
            self._avoid_repeating_across_refill(queue, self._last.get(key))
            self._queues[key] = queue

        chosen = queue.pop()
        self._last[key] = chosen
        return chosen

    def _avoid_repeating_across_refill(self, queue: List[str], previous: Optional[str]) -> None:
        """重新洗牌后,别让新一轮的第一句和上一轮的收尾撞上。

        只在队列**抽空重灌**的那一瞬间会撞车 —— 队内是不会重复的。
        所以这里只需要检查队尾(下一句要被抽走的那条)。
        换位置而不是重洗,是为了保证"确实换了"而不是"可能又洗回原样"。
        """
        if previous is None or len(queue) < 2 or queue[-1] != previous:
            return
        queue[-1], queue[0] = queue[0], queue[-1]

    def react(self, word: Optional[Word], result: JudgeResult,
              answer: str = "") -> Tuple[str, str]:
        """判分后的一整套反应:返回 (情绪, 台词)。

        这是界面最常用的入口 —— 判完分调一次,拿到立绘该摆什么表情、
        对话框该写什么字。
        """
        emotion = emotion_for(result, word, answer)
        if not (answer or "").strip():
            # 空输入不算答错,不该走"正确答案是……"那套反馈
            return emotion, self.line(TOPIC_EMPTY, emotion)
        return emotion, self.line(result.grade.value, emotion)

    def greet(self) -> Tuple[str, str]:
        return EMOTION_HAPPY, self.line(TOPIC_GREETING, EMOTION_HAPPY)

    def farewell(self, correct: int, total: int) -> Tuple[str, str]:
        """一场学习结束。按正确率挑语气 —— 这是纯本地规则,零成本。"""
        if total <= 0:
            return EMOTION_NORMAL, self.line(TOPIC_SESSION_END, EMOTION_NORMAL)
        rate = correct / float(total)
        if rate >= 0.8:
            emotion = EMOTION_HAPPY
        elif rate >= 0.5:
            emotion = EMOTION_NORMAL
        else:
            emotion = EMOTION_SAD
        return emotion, self.line(TOPIC_SESSION_END, emotion)


def is_question(text: str) -> bool:
    """判断用户是不是在**提问**(而不是在答题)。

    这条规则很重要:默认把打字当作答题,只有当用户明显在提问时才进入
    自由对话 —— 因为自由对话要调 API,一次就是几百个 token。
    如果在答题框里随便打几个字就触发对话,省 Token 的设计就全废了。

    判据刻意保守:出现问号,或者以几个明确的疑问词开头。宁可漏判
    (用户把问题换个说法再打一遍 —— 考试页**没有**「问老师」按钮了,
    提问入口就是输入框本身)也不要误判(答题变成烧钱的聊天)。
    """
    stripped = (text or "").strip()
    if not stripped:
        return False
    if "?" in stripped or "？" in stripped:
        return True
    for prefix in ("请问", "为什么", "怎么", "如何", "什么是", "能不能解释"):
        if stripped.startswith(prefix):
            return True
    return False
