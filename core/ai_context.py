# -*- coding: utf-8 -*-
"""AI 的"当前对话"与"当前人设" —— 三个任务共用的一份上下文。

## 为什么需要单独一个对象

用户 2026-10-17 的要求是:**判分、对话、诊断三件事共用一个角色和一段记忆**,
这样发给模型的前缀完全一致、缓存一路命中,而且用户从头到尾面对同一个人。

这就需要一个**唯一的**持有者。早先历史挂在 ChatService 里,判分完全不记 ——
判分每一题都是冷启动,还可能用完全不同的语气回答(它以前挂着写死的
"你是单词判分助手")。

## 两个关键设计

**一、人设是"调用时现读",不是启动时拷贝。**

早先 `ChatService` 在启动和"设置保存"时把人设**拷贝**一份存起来 ——
用户在 AI 选择页切了人设,对话却还在用旧的,要重启才生效。
这里持有一个 `persona_provider` 回调,每次真的发请求时才去问
"现在是谁",所以切换立刻生效。

**二、历史只留"人话"。**

判分一次请求里含 `{"w": ..., "v": ...}` 这类机器数据。那些**不进历史** ——
用户翻对话记录时看到的应该是对话,不是一堆 JSON;而且历史里内容一致,
前缀才稳定。机器数据只活在当次请求里(见 core/ai_client 的消息装配)。
"""

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .interfaces import Turn

# 裁剪后的保留量。比上限小一些,这样裁一次能撑很多轮 ——
# 见 Conversation.trim() 里关于"别每轮都裁"的说明。
#
# 放在模块级而不是类里:它不是这个对话自己的状态,而是"这类对话共用的一个数"。
KEEP_AFTER_TRIM = 30


@dataclass
class Conversation:
    """一段对话历史。**判分 / 对话 / 诊断共用同一个实例。**"""

    persona_provider: Optional[Callable[[], str]] = None
    turns: List[Turn] = field(default_factory=list)

    @staticmethod
    def _limit() -> int:
        """每个请求的条数上限(从 core.ai_client 取,保持单一来源)。"""
        from .ai_client import MAX_HISTORY_MESSAGES
        return MAX_HISTORY_MESSAGES

    # ---- 人设 ------------------------------------------------------------

    def persona(self) -> str:
        """现在该用的 system 提示词。

        每次真的发请求时才调,所以用户切了人设**下一次请求就生效**。
        """
        if self.persona_provider is None:
            return ""
        try:
            return (self.persona_provider() or "").strip()
        except Exception:
            # 取人设失败不该让对话崩掉:退回空串,上层会用中性兜底人设
            return ""

    # ---- 历史 ------------------------------------------------------------

    def remember(self, user_text: str, assistant_text: str) -> None:
        """记一轮问答。**判分和对话都走这里。**

        空的那一半直接跳过(比如判分拿到了空的反馈),免得往历史里塞空消息 ——
        有些接口会因此报错,而且空消息对模型没有任何信息量。
        """
        if user_text:
            self.turns.append(Turn(role="user", content=user_text))
        if assistant_text:
            self.turns.append(Turn(role="assistant", content=assistant_text))
        self.trim()

    def trim(self) -> None:
        """超长时裁一次。

        ⚠️ **刻意不做"每轮滑一格"**。滑动的窗口会让前缀每轮都变,
        而前缀缓存要求"前面那段逐字节相同" —— 每轮都滑等于每轮都全部重算,
        比留长一点贵得多。所以这里只在**装不下时**裁一次,而且一次裁到
        KEEP_AFTER_TRIM,让接下来很多轮的前缀都稳定。
        """
        limit = self._limit()
        if len(self.turns) <= limit:
            return
        self.turns = self.turns[-KEEP_AFTER_TRIM:]

    def clear(self) -> None:
        """开新一场。清空发生在每次学习 / 考试开始时。"""
        self.turns = []

    def snapshot(self) -> List[Turn]:
        """给 AIProvider 用的只读视图。"""
        return list(self.turns)

    def __len__(self) -> int:
        return len(self.turns)
