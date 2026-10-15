# -*- coding: utf-8 -*-
"""可选的大模型接入(OpenAI 兼容接口)。

**这是整个程序里唯一会联网的模块。** 默认关闭,不填密钥就等于不存在。
软件的核心体验(背词、判分、复习调度、角色台词)全部在本地完成,
这一层只是"话更多、更懂你"的加分项。

三个必须守住的约定:

1. **失败绝不抛到界面上。** 网络断了、密钥错了、接口改版了 ——
   用户看到的最坏情况应该是"AI 今天话少",而不是一个报错弹窗。
   ApiProvider 抛 AIError,ChatService 接住并回退到本地文案。

2. **输出长度按用途分级。** 判分只要 64 个 token 就够,对话 300,
   诊断 500。**输出 token 才是账单的大头**,这是最直接的刹车。

3. **提示词的静态部分放最前面。** 人设 system prompt 排在最前、
   变量(单词、用户输入)排在最后,这样能命中服务端的前缀缓存 ——
   Anthropic 大约省 90%,OpenAI 大约省 50%。
"""

import json
import re
from typing import Any, Dict, List, Optional

from .interfaces import AIProvider, JudgeItem, JudgeResult, Turn
from .models import SOURCE_AI, Grade

try:
    import requests
except ImportError:                      # pragma: no cover - 环境异常时的兜底
    requests = None                      # type: ignore[assignment]


class AIError(RuntimeError):
    """调用大模型失败。带上人话原因,写进日志时能直接看懂。"""


# 输出长度分级。改这几个数之前先想清楚:账单是按输出 token 算的。
#
# ⚠️ 判分的额度**刻意不跟着人设变**。它输出的是固定格式的 JSON,放宽只会
# 增加跑题风险,不增加价值 —— 而人设那 1500 字属于**输入**,和这里是两回事。
MAX_TOKENS_JUDGE = 64
# 对话和诊断放宽了:人设本身很长(鲸鱼娘那一版有几十行),而且那段人设明确
# 鼓励"偶尔暴露内心戏、用干饭例句造句",300 个 token 会把话说一半就截断。
MAX_TOKENS_CHAT = 600
MAX_TOKENS_DIAGNOSE = 800

# 批量判分时每个词额外给一点额度,否则 20 个词共用 64 token 会被截断
TOKENS_PER_EXTRA_ITEM = 16
MAX_TOKENS_JUDGE_CEILING = 512

# 发给模型的历史条数上限(一条 = 一句,所以 40 条 ≈ 20 轮问答)。
#
# **为什么要"较大值"**:判分现在也进历史(用户 2026-10-17 的要求 ——
# 三个任务共用同一份历史,缓存前缀才一致)。一场 20 题的考试就是 20 轮,
# 老的 6 条小得只够 3 轮,前缀会一直往前滑、缓存一直不命中。
#
# **为什么不是"不限"**:每一轮都在下一次请求里重复发送,越长越贵;
# 而且超过模型的上下文窗口会直接报错。40 条配合 1500 字左右的人设,
# 每请求的输入大致在千级 token,是个能长期用的量级。
#
# 裁剪是**黏性的**:只在装不下时裁一次,不是每条都滑。滑动的窗口会让
# 前缀每轮都变,前缀缓存就永远命中不了 —— 那比留长一点贵得多。
MAX_HISTORY_MESSAGES = 40

# 判分用的**输出约定**(不是人设)。
#
# 它跟着**每一次判分请求的最后一条消息**走,不放进历史、也不放进 system ——
# 理由见 _build_messages:system 只放人设,这样三个任务的前缀完全一致。
JUDGE_OUTPUT_NOTE = (
    "【这一次的任务】下面是学生的作答,判断他答得对不对。\n"
    "只输出一个 JSON 数组,不要任何解释、不要 markdown 代码块。\n"
    "每个元素形如 {\"w\": \"<单词id>\", \"v\": 1}。\n"
    "v=1 表示正确,v=0 表示沾边但不准确,v=-1 表示错误。"
)

