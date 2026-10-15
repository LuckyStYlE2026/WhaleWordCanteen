# -*- coding: utf-8 -*-
"""曲线图和柱状图。**直接用 Canvas 画,不引入 matplotlib。**

为什么不用 matplotlib:它能画出更漂亮的图,但会给这个项目增加 30MB 的
打包体积、一次不短的导入时间,以及一个"用户必须装对版本"的依赖。
而我们要画的只是一条指数衰减曲线和几十根柱子 ——
Canvas 的 create_line / create_rectangle 完全够用,而且跟着窗口自由缩放。

放在单独文件里,是因为曲线页的正文该留给文字,不该被画图的坐标计算淹掉。
"""

import tkinter as tk
from typing import List, Tuple

from .theme import Theme
from .widgets import theme_color

# 画布四周留给坐标轴的边距
PADDING_LEFT = 46
PADDING_RIGHT = 16
PADDING_TOP = 16
PADDING_BOTTOM = 30

CURVE_STEPS = 60          # 曲线采样点数。60 段画出来已经很顺滑了


class ForgettingCurveChart(tk.Canvas):
    """遗忘曲线 R(t) = e^(-t/S)。

    横轴是天数,纵轴是"还记得的概率"。阶梯上的复习点会标出来 ——
    那几个点是"该复习的时候",用户一眼能看出曲线为什么在这些位置被拉回去。
    """

    def __init__(self, master: tk.Misc, theme: Theme, **kwargs) -> None:
        super().__init__(master, bg=theme_color(theme, "panel"),
                         highlightthickness=0, bd=0, **kwargs)
        self.theme = theme
        self._curve: List[Tuple[int, float]] = []
        self._marks: List[int] = []
        self._days = 30
        self.bind("<Configure>", lambda _e: self.redraw())

    def set_data(self, curve: List[Tuple[int, float]], marks: List[int],
                 days: int) -> None:
        self._curve = list(curve)
        self._marks = list(marks)
        self._days = max(1, days)
        self.redraw()

    # ---- 绘制 ------------------------------------------------------------

    def redraw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 1 or height <= 1 or not self._curve:
            return

        left, right = PADDING_LEFT, width - PADDING_RIGHT
        top, bottom = PADDING_TOP, height - PADDING_BOTTOM
        if right <= left or bottom <= top:
            return

        self._draw_grid(left, top, right, bottom)
        self._draw_marks(left, top, right, bottom)
        self._draw_line(left, top, right, bottom)

    def _x(self, day: int, left: int, right: int) -> float:
        return left + (right - left) * day / float(self._days)

    def _y(self, retention: float, top: int, bottom: int) -> float:
        return bottom - (bottom - top) * max(0.0, min(1.0, retention))

    def _draw_grid(self, left: int, top: int, right: int, bottom: int) -> None:
        theme = self.theme
        for ratio in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = self._y(ratio, top, bottom)
            self.create_line(left, y, right, y,
                             fill=theme_color(theme, "panel_light"))
            self.create_text(left - 8, y, anchor="e", text="%d%%" % int(ratio * 100),
                             fill=theme_color(theme, "text_dim"),
                             font=("Microsoft YaHei UI", 8))

        for day in range(0, self._days + 1, max(1, self._days // 6)):
            x = self._x(day, left, right)
            self.create_text(x, bottom + 14, text="%d天" % day,
                             fill=theme_color(theme, "text_dim"),
                             font=("Microsoft YaHei UI", 8))

        self.create_line(left, top, left, bottom,
                         fill=theme_color(theme, "panel_light"))
        self.create_line(left, bottom, right, bottom,
                         fill=theme_color(theme, "panel_light"))

    def _draw_marks(self, left: int, top: int, right: int, bottom: int) -> None:
        """在应该复习的日子画一条竖虚线。"""
        for day in self._marks:
            if day > self._days:
                continue
            x = self._x(day, left, right)
            self.create_line(x, top, x, bottom, dash=(3, 3),
                             fill=theme_color(self.theme, "accent"))

    def _draw_line(self, left: int, top: int, right: int, bottom: int) -> None:
        points: List[float] = []
        for day, retention in self._curve:
            points.extend([self._x(day, left, right),
                           self._y(retention, top, bottom)])
        if len(points) >= 4:
            self.create_line(*points, fill=theme_color(self.theme, "accent"),
                             width=3, smooth=True)


class DueBarChart(tk.Canvas):
    """未来每天的到期词数。回答"接下来几天我每天要背多少"。"""

    def __init__(self, master: tk.Misc, theme: Theme, **kwargs) -> None:
        super().__init__(master, bg=theme_color(theme, "panel"),
                         highlightthickness=0, bd=0, **kwargs)
        self.theme = theme
        self._data: List[Tuple[int, int]] = []
        self.bind("<Configure>", lambda _e: self.redraw())

    def set_data(self, data: List[Tuple[int, int]]) -> None:
        self._data = list(data)
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 1 or height <= 1 or not self._data:
            return

        left, right = PADDING_LEFT, width - PADDING_RIGHT
        top, bottom = PADDING_TOP, height - PADDING_BOTTOM
        if right <= left or bottom <= top:
            return

        peak = max([count for _day, count in self._data] + [1])
        slot = (right - left) / float(len(self._data))
        bar_width = max(2, int(slot * 0.6))

        self.create_line(left, bottom, right, bottom,
                         fill=theme_color(self.theme, "panel_light"))
        self.create_text(left - 8, top, anchor="e", text=str(peak),
                         fill=theme_color(self.theme, "text_dim"),
                         font=("Microsoft YaHei UI", 8))

        for index, (day, count) in enumerate(self._data):
            if count <= 0:
                continue
            x = left + slot * (index + 0.5)
            bar_height = (bottom - top) * count / float(peak)
            self.create_rectangle(x - bar_width / 2, bottom - bar_height,
                                  x + bar_width / 2, bottom,
                                  fill=theme_color(self.theme, "accent"), width=0)
            if count >= max(1, peak // 4):
                self.create_text(x, bottom - bar_height - 8, text=str(count),
                                 fill=theme_color(self.theme, "text"),
                                 font=("Microsoft YaHei UI", 8))

        for index, (day, _count) in enumerate(self._data):
            if day % 5:
                continue
            x = left + slot * (index + 0.5)
            self.create_text(x, bottom + 14, text="+%d" % day,
                             fill=theme_color(self.theme, "text_dim"),
                             font=("Microsoft YaHei UI", 8))
