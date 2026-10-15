# -*- coding: utf-8 -*-
"""Galgame 场景画布:把合成好的图贴上来,再把真控件叠上去。

单独成模块,是因为它同时管三件互相牵连的事,而三件事都和"画布"有关:

1. **绘制**:用 ui/scene.py 把背景、立绘、底板、对话框合成成**一张**图
   (为什么必须是一张,见 scene.py 开头);
2. **窗口尺寸变化后重画**:拖动窗口时会连续触发 <Configure>,
   每一帧都重新合成会卡得没法用,所以要等手停下来(防抖);
3. **点击老师**:对话页的入口就挂在这里 —— 点立绘打开对话,
   所以"老师站在哪"这件事必须和画图用同一处计算。

放在 widgets.py 里的时候这个类占了这个文件一半还多,而那边其它的东西
(按钮、卡片、配色适配)其实是另一回事。
"""

import tkinter as tk
from typing import Optional, Tuple

from . import scene as scene_module
from .theme import Theme

# 窗口尺寸变化后等多久再重新合成。见上面第 2 条。
RESIZE_DEBOUNCE_MS = 120


class GalScene(tk.Canvas):
    """背景 + 立绘 + 对话框的场景画布。

    内容是**一张离屏合成好的图**,整张贴上来。要交互的控件由调用方用
    create_window 自己叠上去 —— 为什么不画进图里,见 ui/scene.py 开头。

    立绘大小、立绘位置、底板与对话框的透明度来自设置(见 core/config.py)。
    取不到设置时一律退回默认值 —— 这个控件在测试里也会被直接构造,
    不该要求调用方一定先造好一个完整的 App。

    几个可选参数是给**对话页**用的:那一页要让老师站到窗口中间、
    并且点在自己身上不该再打开一个对话页,所以允许覆盖锚点、大小和点击回调。
    """

    def __init__(self, master: tk.Misc, app, theme: Theme,
                 background: Optional[str] = None,
                 character: Optional[str] = None,
                 frame_box: Optional[Tuple[float, float, float, float]] = None,
                 on_character_click=None,
                 character_anchor: Optional[Tuple[float, float]] = None,
                 character_scale: Optional[float] = None,
                 character_centred: Optional[bool] = None,
                 character_centre_x: Optional[bool] = None,
                 options: Optional[dict] = None,
                 **kwargs) -> None:
        super().__init__(master, bg=_hex(theme.background),
                         highlightthickness=0, bd=0, **kwargs)
        self.theme = theme
        self.background = background
        # character 是"这一次画不画老师"(空串 = 不画),而 _character_path
        # 记着"老师是谁" —— 学习页「隐藏老师」只是不画,不是把形象丢掉,
        # 再点「显示老师」要能原样回来。
        self.character = character
        self._character_path = character
        self.dialogue: Optional[scene_module.Dialogue] = None
        self.on_character_click = on_character_click

        render_options = dict(options or {})
        if character_anchor is not None:
            render_options["character_anchor_x"] = character_anchor[0]
            render_options["character_anchor_y"] = character_anchor[1]
        if character_scale is not None:
            render_options["character_scale"] = character_scale
        if character_centred is not None:
            render_options["character_centred"] = character_centred
        if character_centre_x is not None:
            render_options["character_centre_x"] = character_centre_x
        self.renderer = scene_module.SceneRenderer(theme, frame_box=frame_box,
                                                   **render_options)

        self._image_id: Optional[int] = None
        self._last_size: Tuple[int, int] = (0, 0)
        self._pending_resize = None
        self._cursor = ""

        self.bind("<Configure>", self._on_configure)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Motion>", self._on_motion)

    # ---- 内容 ------------------------------------------------------------

    def set_character(self, character: Optional[str]) -> None:
        """换立绘。穿在对话框底下的那种换法(换情绪表情)。"""
        self._character_path = character
        self.character = character
        self.redraw()

    def hide_character(self) -> None:
        """把立绘从画面上拿掉(学习页的「隐藏老师」用)。

        只清"这次画不画",**记着老师是谁**(见 __init__ 里的说明)——
        否则「显示老师」就没东西可恢复了,用户会觉得形象被自己弄丢了。
        """
        self.character = ""
        self.redraw()

    def show_character(self) -> None:
        """把立绘摆回来(隐藏之后)。形象还是隐藏前那个。"""
        self.character = self._character_path or ""
        self.redraw()

    def set_frame_box(self, box) -> None:
        """改内容底板的位置。

        学习页的「隐藏老师」要把单词表铺满全屏,于是图里那块底板也得跟着变 ——
        面板和底板读的是同一个 box(见 ui/layout.py 的 box_rect),
        只改一边就会错位:板还在左半边,而控件已经铺满全屏。
        """
        if box != self.renderer.frame_box:
            self.renderer.frame_box = box
            self.redraw()

    def set_dialogue(self, dialogue: Optional[scene_module.Dialogue]) -> None:
        """设置/清除对话框。传 None = 这一页不要对话框(主菜单就是这样)。

        "没有人在说话"和"有人在说一句空话"是两回事:后者仍然会画出一个
        空的框,而主菜单上不该有框。
        """
        self.dialogue = dialogue
        self.redraw()

    # ---- 点击老师(打开对话页) ------------------------------------------

    def character_hit(self, x: int, y: int) -> bool:
        """这个坐标算不算点在老师身上。

        判据是**渲染时立绘占的那个矩形**(由 scene_layers 算,和画图用的是
        同一处),不是"这块像素透不透明" —— 后者要读像素,还要在每次鼠标
        移动时采样。误差只出现在立绘的透明边角上,可以接受。

        落在对话框范围内的点不算:那里是真控件(输入框、按钮)的地盘。
        """
        if not self.character or self.on_character_click is None:
            return False
        if self._inside_dialog(x, y):
            return False
        return self.renderer.characters.hit(self.canvas_size(), self.character, x, y)

    def canvas_size(self) -> Tuple[int, int]:
        """当前画布尺寸。还没布局好时拿窗口尺寸兜底,免得按 1×1 算。"""
        width, height = self.winfo_width(), self.winfo_height()
        if width > 1 and height > 1:
            return width, height
        top = self.winfo_toplevel()
        return max(320, top.winfo_width()), max(240, top.winfo_height())

    def _inside_dialog(self, x: int, y: int) -> bool:
        left, top, right, bottom = scene_module.dialog_rect(self.canvas_size())
        return left <= x <= right and top <= y <= bottom

    def _on_click(self, event) -> None:
        if self.character_hit(event.x, event.y):
            self.on_character_click()

    def _on_motion(self, event) -> None:
        """鼠标移到老师身上时换成小手。

        这条是**可发现性**的全部依靠:没有它,没人知道老师是可以点的。
        """
        wanted = "hand2" if self.character_hit(event.x, event.y) else ""
        if wanted != self._cursor:
            self._cursor = wanted
            try:
                self.configure(cursor=wanted)
            except tk.TclError:
                pass

    # ---- 绘制 ------------------------------------------------------------

    def _on_configure(self, event) -> None:
        """窗口尺寸变了。等手停下来再重画。"""
        if (event.width, event.height) == self._last_size:
            return
        if self._pending_resize is not None:
            self.after_cancel(self._pending_resize)
        self._pending_resize = self.after(RESIZE_DEBOUNCE_MS, self.redraw)

    def destroy(self) -> None:
        """销毁前把还没到期的防抖回调撤掉。

        不撤的话,切页 / 关窗时那个 `after` 还会在 120ms 后触发,
        而那时控件已经没了 —— Tk 会往 stderr 打
        `invalid command name "...redraw"`,看起来像程序出错。
        这类噪音在测试输出里尤其碍事:真正的失败会被它淹没。
        """
        if self._pending_resize is not None:
            try:
                self.after_cancel(self._pending_resize)
            except tk.TclError:
                pass                      # 解释器已经在拆了,撤不掉也无所谓
            self._pending_resize = None
        super().destroy()

    def redraw(self) -> None:
        self._pending_resize = None
        width = self.winfo_width()
        height = self.winfo_height()
        # 控件还没被布局时 winfo_* 返回 1,拿它合成会得到一张 1×1 的图
        if width <= 1 or height <= 1:
            return
        self._last_size = (width, height)

        if self.dialogue is not None:
            image = self.renderer.compose((width, height), self.dialogue)
        else:
            image = self.renderer.compose_backdrop((width, height), self.background,
                                                   self.character)

        # 必须经过 theme.to_photo 保持强引用,否则图片会被垃圾回收,
        # 界面上留下一片空白而且不报错
        from .theme import to_photo
        # master=self:图片必须挂在**本控件所在的** Tk 解释器上,
        # 否则 configure 时只会得到一句"image pyimageN doesn't exist"
        photo = to_photo(image, "scene:%s" % id(self), master=self)

        if self._image_id is None:
            self._image_id = self.create_image(0, 0, image=photo, anchor="nw")
        else:
            self.itemconfigure(self._image_id, image=photo)
        self.tag_lower(self._image_id)

    # ---- 叠控件 ----------------------------------------------------------

    def dialog_area(self) -> Tuple[int, int, int, int]:
        """当前对话框占据的矩形,供调用方把输入框放进去。"""
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        return scene_module.dialog_rect((width, height))


def _hex(color) -> str:
    """(r,g,b) → "#rrggbb"。Tk 不认 RGB 元组,只认十六进制字符串。"""
    return "#%02x%02x%02x" % (color[0], color[1], color[2])
