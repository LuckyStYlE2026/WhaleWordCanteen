# -*- coding: utf-8 -*-
"""窗口尺寸与全屏。

**为什么从 ui/app.py 拆出来。** 这几件事和"板块路由、共享状态"没有关系,
它们只认设置里的分辨率与全屏开关;而 app.py 是全局状态的持有者,
不该再塞进"窗口怎么摆、怎么居中、F11 怎么绑"这些细节。

一条容易踩的规矩写在这里,免得以后有人顺手改坏:

> **Esc 不能在这里绑。** Esc 要先问当前板块要不要自己处理
> (学习页用它"返回"),所以它的绑定和分发都在 App 里 ——
> Tk 的按键顺着焦点控件的 bindtags 冒泡,页(Frame)不在那条链上,
> 在页上绑是无效的,而在顶层再绑一次会把 App 那条**替换**掉,
> 从此再也退不出全屏。
"""

import tkinter as tk
from typing import Tuple

# 窗口允许缩到多小。
#
# **为什么需要这个。** 每一页的内容都是"按比例摆"的,但有**下限**:
# 主菜单固定要放五张卡片 + 标题 + 进度行 + 退出按钮,窗口一矮,
# pack 分配空间时最后声明的那个就被压扁 —— 用户实际看到的是
# 「退出」只剩半截字、而且点不着。与其让每一页都去处理"空间不够怎么缩",
# 不如在这里守住一个下限:内容放得下,页面代码也不必到处判尺寸。
#
# **这两个数是量出来的,不是拍的。** 主菜单那一块的高度是窗口的 0.90、
# 上边距 0.04,所以窗口高 H 时内容框只有 0.90H;而内容自然需要 633px
# (五张卡片 + 标题 + 进度 + 退出按钮)。解 0.90H ≥ 633 得 H ≥ 704。
# 宽度取 960:再窄的话卡片里的副标题会开始折行,读起来难看。
MIN_WINDOW_WIDTH = 960
MIN_WINDOW_HEIGHT = 704


def screen_geometry(root: tk.Misc, size: Tuple[int, int]) -> str:
    """把窗口摆在屏幕中间偏上的 "WxH+X+Y" 字符串。

    直接摆到 (0,0) 会顶住屏幕左上角,看起来像还没加载完;
    垂直方向取 1/3 而不是 1/2 —— 人眼习惯标题在上面一点。
    """
    width, height = size
    x = max(0, (root.winfo_screenwidth() - width) // 2)
    y = max(0, (root.winfo_screenheight() - height) // 3)
    return "%dx%d+%d+%d" % (width, height, x, y)


def apply_window(root: tk.Tk, width: int, height: int, fullscreen: bool) -> None:
    """把分辨率和全屏开关用上。

    设置页点保存时也调它 —— 用户改了分辨率却看不出变化,
    是最容易引起怀疑的一种反馈。
    """
    root.minsize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    root.attributes("-fullscreen", bool(fullscreen))
    root.geometry("%dx%d" % (width, height))


def bind_fullscreen_toggle(root: tk.Tk, command) -> None:
    """F11 切换全屏。

    只绑这一个键。Esc 由 App 分发(见模块开头),刻意不在全屏切换里管它。
    """
    root.bind("<F11>", command)
