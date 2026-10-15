# -*- coding: utf-8 -*-
"""Galgame 场景合成器。**纯 Pillow,不认识 Tkinter。**

为什么要离屏合成整张场景,而不是在 Canvas 上叠几个图片项?

因为 **Tkinter 的 Canvas 做不了逐像素的 alpha 合成**,只支持二值透明。
立绘是带羽化边缘的 PNG,直接 create_image 叠到背景上会带出一圈黑框。
而半透明的圆角对话框更是完全做不到 —— Canvas 没有 alpha 混合。

所以这里的做法是:在 Pillow 里把背景 → 立绘 → 内容底板 → 对话框 → 文字
一层层 alpha_composite 好,**合成一张最终的图**,再整张贴到 Canvas 上。
只有一张图,自然没有接缝。

反过来也带来一个好处:这个文件完全不需要 Tk 就能测 ——
给定尺寸和内容,它产出一张 PIL 图,单元测试里直接断言像素即可。

需要交互的控件(输入框、按钮)**不进这张图**,而是事后用
canvas.create_window 叠上去。这样中文输入法才能正常工作 ——
画在图片上的字是不能用输入法输入的。

三个"不在这个文件里"的东西,都是有意的:

* **每层长什么样** → ui/scene_layers.py(这里是流程,那里是画法)
* **东西摆在哪** → ui/layout.py(界面层要用同一套坐标摆输入框)
* **颜色怎么算** → ui/theme.py 的 blend_over(界面层也要用同一个口径)
"""

from dataclasses import dataclass
from typing import Optional, Tuple

from PIL import Image

from .layout import (
    CHARACTER_ANCHOR_X_DEFAULT,
    CHARACTER_ANCHOR_Y_DEFAULT,
    PANEL_OPACITY,
    dialog_rect,          # 再导出:调用方一直是从 scene 拿这个函数的
)
from .scene_layers import LayerPainter, gradient, scaled
from .theme import DEFAULT_THEME, Theme, blend_over, readable_text_color

# 这几个名字是 scene_layers 的实现细节,但历史上调用方/测试是从 scene 拿的
# (比如 _scaled)。留成再导出,免得为了改个 import 去动一堆地方。
_scaled = scaled


@dataclass
class Dialogue:
    """一次对话的内容。"""

    speaker: str = ""            # 说话人名字。空串表示旁白
    text: str = ""               # 说的话
    character: Optional[str] = None   # 立绘路径(相对 assets/)
    background: Optional[str] = None  # 背景路径

    # 对话框里最多显示几行,超出就截断。默认按布局算出来的值不够时,
    # 调用方可以直接指定。
    max_lines: int = 0


class SceneRenderer:
    """把一次对话要的画面合成成一张图。

    做成类而不是函数,是为了让主题(以及立绘大小、底板图、各处透明度)
    能挂住,调用方不必每次传一遍。
    """

    def __init__(self, theme: Optional[Theme] = None,
                 dialog_opacity: float = 1.0,
                 frame_opacity: float = PANEL_OPACITY,
                 character_scale: float = 1.0,
                 character_anchor_x: float = CHARACTER_ANCHOR_X_DEFAULT,
                 character_anchor_y: float = CHARACTER_ANCHOR_Y_DEFAULT,
                 character_centred: bool = False,
                 character_centre_x: bool = False,
                 panel_image: Optional[str] = None,
                 frame_box: Optional[Tuple[float, float, float, float]] = None) -> None:
        self.theme = theme or DEFAULT_THEME
        # 内容底板的位置。None = 这一页没有内容区(记忆曲线、设置…),
        # 那时候整张背景都是可见的,不需要再压一层。
        self.frame_box = frame_box
        self.painter = LayerPainter(
            self.theme, dialog_opacity=dialog_opacity, panel_opacity=frame_opacity,
            character_scale=character_scale, character_anchor_x=character_anchor_x,
            character_anchor_y=character_anchor_y, character_centred=character_centred,
            character_centre_x=character_centre_x,
            panel_image=panel_image)

    # ---- 读设置(保持老名字,已有调用方/测试按这些名字读) ------------------

    @property
    def dialog_opacity(self) -> float:
        return self.painter.dialog_opacity

    @property
    def panel_opacity(self) -> float:
        return self.painter.panel_opacity

    @property
    def frame_opacity(self) -> float:
        """旧名字,保留给已有调用方读(内部一律用 panel_opacity)。"""
        return self.painter.panel_opacity

    @property
    def panel_image(self) -> str:
        return self.painter.panel_image

    @property
    def character_scale(self) -> float:
        return self.painter.character_scale

    @property
    def characters(self):
        """立绘的位置与命中测试(ui/character.py 的 CharacterPlacer)。"""
        return self.painter.characters

    # ---- 对外入口 --------------------------------------------------------

    def compose(self, size: Tuple[int, int], dialogue: Dialogue) -> Image.Image:
        """合成"背景 + 立绘 + 内容底板 + 对话框 + 文字"。"""
        size = (max(320, size[0]), max(240, size[1]))
        canvas = self._backdrop(size, dialogue.background)
        if dialogue.character:
            canvas = self.painter.character(canvas, dialogue.character)
        if self.frame_box is not None:
            canvas = self.painter.panel(canvas, self.frame_box)
        return self.painter.dialog(canvas, dialogue.speaker, dialogue.text,
                                   dialogue.max_lines)

    def compose_backdrop(self, size: Tuple[int, int],
                         background: Optional[str] = None,
                         character: Optional[str] = None) -> Image.Image:
        """只画背景(和可选的立绘、内容底板),不画对话框。

        给不需要对话框的板块用(主菜单、设置、记忆曲线…)。
        它们的内容是真实的 Tk 控件,压在背景上;背景只是氛围。

        主菜单要立绘但不要对话框,所以立绘放在这里而不是 compose() 里 ——
        "有没有人站着"和"有没有人在说话"是两件独立的事。
        内容底板也走这里:哪些页面有内容区是**页面**决定的(frame_box 是
        构造时给的),和"要不要对话框"无关。
        """
        size = (max(320, size[0]), max(240, size[1]))
        canvas = self._backdrop(size, background)
        if character:
            canvas = self.painter.character(canvas, character)
        if self.frame_box is not None:
            canvas = self.painter.panel(canvas, self.frame_box)
        return canvas

    def _backdrop(self, size: Tuple[int, int], background: Optional[str]) -> Image.Image:
        return self.painter.backdrop(size, background)


# --------------------------------------------------------------------------
# 给界面层用的两个工具
# --------------------------------------------------------------------------
#
# 界面层的控件底色只能是纯色,而底板是画在图里的 —— 它得先问"那块底
# 看起来是什么颜色"。口径只有一处(theme.blend_over),这里只是转发,
# 让调用方不必同时 import 三个模块。

__all__ = ["Dialogue", "SceneRenderer", "blend_over", "gradient",
           "readable_text_color", "dialog_rect"]
