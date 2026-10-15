# -*- coding: utf-8 -*-
"""场景的各个图层怎么画。**纯 Pillow,不认识 Tkinter。**

为什么单独一个文件:ui/scene.py 讲的是"整张场景怎么合成、为什么非要在
Pillow 里离屏合成",而这个文件讲的是每一层具体长什么样 ——
背景、立绘、内容底板、对话框,四层四种画法。两者都是"画图",
但一个是流程、一个是画法;混在一起之后 scene.py 会涨到四百行,
改对话框的圆角要翻过立绘的缩放代码。

坐标一律从 ui/layout.py 拿 —— 那里是"东西摆在哪"的唯一出处。
"""

from typing import Optional, Tuple

from PIL import Image, ImageDraw

from .character import CharacterPlacer
from .layout import (
    BORDER_OPACITY,
    DIALOG_PANEL_OPACITY,
    DIALOG_PADDING,
    DIALOG_RADIUS,
    LINE_SPACING,
    NAME_PLATE_HEIGHT,
    NAME_PLATE_OPACITY,
    SHADOW_OPACITY,
    box_rect,
    dialog_rect,
)
from .theme import (Theme, get_font, load_image, resolve_image_path,
                    text_height, text_width, wrap_text)

# 内容底板没选图片时铺的颜色。它是"背景图"和"控件"之间那一层,
# 默认跟主题背景同色 —— 深色主题下就是一块深蓝灰的板,和 v1.5 之前
# 的观感一致,只是现在**能换成图片、也能调透明度**。
PANEL_FILL_FALLBACK = (18, 22, 38)


def scaled(color: Tuple[int, ...], opacity: float) -> Tuple[int, int, int, int]:
    """把一个颜色按不透明度系数变成 RGBA。

    颜色本身已经带了 alpha(主题里 dialog_fill 是 225),这里再乘一层 ——
    用户调的是"对话框有多透",不该要求他也去改主题文件里的数字。
    """
    base = color[3] if len(color) > 3 else 255
    alpha = int(round(base * max(0.0, min(1.0, opacity))))
    return (color[0], color[1], color[2], alpha)


def gradient(size: Tuple[int, int], top: Tuple[int, int, int],
             bottom: Tuple[int, int, int]) -> Image.Image:
    """竖直线性渐变。

    没有背景图时用它兜底。纯色背景配立绘会显得很"贴纸",
    加一层渐变就有纵深感了 —— 而且完全不需要素材。
    """
    width, height = max(1, size[0]), max(1, size[1])
    strip = Image.new("RGB", (1, height))
    pixels = strip.load()
    for y in range(height):
        ratio = y / float(max(1, height - 1))
        pixels[0, y] = tuple(
            int(top[channel] + (bottom[channel] - top[channel]) * ratio)
            for channel in range(3)
        )
    return strip.resize((width, height), Image.BILINEAR).convert("RGBA")