# 诊断的输出约定。同样只走最后一条消息。
DIAGNOSE_OUTPUT_NOTE = (
    "【这一次的任务】用你现在的身份,对鱼片同学这一轮的表现说两三句。\n"
    "要具体(指出哪里好、哪里该再看一眼),不要空洞地鼓励,"
    "不要罗列数字,不要 markdown。"
)

_JSON_ARRAY = re.compile(r"\[.*\]", re.DOTALL)

# 判分结果里 v 的取值 → 判分等级
_VERDICT_TO_GRADE = {1: Grade.CORRECT, 0: Grade.FUZZY, -1: Grade.WRONG}


# --------------------------------------------------------------------------
# 统一的消息装配:三个任务共用一个前缀
# --------------------------------------------------------------------------
#
# 这是"缓存命中"的落点,所以规则写在这里一次,别在别处拼 messages。
#
# 形状永远是:
#
#     system:    <人设>                      ← 只有人设,没有第二个角色
#     user:      历史第 1 句                  ┐
#     assistant: 历史第 2 句                  │ 同一份对话历史
#     ...                                    ┘
#     user:      <这一次要它做的事>            ← 每个任务不同,就这一条
#
# 为什么 system 里**只**放人设:
# 早先判分用的是写死的"你是单词判分助手",诊断用的是"你是一位语言学习教练" ——
# 用户选了鲸鱼娘,判分和评语却换了个人说话(用户 2026-10-17:这样"对话非常割裂")。
# 现在三件事共用同一段人设,于是前缀逐字节一致,前缀缓存能一路命中。
#
# 为什么任务约定放**最后一条 user** 而不是 system:
# 放进 system 就等于每个任务的前缀各不相同,缓存白搭;而且用户翻对话记录时
# 会看到一串内部指令。放最后一条,它只存在于当次请求里。

def _build_messages(persona: str, history: Optional[List[Turn]],
                    task_message: str) -> List[Dict[str, str]]:
    """按上面的形状拼出 messages。三个任务都走这里。"""
    messages: List[Dict[str, str]] = [
        # 人设为空时给一句中性兜底,而不是留空 —— 空 system 会让模型
        # 自由挑一个身份,那正是我们要避免的"割裂"
        {"role": "system", "content": persona.strip() or "你是一位耐心的语言老师。"},
    ]
    for turn in (history or [])[-MAX_HISTORY_MESSAGES:]:
        role = turn.role if turn.role in ("user", "assistant") else "user"
        messages.append({"role": role, "content": turn.content})
    messages.append({"role": "user", "content": task_message})
    return messages


def judge_task_message(items: List[JudgeItem]) -> str:
    """判分那一条 user 消息:先人话,再机器可读的 JSON,最后是输出约定。

    **为什么要有"人话"那一段**:判分现在也进对话历史(见 core/judge.py),
    所以模型看到的历史里全是对话。如果这一条突然变成一坨 JSON,它就会
    在"聊天"和"做题"之间反复切换语气 —— 那正是用户说的割裂。
    人话那段让它知道"这仍然是在和我说话",JSON 只是附上的材料。

    **人话里和 JSON 里都有答案,这是有意的**:历史里要留人话(用户在
    对话记录里要看得懂),而 JSON 里带 id 才回得出 {"w": ...} 这种可解析的结果。
    两个都放,代价是几十个 token,换来两边都成立。
    """
    lines = ["%s的意思是?鱼片答:%s" % (item.word, item.answer)
             for item in items]
    payload = json.dumps(
        [{"id": item.word_id, "word": item.word,
          "meaning": item.translation, "answer": item.answer}
         for item in items], ensure_ascii=False)
    return "%s\n\n%s\n\n%s" % ("\n".join(lines), payload, JUDGE_OUTPUT_NOTE)


