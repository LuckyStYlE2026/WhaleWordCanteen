# -*- coding: utf-8 -*-
"""立绘:摆在哪、点到没有。**纯 Pillow + 纯算术,不认识 Tkinter。**

和 ui/scene_layers.py 的分工:那边是"四层怎么画",这边是**关于立绘的
两个问题** ——

1. 它这次占画布上的哪一块(画图和命中测试都要用同一个答案);
2. 点到画面上某一点,算不算点在它身上。

第 2 条是"点老师打开对话页"的判定依据,而它的正确答案比看上去麻烦:
立绘是带透明边的 PNG,**贴图占的那块画布**和**看得见的那个人**不是一回事。
拿前者做命中测试的话,在人物头顶上方几十像素的空白处点一下也会打开
对话页 —— 用户看到的是"我明明点的是空气"。
"""

from typing import Tuple

from PIL import Image

from .layout import CharacterLayout, character_rect, dialog_rect
from .theme import Theme, load_image


class CharacterPlacer:
    """按住一套立绘观感参数(大小/落点),回答上面那两个问题。

    参数来自设置或调用方(对话页要老师站到正中),这里不自己去读设置 ——
    那样它就没法脱离 App 单独测了。
    """

    def __init__(self, theme: Theme, scale: float = 1.0,
                 anchor_x: float = 0.995, anchor_y: float = 0.67,
                 centred: bool = False, centre_x: bool = False) -> None:
        self.theme = theme
        self.scale = scale
        self.anchor_x = anchor_x
        self.anchor_y = anchor_y
        self.centred = centred
        # 只横向居中(纵向仍是底边贴 anchor_y)。对话页要的就是这个。
        self.centre_x = centre_x

    def box(self, size: Tuple[int, int], path: str) -> CharacterLayout:
        """立绘这次占的矩形。画图和命中测试用的是它 —— 同一个口径。"""
        return character_rect(size, aspect=self.aspect(path), scale=self.scale,
                              anchor_x=self.anchor_x, anchor_y=self.anchor_y,
                              centred=self.centred, centre_x=self.centre_x)

    def aspect(self, path: str) -> float:
        """立绘的长宽比。读不到图时占位框的比例,不抛异常。"""
        natural = load_image(path, None, self.theme)
        return natural.width / float(max(1, natural.height))

    def visible_box(self, size: Tuple[int, int], path: str) -> CharacterLayout:
        """**看得见的那一部分**立绘占的矩形 —— 判断点击命中的就是它。

        做法是把立绘按实际显示尺寸缩放一次,读它的 alpha 边界。
        比"每次鼠标移动都去采样像素"便宜得多,而且两种做法都要做一次
        缩放/采样 —— 那不如选准的那一个。
        """
        box = self.box(size, path)
        sprite = load_image(path, (box.width, box.height), self.theme).convert("RGBA")
        bounds = sprite.getchannel("A").getbbox()
        if bounds is None:                    # 整张全透明:退回贴图占的框
            return box
        left = box.left + bounds[0]
        top = box.top + bounds[1]
        width = max(1, bounds[2] - bounds[0])
        height = max(1, bounds[3] - bounds[1])
        _left, dialog_top, _right, _bottom = dialog_rect(size)
        visible_bottom = min(top + height, max(240, size[1]))
        return CharacterLayout(
            width=width, height=height, left=left, top=top,
            free_height=max(0, dialog_top - top),
            covered=max(0, visible_bottom - dialog_top))

    def hit(self, size: Tuple[int, int], path: str, x: int, y: int) -> bool:
        """这个坐标算不算点在老师身上。

        **落在对话框范围内的点不算** —— 那里是真控件(输入框、按钮)的地盘,
        点它们不该顺带打开对话页。这一条由调用方决定要不要用(对话框里
        本来就点不到画布),所以放在这里当一个纯判断,不影响画图。
        """
        box = self.visible_box(size, path)
        inside = box.left <= x <= box.right and box.top <= y <= box.bottom
        if not inside:
            return False
        left, top, right, bottom = dialog_rect(size)
        return not (left <= x <= right and top <= y <= bottom)


def average_color(image: Image.Image, fallback: Tuple[int, int, int]) -> \
        Tuple[int, int, int]:
    """一张图的平均色(用于算底板底色)。读不动就返回 fallback。

    只缩到 1×1 取平均,不按底板的实际比例裁剪 —— 底板是"等比缩放后居中"
    贴的,留白处露的是底色,精确算要按比例裁一块再平均。但那点差别在
    "选深色字还是浅色字"这件事上完全看不出来。
    """
    try:
        small = image.convert("RGBA").resize((1, 1), Image.BOX)
        red, green, blue, alpha = small.getpixel((0, 0))
    except Exception:                        # noqa: BLE001 —— 坏图不该带崩配色
        return fallback
    ratio = alpha / 255.0
    return tuple(
        int(round(channel * ratio + base * (1.0 - ratio)))
        for channel, base in zip((red, green, blue), fallback)
    )