class LayerPainter:
    """把四层分别画到画布上。持有主题和几个观感参数。

    做成一个对象而不是四个散函数,是为了让"这次渲染用哪套设置"
    只传一次 —— 立绘大小、底板透明度、底板图这些参数要在多个图层里用。
    """

    def __init__(self, theme: Theme,
                 dialog_opacity: float = 1.0,
                 panel_opacity: float = 1.0,
                 character_scale: float = 1.0,
                 character_anchor_x: float = 0.995,
                 character_anchor_y: float = 0.67,
                 character_centred: bool = False,
                 character_centre_x: bool = False,
                 panel_image: Optional[str] = None) -> None:
        self.theme = theme
        self.dialog_opacity = dialog_opacity
        self.panel_opacity = max(0.0, min(1.0, panel_opacity))
        self.character_scale = character_scale
        self.character_anchor_x = character_anchor_x
        self.character_anchor_y = character_anchor_y
        # 落点算不算"贴边留白"。对话页要老师站在正中,就不能再减留白。
        self.panel_image = panel_image or ""
        # 立绘的位置和命中测试都在 ui/character.py —— 画图和"点到没有"
        # 必须是同一个答案,所以两边共用这一个对象。
        self.characters = CharacterPlacer(theme, scale=character_scale,
                                          anchor_x=character_anchor_x,
                                          anchor_y=character_anchor_y,
                                          centred=character_centred,
                                          centre_x=character_centre_x)

    # ---- 背景 ------------------------------------------------------------

    def backdrop(self, size: Tuple[int, int], background: Optional[str]) -> Image.Image:
        """背景层。有图用图,没图用渐变。"""
        if background:
            image = load_image(background, size, self.theme)
            # 图片被等比缩放后可能留白,留白处用主题底色填满
            flat = Image.new("RGBA", size, self.theme.background + (255,))
            flat.alpha_composite(image)
            return flat
        return gradient(size, self.theme.background, self.theme.panel_light)

    # ---- 立绘 ------------------------------------------------------------

    def character(self, canvas: Image.Image, path: str) -> Image.Image:
        """立绘层:按布局算出的框缩放,贴到算出的坐标上。

        为什么不能铺满、为什么靠右上 —— 以及"被对话框挡住多少"这个后果,
        都在 ui/layout.character_rect 里解释。这里只负责照着摆。
        """
        box = self.characters.box(canvas.size, path)
        sprite = load_image(path, (box.width, box.height), self.theme)
        canvas.alpha_composite(sprite, (box.left, box.top))
        return canvas

    # ---- 内容底板 --------------------------------------------------------

    def panel(self, canvas: Image.Image,
              frame_box: Tuple[float, float, float, float]) -> Image.Image:
        """内容底板:一层底色(或用户自己的图片)按设定透明度盖上去。

        **它必须画在整张图里,不能用 Tk 控件去做。** Tk 的 Frame 没有
        alpha 填充色(Frame 上根本没有 `-alpha` 这个选项),想让"底"能透、
        能换图,只有两条路 —— 把控件做成图片,或者把它画进这张合成图。
        后者便宜得多,而且效果**可测**:合成出来什么样,屏幕上就什么样。

        代价是底板上的文字和卡片仍是真实的 Tk 控件(输入框必须是真的,
        中文输入法才有效),它们只能用**算出来的那个颜色**把自己藏进去
        (见 panel_content_color 与 ui/surface.py)。
        """
        left, top, right, bottom = box_rect(canvas.size, frame_box)
        if right <= left or bottom <= top:
            return canvas

        plate_size = (right - left, bottom - top)
        fill = tuple(self.theme.background)[:3] or PANEL_FILL_FALLBACK
        plate = self._panel_plate(plate_size, fill)

        # 裁成圆角 + 按设定透明度压到场景上,一步做完
        mask = Image.new("L", plate_size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, plate_size[0] - 1, plate_size[1] - 1],
            radius=DIALOG_RADIUS, fill=int(round(255 * self.panel_opacity)))
        canvas.paste(plate, (left, top), mask)

        # 圆角描边,让底板和背景之间有一条可辨的界线
        outline = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ImageDraw.Draw(outline).rounded_rectangle(
            [left, top, right, bottom], radius=DIALOG_RADIUS,
            outline=scaled(self.theme.panel_light,
                           self.panel_opacity * BORDER_OPACITY), width=2)
        canvas.alpha_composite(outline)
        return canvas

    def _panel_plate(self, size: Tuple[int, int],
                     fill: Tuple[int, int, int]) -> Image.Image:
        """底板本身的图:先铺一层底色,再把用户选的图片盖上去。

        底色是**不透明**的,透明度统一在贴到场景上那一步做 ——
        两处都半透明的话,实际透出来的程度会是两个数的乘积,
        用户按滑块位置完全猜不到会发生什么。
        """
        plate = Image.new("RGBA", size, fill + (255,))
        image = self._panel_image(size)
        if image is not None:
            image = image.convert("RGBA")
            plate.alpha_composite(image, ((size[0] - image.width) // 2,
                                          (size[1] - image.height) // 2))
        return plate

    def _panel_image(self, size: Tuple[int, int]) -> Optional[Image.Image]:
        """把用户选的底板图缩放到这块底板里。没选、或文件不在就是 None。

        **先自己看一眼文件在不在,不能直接交给 load_image。** 那个函数
        的契约是"读不到就给一张画着路径的占位框" —— 对背景和立绘来说
        那是正确的设计(用户需要知道该往哪放图),但底板缺图时我们要的
        是一块干净的白底,而不是一块写着文件名的灰板。

        文件在、但内容坏了(截断、格式不支持),那时占位框反而是有用的
        提示,所以那种情况交给 load_image 处理。
        """
        if not self.panel_image:
            return None
        resolved = resolve_image_path(self.panel_image)
        if resolved is None or not resolved.exists():
            return None
        try:
            return load_image(self.panel_image, size, self.theme)
        except Exception:                     # noqa: BLE001 —— 见 docstring
            return None

    # ---- 对话框 ----------------------------------------------------------

    def dialog(self, canvas: Image.Image, speaker: str, text: str,
               max_lines: int = 0) -> Image.Image:
        """对话框层:半透明圆角板 + 名字牌 + 正文。

        **板、名字牌、文字分三层合成。** 以前三层画在同一张 overlay 上
        再整体贴上去,于是"让框更透"会把字也一起弄糊 —— 用户要的是看见
        背景,不是看不清老师说的话。现在板先贴、正文最后直接画在合成后的
        画布上,透明度只作用在板上。
        """
        left, top, right, bottom = dialog_rect(canvas.size)

        plate = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        plate_draw = ImageDraw.Draw(plate)
        self._draw_panel(plate_draw, left, top, right, bottom)
        text_top = top + DIALOG_PADDING
        if speaker:
            self._draw_name_plate(plate_draw, speaker, left, top, canvas.size[0])
            # 名字牌落在板的上沿,正文要从它下面开始,否则会被牌子压住
            text_top = top + DIALOG_PADDING + 8
        canvas.alpha_composite(plate)

        self._draw_body(ImageDraw.Draw(canvas), text, max_lines, text_top,
                        left + DIALOG_PADDING, right - left - DIALOG_PADDING * 2,
                        bottom - DIALOG_PADDING)
        return canvas

    def _draw_panel(self, draw: ImageDraw.ImageDraw, left: int, top: int,
                    right: int, bottom: int) -> None:
        """对话框本体:一层投影 + 一块半透明的圆角板。"""
        theme = self.theme
        draw.rounded_rectangle(
            [left + 4, top + 6, right + 4, bottom + 6],
            radius=DIALOG_RADIUS, fill=(0, 0, 0, int(255 * SHADOW_OPACITY)))
        draw.rounded_rectangle(
            [left, top, right, bottom], radius=DIALOG_RADIUS,
            fill=scaled(theme.dialog_fill, self.dialog_opacity * DIALOG_PANEL_OPACITY),
            outline=scaled(theme.dialog_border, self.dialog_opacity * BORDER_OPACITY),
            width=2)

    def _draw_name_plate(self, draw: ImageDraw.ImageDraw, speaker: str,
                         left: int, top: int, canvas_width: int) -> None:
        """画名字牌。它跨在对话框上边缘上,像贴上去的标签。"""
        theme = self.theme
        font = get_font(18, bold=True)
        plate_width = min(text_width(speaker, font) + 36,
                          max(120, canvas_width - left - 40))
        draw.rounded_rectangle(
            [left + 16, top - NAME_PLATE_HEIGHT // 2,
             left + 16 + plate_width, top + NAME_PLATE_HEIGHT - NAME_PLATE_HEIGHT // 2],
            radius=10,
            fill=scaled(theme.accent, self.dialog_opacity * NAME_PLATE_OPACITY))
        draw.text((left + 34, top - NAME_PLATE_HEIGHT // 2 + 7), speaker,
                  font=font, fill=theme.accent_text + (255,))

    def _draw_body(self, draw: ImageDraw.ImageDraw, text: str, max_lines: int,
                   top: int, left: int, max_width: int, bottom_limit: int) -> None:
        """画正文。超出可用高度时截断并加省略号。"""
        theme = self.theme
        font = get_font(20)
        line_height = text_height(font) + LINE_SPACING

        available = max(1, (bottom_limit - top) // max(1, line_height))
        limit = max_lines if max_lines > 0 else available

        lines = wrap_text(text, font, max_width)
        if len(lines) > limit:
            # 截断而不是把字缩到看不清 —— 想看全文可以去对话记录里翻
            lines = lines[:limit]
            lines[-1] = lines[-1][:-1] + "…"

        for index, line in enumerate(lines):
            draw.text((left, top + index * line_height), line,
                      font=font, fill=theme.text + (255,))
