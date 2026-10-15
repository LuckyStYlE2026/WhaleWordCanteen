# -*- coding: utf-8 -*-
"""底板颜色与"坐在底板上该用什么字色"。

**为什么需要这么一个模块。**

底板(主界面左侧那一块、学习页的单词框那一块)是画在场景图里的 ——
只有画进图里才能半透明、才能换成用户的图片。可是底板上的文字、卡片、
输入框都是**真实的 Tk 控件**,而 Tk 控件的底色只能是纯色,没有 alpha。

于是它们之间需要一个翻译:

1. "那块底板看起来是什么颜色" —— 控件用这个颜色当底色,看起来就贴在底板上;
2. "在这块底色上,字该用深色还是浅色" —— 底板默认是白的,而界面的默认
   文字是浅灰白,白底白字等于看不见。

这两件事必须只有一处算法。两边各算一遍必然会漂移:改了透明度、换了
底板图,控件没跟上,界面上就会出现"一块明显不一样的方块"。
"""
from typing import Optional, Tuple

from .theme import Theme, contrast_ratio

# 判定"这块底算浅色吗"的阈值。底板默认铺的是**主题背景色**,所以深色主题
# 下是一块深蓝灰的板、浅色主题下是一块接近白的板 —— 两套主题各走一条分支。
# 0.30 是"中间偏暗"的位置:比它亮就用深色字,比它暗就沿用主题的浅色字。
PANEL_SWITCH_LUMINANCE = 0.30


# 浅色底上用的两档深色文字。
#
# 之所以要**两档都换**,而不是只换正文:次要文字(那行"第 1 / 3 屏")
# 在主题里是浅灰,放到白底上只有 1.4:1 —— 等于消失。而"次要"是指
# 视觉权重低,不是看不见,所以它也得达到能读的程度。
#
# 取值是被"整个透明度范围都要读得清"逼出来的:底板最暗只到 0.5
# (见 core/config.py 的下限),那一档底色约 (160,162,168),这两档
# 在那里的对比度分别是 3.4:1 和 4.5:1。
DARK_TEXT = (32, 38, 56)
DARK_TEXT_DIM = (36, 42, 58)

# 深色底上用的两档浅色文字。
#
# ⚠️ 和上面那两档是**成对**的:在深色底板上,主题自带的 text_dim
# (150,160,185)只有 2.2:1 —— 深色卡片上读不清,这里换成更亮的一档。
LIGHT_TEXT = (236, 240, 250)
LIGHT_TEXT_DIM = (180, 188, 208)

# 浅色底板上的词卡曾经用这一套反转配色。**已经不用了** ——
# 浅色主题下浅底板旁边杵一块深卡太不协调,卡片改用主题自己的 panel。
# 这几个值留给"深色卡片"这一种情况(插件换主题时可能用得上)。
DARK_CARD = (44, 52, 74)
DARK_CARD_BORDER = (86, 96, 124)
DARK_CARD_TEXT = (236, 240, 250)
DARK_CARD_TEXT_DIM = (176, 184, 204)
DARK_CARD_ACCENT = (150, 190, 255)

# 深色底板上的词卡(沿用主题那套深色)
LIGHT_CARD_ACCENT = (190, 215, 255)

# 浅色卡片上的释义色。比 LIGHT_CARD_ACCENT 深一档:
# 它在白卡上是 3.5:1,而 LIGHT_CARD_ACCENT 在白卡上只有 1.4:1(等于看不见)。
DARK_CARD_LIGHT_ACCENT = (36, 64, 140)


def is_light(background: Tuple[int, int, int]) -> bool:
    """这块底色该配**深色字**吗。

    名字说的是底色,判断的依据是"哪套字在这块底上更清楚"。
    """
    return _luminance(background) > PANEL_SWITCH_LUMINANCE


def _luminance(color: Tuple[int, ...]) -> float:
    return (0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]) / 255.0


def on_panel(background: Tuple[int, int, int], light: Tuple[int, int, int],
             dark: Tuple[int, int, int]) -> Tuple[int, int, int]:
    """在这块底色上,浅色和深色哪个更读得清,就返回哪个。"""
    if contrast_ratio(light, background) >= contrast_ratio(dark, background):
        return light
    return dark


