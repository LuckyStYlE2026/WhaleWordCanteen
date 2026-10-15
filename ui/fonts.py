# -*- coding: utf-8 -*-
"""字体与排版。**纯 Pillow,不认识 Tkinter。**

单独成一个模块,是因为"怎么把字画到图上"和"界面配色长什么样"
是两件互不相干的事 —— 想让对话框换个字体,不该翻遍整个主题文件。

有两个 Pillow 版本上的坑必须在这里挡住:
  * Pillow 10 删掉了 font.getsize(),只能改用 getlength()/getmetrics()。
    网上抄来的老代码会在这一行直接报 AttributeError。
  * 中文字体不一定存在(非 Windows 系统、精简版系统)。找不到时必须
    退回 Pillow 内置字体 —— 它只能显示 ASCII,但至少程序还能跑起来,
    而不是在合成第一帧画面时就崩掉。
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import ImageFont

# 按优先级排列的中文字体。微软雅黑最好看,黑体是保底。
_FONT_FILES = ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc", "Deng.ttf")
_FONT_DIRS = (Path("C:/Windows/Fonts"), Path("/System/Library/Fonts"),
              Path("/usr/share/fonts"))

_font_cache: Dict[Tuple[int, bool], ImageFont.FreeTypeFont] = {}


def font_path(bold: bool = False) -> Optional[str]:
    """找一个能显示中文的字体文件。找不到返回 None。"""
    names = ("msyhbd.ttc", "simhei.ttf", "msyh.ttc") if bold else _FONT_FILES
    for folder in _FONT_DIRS:
        if not folder.exists():
            continue
        for name in names:
            candidate = folder / name
            if candidate.exists():
                return str(candidate)
    return None


def get_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    """取一个字体对象,按 (字号, 粗体) 缓存。

    缓存是必须的:每次合成场景都要建好几个字体对象,
    而 truetype 加载字体文件是真正的磁盘 IO。
    """
    key = (size, bold)
    cached = _font_cache.get(key)
    if cached is not None:
        return cached

    path = font_path(bold)
    font: ImageFont.ImageFont
    if path:
        try:
            font = ImageFont.truetype(path, size)
        except OSError:
            font = ImageFont.load_default()
    else:
        # 一个中文字体都没有(极少见)。内置字体只能显示 ASCII,
        # 但至少程序还能跑,而不是直接崩在启动阶段。
        font = ImageFont.load_default()
    _font_cache[key] = font  # type: ignore[assignment]
    return font


def text_width(text: str, font: ImageFont.ImageFont) -> int:
    """量一行字有多宽。

    用 getlength 而不是已经被 Pillow 10 删掉的 getsize ——
    老代码抄过来会直接报 AttributeError。
    """
    try:
        return int(font.getlength(text))
    except AttributeError:                # 极老的 Pillow
        return int(font.getsize(text)[0])  # type: ignore[attr-defined]


def text_height(font: ImageFont.ImageFont) -> int:
    """一行字的行高。用它来排版,比硬编码字号可靠。"""
    try:
        ascent, descent = font.getmetrics()
        return int(ascent + descent)
    except AttributeError:
        return int(getattr(font, "size", 14))


def wrap_text(text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    """把一段文字按像素宽度折行。

    **按像素而不是按字数** —— 中英文宽度差异很大,按字数折会在
    中英混排时折得乱七八糟。另外遇到换行符会强制断行,
    因为用户自己敲的换行是有意义的。
    """
    if max_width <= 0:
        return [text]

    lines: List[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for character in paragraph:
            candidate = current + character
            if current and text_width(candidate, font) > max_width:
                lines.append(current)
                current = character
            else:
                current = candidate
        lines.append(current)
    return lines
