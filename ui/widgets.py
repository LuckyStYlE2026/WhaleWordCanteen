# -*- coding: utf-8 -*-
"""可复用的界面零件:按钮、卡片。

这里的东西都**不认识 core**,只认识 tkinter 和 theme ——
它们不知道什么是单词、什么是记忆曲线。要显示数据的地方,
由 views/ 里的界面把数据整理成字符串再传进来。

分家说明(都是为了让每个文件只讲一件事):
  · 场景画布 GalScene → ui/gal_scene.py
  · 底板配色(控件该用什么底色和字色) → ui/surface.py
  · 装东西的容器(可滚动区域、对话记录) → ui/panels.py
这里只留摆在页面上的小零件:按钮、卡片,以及把设置翻成控件颜色的适配。
"""

import tkinter as tk
from typing import Callable, Tuple

from core.config import UiSettings

from . import surface
from .theme import Theme, load_image

# 窗口尺寸变化后等多久再重新合成。拖动窗口边框时会连续触发 <Configure>,
# 每一帧都重新合成场景会卡得没法用;等手停下来再画一次就够了。
RESIZE_DEBOUNCE_MS = 120

# --------------------------------------------------------------------------
# 按钮
# --------------------------------------------------------------------------

def primary_button(parent: tk.Misc, text: str, command: Callable[[], None],
                   theme: Theme, **kwargs) -> tk.Button:
    """强调色实心按钮。一屏里最多一两个,用来表示"主要动作"。

    Tk 的按钮在 Windows 上默认是灰色方块,除非显式关掉浮雕和边框。
    这几个参数看起来啰嗦,但少了任何一个都会露出原生的立体边框,
    跟深色背景放在一起很扎眼。
    """
    return tk.Button(
        parent, text=text, command=command,
        bg=_hex(theme.accent), fg=_hex(theme.accent_text),
        activebackground=_hex(theme.panel_light), activeforeground=_hex(theme.text),
        relief="flat", bd=0, highlightthickness=0,
        font=("Microsoft YaHei UI", 12, "bold"), cursor="hand2",
        padx=18, pady=8, **kwargs)


def ghost_button(parent: tk.Misc, text: str, command: Callable[[], None],
                 theme: Theme, **kwargs) -> tk.Button:
    """线框按钮。次要动作都用它,让位给主按钮。"""
    return tk.Button(
        parent, text=text, command=command,
        bg=_hex(theme.panel), fg=_hex(theme.text),
        activebackground=_hex(theme.panel_light), activeforeground=_hex(theme.text),
        relief="flat", bd=0, highlightthickness=1,
        highlightbackground=_hex(theme.panel_light),
        font=("Microsoft YaHei UI", 11), cursor="hand2",
        padx=14, pady=6, **kwargs)


def _hex(color: Tuple[int, ...]) -> str:
    """(r,g,b) → "#rrggbb"。Tk 不认 RGB 元组,只认十六进制字符串。"""
    return "#%02x%02x%02x" % (color[0], color[1], color[2])


def theme_color(theme: Theme, field: str) -> str:
    """取主题里的一个颜色并转成 Tk 认的写法。"""
    return _hex(theme.to_tuple(field))


def scene_options(app) -> dict:
    """把设置里的场景观感(立绘大小/位置、底板与对话框透明度、底板图)翻成渲染参数。

    单独拎出来,是因为它有两个调用方:场景画布自己(ui/widgets.py),
    以及"设置一改就立刻重画"的那条路。两处各写一遍迟早会漏掉一个字段,
    表现为"设置里改了但界面没变"。

    app 为 None 或没有 settings 时退回默认值 —— 这个函数会在
    构造界面的早期被调用,那时候设置可能还没读进来。
    """
    ui = getattr(getattr(app, "settings", None), "ui", None)
    fallback = UiSettings()
    if ui is None:
        ui = fallback
    return {
        "dialog_opacity": _number(ui.dialog_opacity, fallback.dialog_opacity),
        "frame_opacity": _number(ui.panel_opacity, fallback.panel_opacity),
        "panel_image": str(getattr(ui, "panel_image", "") or ""),
        "character_scale": _number(ui.character_scale, fallback.character_scale),
        "character_anchor_x": _number(ui.character_anchor_x, fallback.character_anchor_x),
        "character_anchor_y": _number(ui.character_anchor_y, fallback.character_anchor_y),
        "character_centred": bool(getattr(ui, "character_centred", False)),
        "character_centre_x": bool(getattr(ui, "character_centre_x", False)),
    }


