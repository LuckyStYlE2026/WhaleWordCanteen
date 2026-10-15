# -*- coding: utf-8 -*-
"""AI 回复的格式规范,以及把回复拆成"情绪 + 正文"的解析器。

## 为什么需要这个文件

游戏要把 AI 说的话**放进对话框并选一张立绘**。对话框只有 3~6 行(实测:
720p 约 3 行、1080p 约 6 行,见 ui/scene_layers._draw_body),立绘则按情绪取图。
所以模型不能自由发挥版式 —— 它必须按一个**游戏读得懂**的格式回答。

## 回复格式(约定)

    回复 := [情绪标记] 正文

* **情绪标记**可选,写在**最前面**,一对方括号里一个英文词,取值见
  `core.interfaces.ALL_EMOTIONS`。例如 `[happy] 不错嘛,鱼片。`
* 没有标记就按 `normal` 处理 —— 模型偶尔忘了写不该导致立绘不换。
* 正文**最多 3 行**,只写要说的话。不要 markdown、不要列表、不要多段落。

## 解析必须"宽容到不会坏"

模型不总是守规矩:可能写成 `[HAPPY]`、`【happy】`、`[开心]`,或者干脆不写。
所以解析的规则是:

* 认不出来 → 当 `normal`,**正文一个字都不改**;
* 认出来 → 只摘掉标记本身,正文其余部分原样保留。

绝不做"猜"和"纠正"。理由:这段文字是**要显示给用户看的**,
误删或改写比"立绘没换"糟糕得多 —— 前者是内容出错,后者只是少个表情。

## 和"情绪由本地规则决定"的关系

`core/lines.py` 那条规则说的是**本地台词**:那些不经模型的台词,情绪由
本地按判分结果选(答对 → happy),这样离线也能换表情。

AI 回复是另一回事:既然已经付了这次请求的钱,让它在回答里捎带一个情绪词
几乎不增加成本,却能让立绘和它说的话对上。这两者不冲突 ——
本地台词走本地规则,AI 回复走这里的标记,**都只用同一份情绪白名单**。
"""

import re
from typing import Tuple

from .interfaces import ALL_EMOTIONS, EMOTION_NORMAL

# 允许的情绪标记:方括号里一个英文词。半角/全角括号都认。
#
# 只认"紧贴在开头"的标记 —— 正文中间的方括号是正常内容(比如
# "这个词的搭配是 [make a decision]"),不能当成指令摘掉。
_TAG = re.compile(r"^\s*[\[【]\s*([A-Za-z]+)\s*[\]】]\s*")

# 给模型看的说明。**要短** —— 它每次请求都会出现在人设提示词后面,
# 按输入 token 计费。
FORMAT_HINT = (
    "回复格式:如果在最前面写 [情绪] 就能换表情,情绪只能取 "
    + " / ".join(ALL_EMOTIONS) + " 之一,例如 [happy]。"
    "不写就按 normal。正文最多 3 行,只写要说的话;"
    "不要 markdown、不要列表、不要多段落。"
)


def parse_reply(raw: str) -> Tuple[str, str]:
    """把模型回复拆成 (情绪, 正文)。

    返回的正文**一定**是可以直接显示的文字:标记已经摘掉,前后空白也去过。
    空回复返回 (normal, "")。认不出的标记原样留在正文里,不猜、不删。
    """
    text = (raw or "").strip()
    if not text:
        return EMOTION_NORMAL, ""

    match = _TAG.match(text)
    if match is None:
        return EMOTION_NORMAL, text

    emotion = match.group(1).lower()
    if emotion not in ALL_EMOTIONS:
        # 认不出来:整个当正文。宁可立绘不换,也不能把用户要看的话改掉。
        return EMOTION_NORMAL, text

    return emotion, text[match.end():].strip()


def strip_tag(raw: str) -> str:
    """只要正文。给"不在乎情绪、只想显示文字"的地方用。"""
    return parse_reply(raw)[1]


__all__ = ["FORMAT_HINT", "parse_reply", "strip_tag"]
