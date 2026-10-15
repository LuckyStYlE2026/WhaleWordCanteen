# -*- coding: utf-8 -*-
"""配色、字体、图片加载。

界面里所有"长什么样"的常量都收在这里:换一个主题就是换一套数字,
不用去十几个文件里找散落的颜色值。

三件事值得多说几句:

**字体必须显式指定。** Tkinter 默认字体在 Windows 上能显示中文,但 Pillow
在图片上写字时必须给出具体的字体文件,否则中文会变成一堆方块。
所以这里从系统字体里挑一个能用的,挑不到就退回 Pillow 内置字体
(那时英文还能看,中文会变方块 —— 但至少程序不崩)。

**缺图是常态,不是异常。** 第一版的美术素材由用户自备,所以图片几乎
一定不全。load_image() 找不到文件时会画一个主题色占位框,
并在框里写上"它期望的文件路径" —— 用户照着路径把图丢进去就行,
不需要查文档。

**PhotoImage 必须保持强引用。** 这是 Tkinter 最经典的一个坑:
ImageTk.PhotoImage 建出来的对象如果只被局部变量引用,函数一返回就被
垃圾回收,界面上留下一块空白(而且不报错)。所以所有 PhotoImage
都经 ui/photos.py 的 to_photo() 生成并登记 —— 那里解释了为什么。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from PIL import Image, ImageDraw

from core import storage
from core.paths import image_dir


# --------------------------------------------------------------------------
# 配色
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Theme:
    """一套配色。字段名说明用途,不用"color1/color2"这种名字。"""

    name: str
    background: Tuple[int, int, int]        # 最底层背景
    panel: Tuple[int, int, int]             # 卡片/面板底色
    panel_light: Tuple[int, int, int]       # 悬停/选中的面板
    dialog_fill: Tuple[int, int, int, int]  # 对话框(半透明,叠在背景上)
    dialog_border: Tuple[int, int, int, int]
    text: Tuple[int, int, int]              # 正文
    text_dim: Tuple[int, int, int]          # 次要说明文字
    accent: Tuple[int, int, int]            # 强调色:按钮、标题、进度条
    accent_text: Tuple[int, int, int]       # 强调色底上的文字
    good: Tuple[int, int, int]              # 答对
    warn: Tuple[int, int, int]              # 模糊
    bad: Tuple[int, int, int]               # 答错
    placeholder_fill: Tuple[int, int, int]  # 缺图占位框

    def to_tuple(self, field: str) -> Tuple[int, ...]:
        return getattr(self, field)

    def flat_image(self, size: Tuple[int, int],
                   field: str = "panel") -> Image.Image:
        """一块纯色 RGBA 画布。

        用来给立绘当底:立绘是带 alpha 的 PNG,直接贴到控件上会带出
        一圈别的颜色;先合成到跟面板同色的底上就干净了。
        """
        color = self.to_tuple(field)
        return Image.new("RGBA", size, color[:3] + (255,))


# 默认主题:深靛蓝的夜色,对话框偏暖,让文字读起来不刺眼。
DEFAULT_THEME = Theme(
    name="default",
    background=(18, 22, 38),
    panel=(30, 36, 58),
    panel_light=(44, 52, 80),
    dialog_fill=(24, 28, 46, 225),
    dialog_border=(120, 140, 200, 255),
    text=(236, 240, 250),
    text_dim=(150, 160, 185),
    accent=(120, 160, 255),
    accent_text=(14, 18, 32),
    good=(110, 210, 150),
    warn=(240, 195, 100),
    bad=(240, 120, 130),
    placeholder_fill=(46, 54, 82),
)

# 浅色主题。夜里用深色,白天用浅色 —— 背单词是个长期活儿,
# 一直盯深色也累。
LIGHT_THEME = Theme(
    name="light",
    background=(244, 246, 251),
    panel=(255, 255, 255),
    panel_light=(226, 233, 247),
    dialog_fill=(252, 253, 255, 232),
    dialog_border=(150, 170, 215, 255),
    text=(28, 34, 52),
    text_dim=(110, 120, 145),
    accent=(70, 110, 220),
    accent_text=(255, 255, 255),
    good=(40, 160, 100),
    warn=(200, 140, 30),
    bad=(200, 70, 80),
    placeholder_fill=(224, 230, 242),
)

THEMES: Dict[str, Theme] = {"default": DEFAULT_THEME, "light": LIGHT_THEME}


def get_theme(name: str) -> Theme:
    """按名字取主题。名字不认识时给默认主题,不报错。"""
    return THEMES.get(name, DEFAULT_THEME)


# --------------------------------------------------------------------------
# 颜色算术
# --------------------------------------------------------------------------
#
# 放在这里而不是 scene.py:这是**纯算术**,不碰图片也不碰控件。
# 它同时被两边用到 —— 场景合成器(画底板时)和界面层(算控件的底色时)。
# 让 scene 来提供它,界面层从 scene 拿一个颜色函数是很怪的依赖方向。

def blend_over(front: Tuple[int, int, int], back: Tuple[int, int, int],
               opacity: float) -> Tuple[int, int, int]:
    """把 front 按 opacity 盖在 back 上,算出最终颜色。

    底板是画在合成图里的(所以能半透明、能换图),而底板上的文字和卡片
    都是真实的 Tk 控件 —— Tk 控件的底色只能是纯色、没有 alpha。
    于是必须有人算出"那块底板看起来是什么颜色",控件才能用这个颜色
    把自己藏进去。两边各算一遍一定会漂移,所以这里是**唯一**的口径。
    """
    ratio = max(0.0, min(1.0, opacity))
    return tuple(
        int(round(front[channel] * ratio + back[channel] * (1.0 - ratio)))
        for channel in range(3)
    )


def luminance(color: Tuple[int, ...]) -> float:
    """相对亮度(0..1)。对比度计算用的就是它。"""
    return (0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]) / 255.0


def contrast_ratio(one: Tuple[int, ...], other: Tuple[int, ...]) -> float:
    """WCAG 对比度。1:1 是完全看不见,21:1 是黑白。"""
    high, low = sorted((luminance(one), luminance(other)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def readable_text_color(background: Tuple[int, int, int],
                        light: Tuple[int, int, int],
                        dark: Tuple[int, int, int]) -> Tuple[int, int, int]:
    """在这块底色上,浅色字和深色字哪个更读得清,就返回哪个。

    底板默认是白的,而白底上写浅灰字是看不清的 —— 用户把透明度拉低、
    底色变深之后浅色字又变回正确选择。与其让用户自己去调文字颜色,
    不如按对比度自动选一个:这是**能算的**,就不该让人猜。
    """
    return light if contrast_ratio(light, background) >= contrast_ratio(dark, background) \
        else dark


# 字体实现住在 ui/fonts.py(那里不依赖主题)。这里 import 进来,
# theme 自己要用,scene 等调用方也从这里拿 —— 字体入口只有这一个名字。
from .fonts import (                    # noqa: E402  —— 放在这里是为了先定义 Theme
    get_font,
    text_height,
    text_width,
    wrap_text,
)


# --------------------------------------------------------------------------
# 图片
# --------------------------------------------------------------------------

# 缺图占位框里显示的提示行数上限。太长会把占位框撑破。
_PLACEHOLDER_MAX_LINES = 6


def make_placeholder(size: Tuple[int, int], label: str = "",
                     theme: Optional[Theme] = None) -> Image.Image:
    """画一个占位框:主题色底 + 虚线边 + 期望的文件路径。

    第一版素材由用户自备,所以"缺图"是常态。与其留一片空白让用户困惑,
    不如把该放哪儿直接写在图上。
    """
    theme = theme or DEFAULT_THEME
    width, height = max(16, size[0]), max(16, size[1])
    image = Image.new("RGBA", (width, height), theme.placeholder_fill + (235,))
    draw = ImageDraw.Draw(image)

    # 虚线边框:一段一段画,每段之间留空隙
    step, dash = 12, 7
    for x in range(0, width, step):
        draw.line([(x, 0), (min(x + dash, width), 0)], fill=theme.text_dim + (200,), width=2)
        draw.line([(x, height - 1), (min(x + dash, width), height - 1)],
                  fill=theme.text_dim + (200,), width=2)
    for y in range(0, height, step):
        draw.line([(0, y), (0, min(y + dash, height))], fill=theme.text_dim + (200,), width=2)
        draw.line([(width - 1, y), (width - 1, min(y + dash, height))],
                  fill=theme.text_dim + (200,), width=2)

    if not label:
        return image

    font = get_font(max(11, min(16, width // 22)))
    lines = wrap_text(label, font, width - 24)[:_PLACEHOLDER_MAX_LINES]
    line_height = text_height(font) + 4
    top = max(8, (height - line_height * len(lines)) // 2)
    for index, line in enumerate(lines):
        offset_x = max(8, (width - text_width(line, font)) // 2)
        draw.text((offset_x, top + index * line_height), line,
                  font=font, fill=theme.text_dim + (235,))
    return image


def load_image(path, size: Optional[Tuple[int, int]] = None,
               theme: Optional[Theme] = None) -> Image.Image:
    """读一张图;读不到就返回占位框。

    path 可以是绝对路径,也可以是相对 assets/ 的路径
    (例如 "ai/default/happy.png") —— 后者是存档和配置里存的形式,
    这样整个项目目录搬个位置也不会失效。
    """
    resolved = resolve_image_path(path)
    if resolved is not None and resolved.exists():
        try:
            image = Image.open(str(resolved)).convert("RGBA")
            if size:
                image = fit_into(image, size)
            return image
        except (OSError, ValueError) as exc:
            # 图片坏了(格式不支持、文件被截断)。当成缺图处理,
            # 不该让一张坏图把整个界面卡死。
            storage.log_error("图片 %s 读取失败: %s" % (resolved, exc))

    label = str(path)
    if resolved is not None:
        label = str(resolved)
    return make_placeholder(size or (240, 360), label, theme)


def resolve_image_path(path) -> Optional[Path]:
    """把"相对 assets/ 的路径"或绝对路径统一成 Path。"""
    if path is None:
        return None
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return image_dir() / candidate


def fit_into(image: Image.Image, size: Tuple[int, int]) -> Image.Image:
    """等比缩放并居中放到指定尺寸里(不裁剪、不拉伸)。

    立绘最怕被拉变形,所以宁可留白也不改长宽比。
    """
    width, height = max(1, size[0]), max(1, size[1])
    if image.width <= 0 or image.height <= 0:
        return Image.new("RGBA", (width, height), (0, 0, 0, 0))

    scale = min(width / float(image.width), height / float(image.height))
    new_size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
    resized = image.resize(new_size, Image.LANCZOS)

    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas.paste(resized, ((width - new_size[0]) // 2, (height - new_size[1]) // 2))
    return canvas


# 场景和控件要用的 PhotoImage 都经 ui/photos.py 的 to_photo 生成 ——
# 那里解释了为什么不直接调 ImageTk(两个坑:强引用、master)。
# 从 theme 再导出,是因为历史调用方一直是从这里拿的。
from .photos import to_photo  # noqa: E402,F401