def _number(value, fallback: float) -> float:
    """读一个数值设置,读不到就用默认值。

    设置文件是纯文本,用户可以手工改;一个写错的字符串不该让
    整个场景合成崩掉(那时界面会变成一片黑,而原因在别处)。
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


# --------------------------------------------------------------------------
# 底板配色:让真实控件"藏进"画在图里的那块底
# --------------------------------------------------------------------------
#
# 颜色怎么算是 ui/surface.py 的事(纯算术,不认识 Tk 也不认识 Pillow)。
# 这里只做两件事:把"当前设置"翻译成它的入参,再把结果转成 Tk 认的写法。

def panel_palette(app) -> dict:
    """底板上的整套颜色,已经转成 Tk 写法。

    一次给全,是因为"用深色字还是浅色字"必须**整块一起决定** ——
    正文选了深色而次要文字还是浅灰,那块底上就会有一行看不见的字。

    控件拿到的是 "#rrggbb" 字符串:让每个调用方自己转一遍,
    迟早会有一个人忘了转,然后在 Tk 那里收到一个看不懂的报错。
    """
    colors = surface.panel_palette(_theme(app), panel_image(app))
    return {name: _hex(value) for name, value in colors.items()}


def panel_tint(app) -> str:
    """底板底色的 Tk 写法("#rrggbb")。"""
    return panel_palette(app)["surface"]


def panel_text_dim(app) -> str:
    """底板上的次要文字色(按同一块底色算过对比度)。"""
    return panel_palette(app)["dim"]


def panel_image(app):
    """用户选的底板图(已经读进来的 PIL 图),没选就是 None。

    读不到就当没选 —— 底板退回主题底色,而不是弹一个错。
    """
    ui = getattr(getattr(app, "settings", None), "ui", None)
    name = str(getattr(ui, "panel_image", "") or "")
    if not name:
        return None
    try:
        return load_image(name, None, _theme(app))
    except Exception:                        # noqa: BLE001 —— 坏图退回底色
        return None


def _theme(app):
    from .theme import DEFAULT_THEME
    return getattr(app, "theme", None) or DEFAULT_THEME


# --------------------------------------------------------------------------
# 卡片
# --------------------------------------------------------------------------

class Card(tk.Frame):
    """主菜单上的一个可点卡片:标题 + 一行说明。

    做成 Frame 而不是 Button,是因为要显示两行不同字号的文字,
    Tk 的按钮只能放一种字体。代价是要自己处理悬停和点击。
    """

    def __init__(self, master: tk.Misc, theme: Theme, title: str,
                 subtitle: str, command: Callable[[], None], **kwargs) -> None:
        super().__init__(master, bg=_hex(theme.panel), highlightthickness=1,
                         highlightbackground=_hex(theme.panel_light), **kwargs)
        self.theme = theme
        self.command = command

        self.title_label = tk.Label(
            self, text=title, bg=_hex(theme.panel), fg=_hex(theme.text),
            font=("Microsoft YaHei UI", 15, "bold"), anchor="w")
        self.title_label.pack(fill="x", padx=16, pady=(12, 2))

        self.subtitle_label = tk.Label(
            self, text=subtitle, bg=_hex(theme.panel), fg=_hex(theme.text_dim),
            font=("Microsoft YaHei UI", 10), anchor="w", justify="left",
            wraplength=280)
        self.subtitle_label.pack(fill="x", padx=16, pady=(0, 12))

        # 卡片里的每个零件都要绑事件 —— 点在标题文字上和在空白处
        # 应该是同一件事,否则用户会觉得卡片"点不动"
        for widget in (self, self.title_label, self.subtitle_label):
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
            widget.bind("<Button-1>", self._on_click)
            widget.configure(cursor="hand2")

    def _paint(self, background: str) -> None:
        for widget in (self, self.title_label, self.subtitle_label):
            widget.configure(bg=background)

    def _on_enter(self, _event=None) -> None:
        self._paint(_hex(self.theme.panel_light))

    def _on_leave(self, _event=None) -> None:
        self._paint(_hex(self.theme.panel))

    def _on_click(self, _event=None) -> None:
        self.command()
