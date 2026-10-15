# -*- coding: utf-8 -*-
"""窗口与任务栏的图标。

## 为什么要单独一个模块

和 ui/imagery.py 是同一个理由:**"文件到底在不在"是用户素材决定的事实**,
只有界面层该操心:

* core 层只算路径、不碰磁盘(见 core/paths.resource_root 的说明)。
* 图标是**可选**的 —— 用户把 icon.ico 删了,程序该照常启动、只是回到
  默认图标,而不是报错。这个判断需要一个地方统一兜住。

## 图标放哪

    game/icon.ico          (开发时)
    <exe 同级的 _internal 或 _MEIPASS>/icon.ico   (打包后)

两种都由 `resource_root()` 算出来 —— 打包后它就是 PyInstaller 的
_MEIPASS,开发时就是 `game/`。所以这里只写相对名字。

## 为什么不用担心"图标是坏文件"

`iconbitmap` 遇到非 ICO 内容会抛 TclError。**而这个项目真的踩过一次**:
一个 .png 被改了后缀名当 .ico 用,看着毫无异常,只有设图标时才炸。
所以下面把异常全兜住了 —— 图标设置失败绝不该让程序起不来。
"""

import tkinter as tk
from typing import Optional

from core.paths import resource_root

# 图标的候选文件名。第一个存在的就用它。
#
# 支持多个名字是因为"图标该叫什么"没有公认答案:有人叫 app.ico、
# 有人叫 logo.ico。要求用户必须叫某个特定名字,是那种"文档里写了
# 但没人看"的规矩(和 ui/imagery 里背景图的候选名单同一个理由)。
ICON_NAMES = ("icon.ico", "app.ico", "logo.ico")


def icon_path() -> Optional[str]:
    """找一个能用的图标文件,返回绝对路径字符串;都没有就返回 None。

    返回 **str 而不是 Path**:`iconbitmap` 要的是字符串,Tk 对 Path
    在旧版本上会报类型错。
    """
    root = resource_root()
    for name in ICON_NAMES:
        candidate = root / name
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None


def apply_icon(window: tk.Misc) -> bool:
    """给窗口设上图标,返回有没有设成功。

    **永不抛异常。** 图标是装饰,装饰失败不该拦着一个背单词的程序启动。
    """
    path = icon_path()
    if not path:
        return False
    try:
        window.iconbitmap(path)
        return True
    except Exception:
        # 文件坏了(比如把 .png 改名成 .ico)、Tk 版本不支持、路径含
        # 特殊字符…… 全都归到"没设上",继续跑。
        return False