def panel_content_color(theme: Theme, image: Optional["Image.Image"] = None) -> \
        Tuple[int, int, int]:
    """底板**看起来**是什么颜色。

    这是全套配色计算的起点:底板画在图里(能换图、能调透明度),
    而底板上的控件底色只能是纯色 —— 必须先知道"那块底是什么颜色",
    才能给控件选底色和字色。

    底板的构成固定是两步:先铺一层主题背景色,再把用户的图片等比盖上。
    所以这里照这个顺序算出来就够了,不必真的合成一张图 ——
    这个模块因此**不需要依赖 Pillow**(image 允许为 None,类型只是好读)。
    """
    plate = tuple(theme.background)[:3]
    if image is not None:
        from .character import average_color
        plate = average_color(image, plate)
    return plate



def panel_text(theme: Theme, background: Tuple[int, int, int]) -> Tuple[int, int, int]:
    """底板上的正文色。

    刻意**只看底色深浅来选整套字色**,不像 on_panel 那样逐个颜色比对比度 ——
    正文和次要文字必须来自同一套,否则会出现"正文是深色、次要文字还是
    浅灰"的组合,那行字就没了(单元测试逐档验过整个透明度范围)。
    主题自己的正文色只在深色底上才够用,所以浅色底换成一整套深色版。
    """
    return DARK_TEXT if is_light(background) else tuple(theme.text)[:3]


def panel_text_dim(theme: Theme, background: Tuple[int, int, int]) -> Tuple[int, int, int]:
    """底板上的次要文字色。和正文同一套,只是更淡一档。

    "次要"是指视觉权重低,不是看不见 —— 主题自带的 text_dim 放到白底上
    只有 1.4:1,那是真的看不见。
    """
    if is_light(background):
        return DARK_TEXT_DIM
    lighter = tuple(theme.text_dim)[:3]
    if contrast_ratio(lighter, background) >= 3.0:
        return lighter
    return LIGHT_TEXT_DIM


def panel_palette(theme: Theme, image=None) -> dict:
    """底板上的整套颜色:底、正文、次要文字、以及"卡片"那一层。

    入参是**底板用的图片**(可能没有),不是已经算好的颜色 ——
    这样调用方不必自己先算一遍底板色,而那一步是最容易两边算岔的地方。

    **卡片用主题自己的那几个颜色。** 这里返工过一次:第一版写死成
    "底色浅就用深卡片 (44,52,74)",理由是"卡片和底同色会糊成一片"。
    结果在浅色主题下,浅色底板旁边杵着一块深蓝卡片,非常不协调。
    卡片的底色本来就该跟着主题走,而主题里现成就有 `panel` 和 `panel_light`
    (浅色主题下分别是白和浅蓝灰)—— 底板和卡片的区分靠那条描边,
    不靠反转配色,这也正是 v1.5 之前一直有效的做法。

    需要按底色挑的只有正文和次要文字:底板可能是用户的亮色图片,
    那时主题那套浅色字会看不见。
    """
    background = panel_content_color(theme, image)
    card = tuple(theme.panel)[:3]
    return {
        "surface": background,
        "text": panel_text(theme, background),
        "dim": panel_text_dim(theme, background),
        "accent": tuple(theme.accent)[:3],
        "card": card,
        "card_border": tuple(theme.panel_light)[:3],
        # 卡上的字按**卡片**的底色挑,不按底板 —— 底板亮而卡片是深色主题色时,
        # 拿底板的结论去写卡片会得到"深字压深卡片"这种读不清的组合
        "card_text": on_panel(card, DARK_TEXT, LIGHT_TEXT),
        "card_dim": on_panel(card, DARK_TEXT_DIM, LIGHT_TEXT_DIM),
        # 释义色有三档,按卡片底色挑:浅卡用深蓝、深卡用浅蓝。
        # 挑错的后果很具体 —— 浅蓝压在白卡上只有 1.4:1,等于没有释义。
        "card_accent": on_panel(card, DARK_CARD_LIGHT_ACCENT, LIGHT_CARD_ACCENT),
    }