def diagnose_task_message(summary: Dict[str, Any]) -> str:
    """诊断那一条 user 消息:把汇总数字说成人话,再附一句输出约定。

    刻意**不**直接丢 JSON:那样模型突然要读机器数据,评语会变回"分析报告"
    的口气,人设就断了。说成人话它就还能用角色的口吻回一句。
    """
    parts = []
    if summary.get("pack"):
        parts.append("这一轮是「%s」" % summary["pack"])
    parts.append("一共碰了 %d 个词" % summary.get("total", 0))
    parts.append("其中记住 %d" % summary.get("known", 0))
    if summary.get("fuzzy"):
        parts.append("有点模糊 %d" % summary["fuzzy"])
    if summary.get("new"):
        parts.append("还没见过 %d" % summary["new"])
    if summary.get("due_today"):
        parts.append("今天另有 %d 个词到期该复习" % summary["due_today"])
    return "%s。\n\n%s" % (",".join(parts), DIAGNOSE_OUTPUT_NOTE)


# --------------------------------------------------------------------------
# 离线后端:让"没配 API"也是一条正常路径
# --------------------------------------------------------------------------

class NullAIProvider(AIProvider):
    """什么都不做的 AI 后端。

    存在的意义是让内核**永远有一个可用的 AIProvider** —— 这样界面代码
    不必到处写 `if provider is not None`。它返回空结果,而空结果在
    JudgeService 里等于"本地判定说了算",在 ChatService 里等于"用本地台词"。
    """

    name = "null"

    def judge_batch(self, items: List[JudgeItem], persona: str = "",
                    history: Optional[List[Turn]] = None) -> List[JudgeResult]:
        return []

    def chat(self, persona: str, history: List[Turn], user_message: str) -> str:
        return ""

    def diagnose(self, summary: Dict[str, Any], persona: str = "",
                 history: Optional[List[Turn]] = None) -> str:
        return ""


# --------------------------------------------------------------------------
# OpenAI 兼容后端
# --------------------------------------------------------------------------

