# -*- coding: utf-8 -*-
"""自由对话的调度层。对应判分那边的 JudgeService。

界面只调 ask() / diagnose(),**永远不会收到异常**。

为什么要在 provider 之上再包一层?因为有三件事必须有人统一负责:

  1. **失败回退。** AIProvider 坦诚地抛 AIError(那是它的契约),
     但界面不能因为接口挂了就崩。这一层把异常换成一句本地台词。
  2. **历史裁剪。** 只带最近几轮对话发给模型。再往前的对当前回答没帮助,
     却要按输入 token 真金白银地付钱。
  3. **预算与状态。** 记住这场对话说了几轮、上次错在哪,界面要显示。

单独成模块,是因为它是"聊天这个功能"的完整逻辑,
而 ai_client.py 只负责"怎么把一句话发给模型"。
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# 历史裁剪的规则**不在这里**,在 core/ai_context.Conversation.trim() ——
# 判分和诊断读的是同一份历史,裁剪规则必须只有一个出处。
from .ai_client import AIError, NullAIProvider
from .ai_context import Conversation
from .interfaces import AIProvider, EMOTION_NORMAL, Turn
from .reply_format import parse_reply


@dataclass
class Reply:
    """老师的一次回话:**说什么**(text)和**什么表情**(emotion)。

    分成两个字段而不是返回一个字符串,是因为界面需要两样东西:
    对话框要文字,立绘要情绪。拼成一个字符串再让界面自己去拆,
    等于把"格式规范"漏到界面层 —— 那样每个显示回复的地方都得懂格式。
    """

    emotion: str
    text: str

    def __bool__(self) -> bool:
        """空回复算"假",这样 `if reply:` 和以前的 `if text:` 一样好写。"""
        return bool(self.text)


class ChatService:
    """自由对话调度。永不抛异常 —— 出问题就用本地台词顶上。

    ⚠️ **人设和历史不归它所有**,而是拿一个共用的 Conversation
    (见 core/ai_context.py)。判分和诊断读的是**同一份**上下文,这样
    三件事的前缀一致、缓存能复用,用户也从头到尾面对同一个人。
    """

    def __init__(self, provider: Optional[AIProvider] = None,
                 conversation: Optional[Conversation] = None,
                 fallback=None) -> None:
        """
        provider      AIProvider;None 或 NullAIProvider 都表示纯离线
        conversation  共用的对话上下文(人设 + 历史);None 就自己造一个空的
        fallback      取本地兜底台词的函数,签名 (topic, emotion) -> str
        """
        self.provider = provider
        self.conversation = conversation if conversation is not None else Conversation()
        self.fallback = fallback
        self.last_error = ""

    @property
    def history(self) -> List[Turn]:
        """历史(只读转发)。

        留这个属性是因为界面和测试一直在读 `chat.history`;真正的持有者是
        Conversation,所以这里做成转发而不是再存一份 —— 存两份迟早不一致。
        """
        return self.conversation.turns

    @property
    def persona_prompt(self) -> str:
        """当前人设。**每次读都是最新的**(用户切了人设立刻生效)。

        早先这是一个在启动时拷贝的普通属性,于是切人设要重启才生效。
        """
        return self.conversation.persona()

    @property
    def is_online(self) -> bool:
        """是否可能真的问到模型。界面上据此显示"离线模式"提示。

        判据是"不是空后端"而不是"是内置的 ApiProvider" ——
        插件写的后端同样应该被当作在线,否则它会被无声地跳过。
        """
        return self.provider is not None and not isinstance(self.provider, NullAIProvider)

    def ask(self, user_message: str) -> Reply:
        """问一句,拿一句回复(含情绪)。

        返回值是 Reply,不是字符串 —— 模型会在开头写一个 [情绪] 标记
        (见 core/reply_format.py),这里把它拆出来交给界面选立绘。
        界面上想只拿文字的话用 reply.text。
        """
        text = (user_message or "").strip()
        if not text:
            return Reply(EMOTION_NORMAL, "")

        if not self.is_online:
            return self._local_reply("ask", "thinking")

        try:
            answer = self.provider.chat(self.persona_prompt,
                                        self.conversation.snapshot(), text)
        except AIError as exc:
            self._record_error(exc)
            return self._local_reply("ask", "confused")
        except Exception as exc:             # 契约之外的问题也不该让界面崩
            self._record_error(exc)
            return self._local_reply("ask", "confused")

        if not answer:
            return self._local_reply("ask", "thinking")

        # 只记成功的一轮。失败的对话不该污染上下文,否则模型会一直
        # 看到自己上次没答上来。
        #
        # ⚠️ 记进历史的是**原样**(连情绪标记一起),不是拆过的正文:
        # 模型看到自己上一条写了 [happy],下一条才知道该接着这么写。
        # 只喂它净化后的文字,它会渐渐忘掉这个约定。
        self.conversation.remember(text, answer)

        emotion, clean = parse_reply(answer)
        return Reply(emotion, clean)

    def diagnose(self, summary: Dict[str, Any], offline_text: str = "") -> str:
        """生成一次学习诊断。失败时用传入的离线文案兜底。

        offline_text 由调用方从 stats.diagnosis_text() 取,所以这里不 import
        stats —— 少一条依赖,这个类就更好测。

        同样带上共用的人设和历史:这样"老师"在评语里的口气和在对话里一致,
        而且前缀和对话、判分相同,缓存能复用。
        """
        if not self.is_online:
            return offline_text
        try:
            text = self.provider.diagnose(summary, self.persona_prompt,
                                          self.conversation.snapshot())
        except Exception as exc:
            self._record_error(exc)
            return offline_text
        if not text:
            return offline_text
        # 诊断也算一次"老师说过的话",记进同一份历史 —— 用户之后接着问,
        # 她是记得自己刚才点评过什么的。只记人话,不记那份汇总数字。
        self.conversation.remember(
            "这一轮学完了,说说我怎么样?", text)
        return text

    def reset(self) -> None:
        """开始新一场学习时清空对话历史。留着上一场的内容只会白花输入 token。"""
        self.conversation.clear()

    # ---- 内部 ------------------------------------------------------------

    def _local_reply(self, topic: str, emotion: str) -> Reply:
        """离线 / 出错时的兜底回复。

        情绪由**本地规则**给(调用方传进来的 emotion),而不是让兜底台词
        自己写标记 —— 本地台词本来就配着本地算出的情绪,再走一遍解析
        只会多一层出错的机会。

        ⚠️ 兜底台词里如果**碰巧**以 `[xxx]` 开头也不会被当指令:
        这里不调 parse_reply。本地台词是人写的,人写什么就显示什么。
        """
        return Reply(emotion, self._local_line(topic, emotion))

    def _local_line(self, topic: str, emotion: str) -> str:
        if self.fallback is None:
            return ""
        try:
            return self.fallback(topic, emotion)
        except Exception:                    # 兜底函数只是台词,不该让它带崩对话
            return ""

    def _record_error(self, exc: Exception) -> None:
        self.last_error = str(exc)
        from . import storage                 # 局部 import,避免和 storage 循环
        storage.log_error("AI 调用失败,已回退到本地台词: %s" % exc)
