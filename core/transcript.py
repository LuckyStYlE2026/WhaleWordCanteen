# -*- coding: utf-8 -*-
"""把一段对话存下来(用户退出时选择)。

## 存成两份,各有各的用处

* **`<时间>.md`** —— 给人看的。用记事本打开就是一段能读的对话记录,
  可以复制、可以打印、可以扔进任何笔记软件。
* **`<时间>.json`** —— 给程序看的。逐条保存,以后要"接着上次聊"或者
  做检索时读它,不必去解析那份给人看的排版。

两份都由这里生成,所以不会出现"记录里少了某几句"这种对不上的情况。

## 为什么不用一个文件

把人看的排版和机器读的结构塞进同一个文件,就得发明一种混合格式 ——
那既不方便人读,也不方便程序读。两份文件各几十 KB,不值得省。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from . import paths
from .interfaces import Turn
from .reply_format import strip_tag

# 存档格式版本。以后要改结构时靠它区分,而不是猜。
TRANSCRIPT_VERSION = 1

# 文件名里的时间戳。**不能只有日期** —— 同一天可能存好几次,
# 同名会把上一次覆盖掉,那是数据丢失而不是"整理"。
STAMP_FORMAT = "%Y%m%d_%H%M%S"


def _stamp(now: datetime) -> str:
    return now.strftime(STAMP_FORMAT)


def _header_lines(character: str, persona: str, when: datetime) -> List[str]:
    """记录开头的几行说明。**必须写清"用谁的人设"** ——

    同一份对话记录在不同人设下读起来是完全不同的一回事,而用户过几个月
    回来翻的时候,唯一能告诉他"当时那个傲娇的老师是哪个设定"的就是这几行。
    """
    lines = ["# 与 %s 的对话" % (character or "老师"),
             "",
             "- 时间:%s" % when.strftime("%Y-%m-%d %H:%M"),
             "- 人设:%s" % (persona or "(未命名)"),
             "",
             "---",
             ""]
    return lines


def to_markdown(turns: List[Turn], character: str = "", persona: str = "",
                when: datetime = None) -> str:
    """那份给人看的记录。

    说话人只在**换人**时才写一次 —— 连续几句同一个人的话挤在一起时,
    每句都顶一个名字会很难读。

    ⚠️ 老师那一边会先摘掉 `[情绪]` 标记(见 core/reply_format.py):
    那是**给机器看的指令**,用户读记录时看到 "[happy]" 只会莫名其妙。
    原始文本(带标记)在 .json 里完整保留着。
    """
    when = when or datetime.now()
    lines = _header_lines(character, persona, when)
    speaker = ""

    for turn in turns:
        content = (strip_tag(turn.content) if turn.role == "assistant"
                   else (turn.content or "")).strip()
        if not content:
            continue
        who = character if turn.role == "assistant" else "我"
        if who != speaker:
            if speaker:                 # 换人前空一行,分段清楚
                lines.append("")
            lines.append("**%s:**" % who)
            speaker = who
        lines.append(content)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def to_payload(turns: List[Turn], character: str = "", persona: str = "",
               when: datetime = None) -> Dict[str, Any]:
    """那份给程序看的记录。"""
    when = when or datetime.now()
    return {
        "version": TRANSCRIPT_VERSION,
        "saved_at": when.isoformat(timespec="seconds"),
        "character": character,
        "persona": persona,
        "turns": [{"role": turn.role, "content": turn.content}
                  for turn in turns],
    }


def save(turns: List[Turn], character: str = "", persona: str = "",
         when: datetime = None) -> Path:
    """把这段对话存进 save/chats/,返回那份 .md 的路径。

    turns 为空时**不写文件** —— 留一堆空白记录只会让 save/chats 变得没法看。
    """
    if not turns:
        return None

    when = when or datetime.now()
    folder = paths.chats_dir()
    folder.mkdir(parents=True, exist_ok=True)
    stamp = _stamp(when)

    markdown = folder / ("%s.md" % stamp)
    markdown.write_text(to_markdown(turns, character, persona, when),
                        encoding="utf-8")
    (folder / ("%s.json" % stamp)).write_text(
        json.dumps(to_payload(turns, character, persona, when),
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    return markdown