class ApiProvider(AIProvider):
    """走 OpenAI 兼容 /chat/completions 的后端。

    兼容它的服务很多(OpenAI、DeepSeek、通义、各种本地推理服务……),
    所以这里不绑定任何一家,只要求填 base_url 和 model。

    ⚠️ 失败时抛 AIError,而不是静默返回空值。原因:静默失败会让
    "密钥填错了"表现成"AI 一直不说话",用户根本无从排查。
    由调用方(ChatService / JudgeService)负责决定怎么回退。
    """

    name = "openai_compatible"

    def __init__(self, ai_settings) -> None:
        """ai_settings 是 config.AiSettings。"""
        self.settings = ai_settings

    # ---- 底层请求 --------------------------------------------------------

    def _endpoint(self) -> str:
        """拼出 /chat/completions 的完整地址。

        用户填的 base_url 可能带尾斜杠,也可能已经带上了 /chat/completions,
        两种都容忍 —— 让用户去猜"该不该带斜杠"是很糟糕的体验。
        """
        base = (self.settings.base_url or "").strip().rstrip("/")
        if not base:
            raise AIError("还没有填写接口地址")
        if base.endswith("/chat/completions"):
            return base
        return base + "/chat/completions"

    def _post(self, messages: List[Dict[str, str]], max_tokens: int,
              temperature: float) -> str:
        """发一次请求,返回模型输出的文本。

        抛出 AIError 的所有情况都在这里集中处理,上层不必再关心
        HTTP 细节。
        """
        if requests is None:
            raise AIError("本机没有安装 requests,无法调用大模型")
        if not self.settings.model:
            raise AIError("还没有填写模型名")
        if not self.settings.api_key:
            raise AIError("还没有填写密钥")

        payload = {
            "model": self.settings.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        headers = {
            "Authorization": "Bearer %s" % self.settings.api_key,
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                self._endpoint(), json=payload, headers=headers,
                timeout=self.settings.timeout_seconds,
            )
        except Exception as exc:            # 超时、DNS、TLS、断网……
            raise AIError("请求失败:%s" % exc)

        if response.status_code != 200:
            # 把响应体截断后带上 —— 服务端的报错信息通常很有用,
            # 但整段塞进日志也没必要
            raise AIError("接口返回 %d:%s"
                          % (response.status_code, response.text[:200]))

        try:
            data = response.json()
            return data["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AIError("看不懂接口返回的内容:%s" % exc)

    # ---- 判分 ------------------------------------------------------------

    def judge_batch(self, items: List[JudgeItem], persona: str = "",
                    history: Optional[List[Turn]] = None) -> List[JudgeResult]:
        """批量判分。**一次请求判完整个列表** —— 这是省 Token 的关键机制。

        返回的列表可能比输入短(模型漏答了某几项)。调用方按 word_id
        对不上时应当丢弃这一项、继续用本地判定,而不是整体作废。

        人设和历史一起带上:这样判分请求的前缀和对话、诊断**完全一样**,
        前缀缓存能复用(见模块开头的说明)。
        """
        if not items:
            return []

        budget = min(MAX_TOKENS_JUDGE_CEILING,
                     MAX_TOKENS_JUDGE + TOKENS_PER_EXTRA_ITEM * (len(items) - 1))
        messages = _build_messages(persona, history, judge_task_message(items))
        text = self._post(messages, max_tokens=budget, temperature=0.0)
        return self._parse_verdicts(text, items)

    @staticmethod
    def _parse_verdicts(text: str, items: List[JudgeItem]) -> List[JudgeResult]:
        """把模型输出的 JSON 数组解析成判分结果。

        模型有时会把 JSON 包在 markdown 代码块里,或者前后加一句话,
        所以先用正则把数组抠出来,再从宽松到严格地解析。
        """
        match = _JSON_ARRAY.search(text)
        if match is None:
            raise AIError("模型没有返回 JSON 数组:%s" % text[:120])

        try:
            entries = json.loads(match.group(0))
        except ValueError as exc:
            raise AIError("模型返回的 JSON 解析失败:%s" % exc)

        results: List[JudgeResult] = []
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            try:
                grade = _VERDICT_TO_GRADE[int(entry.get("v"))]
            except (TypeError, ValueError, KeyError):
                # 模型给了个没见过的取值,跳过这一项,交给本地判定
                continue
            results.append(JudgeResult(
                grade=grade,
                score=1.0 if grade == Grade.CORRECT else 0.5,
                source=SOURCE_AI,
                feedback="",
            ))
        return results

    # ---- 自由对话 --------------------------------------------------------

    def chat(self, persona: str, history: List[Turn], user_message: str) -> str:
        """带人设的自由对话。只在用户主动提问时调用。"""
        messages = _build_messages(persona, history, user_message)
        return self._post(messages, max_tokens=MAX_TOKENS_CHAT,
                          temperature=0.8).strip()

    # ---- 诊断 ------------------------------------------------------------

    def diagnose(self, summary: Dict[str, Any], persona: str = "",
                 history: Optional[List[Turn]] = None) -> str:
        """根据学习统计生成一段个性化评语。**一场学习只调一次。**

        传进来的 summary 只有汇总数字(见 stats.build_diagnosis_payload),
        不带单词细节 —— 让这个请求尽可能小。

        ⚠️ **不再用写死的"语言学习教练"**:那段提示词会让评语突然换成
        另一个人的口气,和用户选的人设割裂(用户 2026-10-17 的要求)。
        现在人设来自当前选中的人设;汇总数字**说成人话**放在最后一条消息里,
        这样评语仍然是"老师在跟学生说话",而不是一份分析报告。
        """
        messages = _build_messages(persona, history,
                                   diagnose_task_message(summary))
        return self._post(messages, max_tokens=MAX_TOKENS_DIAGNOSE,
                          temperature=0.7).strip()
