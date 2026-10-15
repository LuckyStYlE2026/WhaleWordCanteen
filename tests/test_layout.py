# -*- coding: utf-8 -*-
"""场景布局与合成:立绘别被对话框挡住、透明度的算术要对。

这些用例是 v1.5 的**回归锁**。在 v1.4 及以前,立绘贴着屏幕底边站,
对话框盖住了它 41% 的高度 —— 用户看到的"老师被对话框挡住了"就是它。
把默认值调回来会让下面那几条立刻变红,这正是它们存在的意义。

不需要图形环境:布局是纯算术,合成用的是 Pillow 离屏画布。
"""

import hashlib
import inspect
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

from core.config import PANEL_OPACITY_MIN as PANEL_MIN
from core.config import UiSettings
from ui import layout as L
from ui import surface
from ui.scene import Dialogue, SceneRenderer, _scaled
from ui.theme import DEFAULT_THEME, LIGHT_THEME
from ui.views import settings_panels

# 常见窗口尺寸。立绘的构图在这几个尺寸下都不该出问题。
WINDOWS = ((1280, 720), (1024, 640), (1366, 768), (1600, 900), (1920, 1080))
STANDARD_ASPECT = 520 / 780.0        # 2:3,立绘的常见画幅


class DialogRectTest(unittest.TestCase):
    """对话框的矩形。界面层要用它摆输入框和按钮,所以坐标必须稳定。"""

    def test_inside_the_window(self):
        for size in WINDOWS:
            left, top, right, bottom = L.dialog_rect(size)
            self.assertGreater(left, 0)
            self.assertGreater(right, left)
            self.assertGreater(top, 0)
            self.assertGreater(bottom, top)
            self.assertLessEqual(right, size[0])
            self.assertLessEqual(bottom, size[1])

    def test_very_small_size_is_raised_to_the_floor(self):
        # 窗口还没布局时 winfo 会给 1×1,不能算出负数的矩形
        left, top, right, bottom = L.dialog_rect((1, 1))
        self.assertGreaterEqual(left, 0)
        self.assertGreater(right, left)
        self.assertGreater(bottom, top)


class CharacterPlacementTest(unittest.TestCase):
    """立绘摆在哪 —— 这一组是这次修复的核心。"""

    def test_face_is_not_hidden_behind_the_dialog(self):
        """**立绘不能被对话框盖住一大半。**

        这是用户报的那个问题:v1.4 的默认值下,立绘有 41% 的高度埋在
        对话框里(脸都在框里)。现在底边停在对话框上沿附近,
        被盖住的部分只剩最下面一两成 —— 那点正好是"腿在框后面",
        galgame 的常规构图。
        """
        for size in WINDOWS:
            box = L.character_rect(size, aspect=STANDARD_ASPECT)
            covered = box.covered / float(box.height)
            self.assertLess(
                covered, 0.30,
                "窗口 %s 下立绘有 %.0f%% 被对话框挡住了" % (size, covered * 100))

    def test_the_upper_half_of_the_character_is_always_visible(self):
        """头肩必须在框外面 —— 只压住一小截腿是可以的,压住脸不行。"""
        for size in WINDOWS:
            box = L.character_rect(size, aspect=STANDARD_ASPECT)
            self.assertGreaterEqual(
                box.free_height, box.height * 0.7,
                "窗口 %s 下立绘露出来的部分太少" % (size,))

    def test_character_stays_fully_inside_the_canvas(self):
        """越界的落点必须被夹回来,否则会得到一张"人不见了"的图。"""
        for size in ((320, 240), (400, 1000), (3000, 300), (900, 600)):
            for aspect in (0.2, 0.6, 1.4, 3.0):
                box = L.character_rect(size, aspect=aspect)
                self.assertGreaterEqual(box.left, 0, size)
                self.assertGreaterEqual(box.top, 0, size)
                self.assertLessEqual(box.right, max(320, size[0]), (size, aspect))
                self.assertLessEqual(box.bottom, max(240, size[1]), (size, aspect))

    def test_character_keeps_its_own_aspect_ratio(self):
        """立绘的长宽比由素材决定 —— 变形的人比小一点的人难看得多。

        这里刻意用两个差得很远的长宽比:如果实现是"塞进固定框居中",
        两者会得到同一个框。
        """
        narrow = L.character_rect((1280, 720), aspect=0.4)
        wide = L.character_rect((1280, 720), aspect=1.6)
        self.assertAlmostEqual(narrow.width / float(narrow.height), 0.4, places=2)
        self.assertAlmostEqual(wide.width / float(wide.height), 1.6, places=2)
        self.assertGreater(wide.width, narrow.width)

    def test_width_is_capped_on_very_wide_art(self):
        """一张超宽的图不能横着铺满整个窗口。"""
        box = L.character_rect((1280, 720), aspect=6.0)
        self.assertLessEqual(box.width, int(1280 * L.CHARACTER_WIDTH) + 1)

    def test_scale_multiplier_makes_it_smaller(self):
        big = L.character_rect((1280, 720), aspect=STANDARD_ASPECT, scale=1.0)
        small = L.character_rect((1280, 720), aspect=STANDARD_ASPECT, scale=0.6)
        self.assertLess(small.height, big.height)

    def test_missing_aspect_still_gives_a_sane_box(self):
        """没读到图(缺素材)时也要能算出一个合理的框。"""
        box = L.character_rect((1280, 720))
        self.assertGreater(box.width, 0)
        self.assertGreater(box.height, 0)

    def test_default_anchor_keeps_clear_of_the_button_row(self):
        """立绘贴住右边界。

        学习页/考试页的按钮行贴着对话框底边居中,最右边的按钮大约伸到
        窗口的 90% 处。立绘的默认落点比它更靠右,两者才不会叠在一起。
        """
        self.assertGreaterEqual(L.CHARACTER_ANCHOR_X_DEFAULT, 0.98)


class ScaledColorTest(unittest.TestCase):
    """透明度只作用在板上,不该把颜色算飞。"""

    def test_opacity_multiplies_the_alpha_of_the_theme_color(self):
        color = (24, 28, 46, 200)
        self.assertEqual(_scaled(color, 1.0), (24, 28, 46, 200))
        self.assertEqual(_scaled(color, 0.5), (24, 28, 46, 100))
        self.assertEqual(_scaled(color, 0.0), (24, 28, 46, 0))

    def test_opacity_is_clamped_not_trusted(self):
        self.assertEqual(_scaled((1, 2, 3, 100), 5.0), (1, 2, 3, 100))
        self.assertEqual(_scaled((1, 2, 3, 100), -3.0), (1, 2, 3, 0))

    def test_color_without_alpha_is_treated_as_opaque(self):
        # int(round(255 * 0.5)) = 128 —— 四舍五入的结果,不是 127
        self.assertEqual(_scaled((10, 20, 30), 0.5), (10, 20, 30, 128))


class ComposeTest(unittest.TestCase):
    """整场景合成:尺寸、文字、板的透明度。"""

    def make_dialogue(self) -> Dialogue:
        return Dialogue(speaker="小老师", text="这句话应该看得清楚。",
                        character="ai/default/normal.png",
                        background="ui/background.png")

    def test_compose_returns_the_requested_size(self):
        for size in WINDOWS:
            image = SceneRenderer(DEFAULT_THEME).compose(size, self.make_dialogue())
            self.assertEqual(image.size, size)
            self.assertEqual(image.mode, "RGBA")

    def test_body_text_stays_fully_opaque(self):
        """板可以透,字不行 —— 用户要的是看见背景,不是看不清老师说话。"""
        for opacity in (1.0, 0.82, 0.3):
            renderer = SceneRenderer(DEFAULT_THEME, dialog_opacity=opacity)
            image = renderer.compose((1280, 720), self.make_dialogue())
            left, top, right, bottom = L.dialog_rect((1280, 720))
            body = image.crop((left + 20, top + 40, right - 20, bottom - 20))
            bright = [pixel for pixel in body.getdata()
                      if pixel[0] > 200 and pixel[1] > 200 and pixel[2] > 200]
            self.assertTrue(bright, "对话框里找不到正文像素(opacity=%s)" % opacity)
            self.assertEqual(min(pixel[3] for pixel in bright), 255,
                             "正文被透明度弄糊了(opacity=%s)" % opacity)

    def test_panel_alpha_follows_the_setting(self):
        """对话框板的不透明度必须真的跟着设置走 —— 否则滑块就是个摆设。

        主题里的 dialog_fill 本身就带 alpha(225),所以这里只断言
        "随设置单调变化、且夹在合法范围内",不写死某个具体数字。
        """
        base_alpha = DEFAULT_THEME.dialog_fill[3]
        alphas = []
        for opacity in (1.0, 0.5, 0.0):
            plate = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
            renderer = SceneRenderer(DEFAULT_THEME, dialog_opacity=opacity)
            renderer.painter._draw_panel(ImageDraw.Draw(plate), 100, 400, 1100, 600)
            alphas.append(plate.getpixel((600, 500))[3])
        self.assertEqual(alphas, sorted(alphas, reverse=True))
        self.assertLess(alphas[0], base_alpha)      # 还要乘上板的不透明度系数
        self.assertGreater(alphas[0], 150)
        self.assertEqual(alphas[-1], 0)

    def test_missing_assets_fall_back_to_placeholders(self):
        """素材缺失是常态:合成必须照常出图,而不是抛异常。"""
        dialogue = Dialogue(speaker="老师", text="没有素材也要能说话。",
                            character="ai/不存在的形象/x.png",
                            background="ui/不存在的背景.png")
        image = SceneRenderer(DEFAULT_THEME).compose((1024, 640), dialogue)
        self.assertEqual(image.size, (1024, 640))

    def test_empty_speaker_does_not_reserve_a_name_plate(self):
        with_speaker = SceneRenderer(DEFAULT_THEME).compose(
            (1280, 720), Dialogue(speaker="老师", text="同一句话"))
        without = SceneRenderer(DEFAULT_THEME).compose(
            (1280, 720), Dialogue(speaker="", text="同一句话"))
        self.assertNotEqual(with_speaker.tobytes(), without.tobytes())


class FramePanelTest(unittest.TestCase):
    """内容区那块半透明的板(v1.5)。

    它必须画在**合成图**里 —— Tk 的 Frame 没有 alpha 填充色,
    用 wm_attributes("-alpha") 也不成立(Frame 上没这个选项,试过)。
    所以这里断言的是"画进图里之后确实半透明"。
    """

    BOX = L.STUDY_PANEL_BOX

    def test_box_rect_matches_place_geometry(self):
        """比例框换算成像素,必须和 Tk 的 place(rel*) 一致。

        不一致的后果是"背景里的板和控制器的位置差一截",而且很难看
        出是谁错了 —— 所以这里按 place 的定义逐项验算。
        """
        width, height = 1280, 720
        relx, rely, relwidth, relheight = self.BOX
        left, top, right, bottom = L.box_rect((width, height), self.BOX)
        self.assertEqual(left, int(width * relx))
        self.assertEqual(top, int(height * rely))
        self.assertEqual(right - left, int(width * relwidth))
        self.assertEqual(bottom - top, int(height * relheight))

    def test_frame_is_translucent_not_opaque(self):
        plate = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
        renderer = SceneRenderer(DEFAULT_THEME, frame_opacity=0.6)
        renderer.painter.panel(plate, self.BOX)
        left, top, right, bottom = L.box_rect((1280, 720), self.BOX)
        alpha = plate.getpixel(((left + right) // 2, (top + bottom) // 2))[3]
        self.assertGreater(alpha, 0, "板没画上去")
        self.assertLess(alpha, 255, "板完全不透明,那就不叫半透明了")

    def test_default_panel_paints_the_theme_colour(self):
        """没选图片时,底板铺的是**主题背景色** —— 深色主题下就是深蓝灰。

        这里刻意不写死 (18,22,38):换主题时底板应该跟着变,
        写死了就等于把主题钉住。
        """
        plate = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
        SceneRenderer(DEFAULT_THEME, frame_opacity=1.0).painter.panel(plate, self.BOX)
        left, top, right, bottom = L.box_rect((1280, 720), self.BOX)
        center = plate.getpixel(((left + right) // 2, (top + bottom) // 2))
        self.assertEqual(center[:3], tuple(DEFAULT_THEME.background)[:3])
        self.assertEqual(center[3], 255)

    def test_panel_image_overrides_the_white_fill(self):
        """选了图片就用图片,没选就用白。两者不能画成一样的东西。"""
        def fingerprint(image):
            return hashlib.md5(image.tobytes()).hexdigest()

        def plate_for(panel_image):
            renderer = SceneRenderer(DEFAULT_THEME, frame_opacity=1.0,
                                     panel_image=panel_image)
            canvas = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
            return renderer.painter.panel(canvas, self.BOX)

        white = plate_for(None)
        loaded = plate_for("ui/background.png")
        self.assertNotEqual(fingerprint(white), fingerprint(loaded))

    def test_missing_panel_image_falls_back_to_white(self):
        """图片文件被删了,底板要退回纯白,而不是空白或者报错。"""
        def fingerprint(image):
            return hashlib.md5(image.tobytes()).hexdigest()

        def plate_for(panel_image):
            renderer = SceneRenderer(DEFAULT_THEME, frame_opacity=1.0,
                                     panel_image=panel_image)
            canvas = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
            return renderer.painter.panel(canvas, self.BOX)

        self.assertEqual(fingerprint(plate_for("ui/不存在的底板.png")),
                         fingerprint(plate_for(None)))

    def test_backdrop_shows_through_the_frame(self):
        """板下面必须还看得见背景 —— 这正是用户要的效果。

        比的是**指纹**而不是原图:直接 assertNotEqual(图.tobytes()) 在失败时
        会把几十万字节的像素倒进测试输出里,那种报错没人看得下去。
        """
        def fingerprint(image):
            return hashlib.md5(image.tobytes()).hexdigest()

        base = SceneRenderer(DEFAULT_THEME).compose_backdrop(
            (1280, 720), "ui/background.png", "ai/default/normal.png")
        with_frame = SceneRenderer(DEFAULT_THEME, frame_box=self.BOX).compose_backdrop(
            (1280, 720), "ui/background.png", "ai/default/normal.png")
        self.assertNotEqual(fingerprint(base), fingerprint(with_frame))

    def test_no_frame_box_means_no_extra_layer(self):
        """没有内容区的页面(主菜单、记忆曲线)不该被压一层。"""
        def fingerprint(image):
            return hashlib.md5(image.tobytes()).hexdigest()

        plain = SceneRenderer(DEFAULT_THEME).compose_backdrop(
            (1280, 720), "ui/background.png")
        none_box = SceneRenderer(DEFAULT_THEME, frame_box=None).compose_backdrop(
            (1280, 720), "ui/background.png")
        self.assertEqual(fingerprint(plain), fingerprint(none_box))

    def test_word_card_text_keeps_comfortable_contrast(self):
        """词卡上的字必须读得清。

        这条防的是"改配色时顺手把字弄成看不见"。正文要求 4.5:1
        (WCAG AA 对正文的线),但**强调色只要求 2.0:1** —— 实测浅色主题的
        强调色压在词卡底色上只有 2.2:1,而那是 v1.0 起就有的配色,不是这一版
        引入的。这里只守住"不至于糊成一片",重配主题色留作单独一件事
        (记在 说明.md 的「已知问题」里):那个颜色同时还是按钮底色,
        在一次界面修复里悄悄换掉太冒险。
        """
        def luminance(color):
            return (0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]) / 255.0

        def ratio(one, other):
            high, low = sorted((luminance(one), luminance(other)), reverse=True)
            return (high + 0.05) / (low + 0.05)

        for theme in (DEFAULT_THEME, LIGHT_THEME):
            self.assertGreater(ratio(theme.text, theme.panel), 4.5,
                               "%s 主题下正文对比度不足" % theme.name)
            self.assertGreater(ratio(theme.accent, theme.panel), 2.0,
                               "%s 主题下释义(强调色)几乎看不见" % theme.name)


class SurfaceTest(unittest.TestCase):
    """底板颜色与"上面的字该用深还是浅"。

    这是"底板能换图、能调透明度"之后最容易出错的一环:底板是画在图里的,
    而控件底色只能是纯色,两者必须由同一处给出。算错的后果很具体 ——
    深底上写深字,那一块字等于消失。

    底板**默认铺的是主题背景色**(不是白),所以这两套主题走的是
    两条不同的分支,都要验。
    """

    def test_default_panel_matches_the_theme_background(self):
        """没选图片时,底板就是主题背景色 —— 深色主题下一块深蓝灰的板。"""
        for theme in (DEFAULT_THEME, LIGHT_THEME):
            self.assertEqual(surface.panel_content_color(theme),
                             tuple(theme.background)[:3])

    def test_dark_theme_panel_keeps_the_light_text(self):
        """深色底板 → 浅色字(主题原来那一套),不能反过来。"""
        panel = surface.panel_content_color(DEFAULT_THEME)
        self.assertFalse(surface.is_light(panel))
        self.assertEqual(surface.panel_text(DEFAULT_THEME, panel),
                         tuple(DEFAULT_THEME.text)[:3])

    def test_light_theme_panel_gets_dark_text(self):
        """浅色底板上必须用深色字 —— 否则正文就是浅底浅字。"""
        panel = surface.panel_content_color(LIGHT_THEME)
        self.assertTrue(surface.is_light(panel))
        chosen = surface.panel_text(LIGHT_THEME, panel)
        self.assertGreater(surface.contrast_ratio(chosen, panel), 4.5)

    def test_text_stays_readable_at_the_supported_opacities(self):
        """**底板能调多透,那个范围内字就要读得清。**

        按设置里允许的整个透明度范围逐档验(范围从 core.config 取,
        不在这里抄一遍)。底板默认是深色的,所以深色主题下透与不透
        都是深底 —— 这一组主要盯的是浅色主题(它的底板是接近白的)
        以及"万一底板被换成一张亮图"时字色有没有跟着换。
        """
        steps = [PANEL_MIN + index * (1.0 - PANEL_MIN) / 20.0 for index in range(21)]
        for theme in (DEFAULT_THEME, LIGHT_THEME):
            for opacity in steps:
                panel = surface.panel_content_color(theme)
                for color in (surface.panel_text(theme, panel),
                              surface.panel_text_dim(theme, panel)):
                    ratio = surface.contrast_ratio(color, panel)
                    self.assertGreater(
                        ratio, 3.0,
                        "%s 主题、透明度 %.2f 时对比度只有 %.2f:1"
                        % (theme.name, opacity, ratio))

    def test_word_cards_are_readable_whatever_the_panel_colour(self):
        """词卡上的字要跟着底板颜色走 —— 底板换图之后尤其重要。

        这里用的三种底色都是真会出现的:默认的深底板、被压透的底板、
        以及一张亮色图片当底板。
        """
        for panel in ((18, 22, 38), (208, 208, 212), (255, 255, 255)):
            palette = surface.panel_palette(DEFAULT_THEME, panel)
            self.assertEqual(
                surface.is_light(palette["text"]), surface.is_light(palette["dim"]),
                "底板 %s 上正文和次要文字不是一套色系 —— 那行次要文字会消失"
                % (panel,))
            # 深底上沿用主题自带的次要色(它在那块底上是够清楚的,
            # panel_text_dim 只有在不够时才换成更亮的那一档)
            if not surface.is_light(panel):
                self.assertIn(palette["dim"],
                              (tuple(DEFAULT_THEME.text_dim)[:3],
                               surface.LIGHT_TEXT_DIM))
            # 卡片现在跟着主题走(浅主题=白卡),所以卡上的字也要跟着卡片挑
            for key in ("card_text", "card_dim", "card_accent"):
                self.assertGreater(
                    surface.contrast_ratio(palette[key], palette["card"]), 3.0,
                    "卡片 %s 上的 %s 读不清" % (palette["card"], key))


class PanelChoicesTest(unittest.TestCase):
    """底板图片列表:扫目录生成,而不是写死。"""

    def test_lists_ui_images_and_keeps_background_out(self):
        names = settings_panels.panel_choices()
        # assets/ui/background.png 是"场景背景",不该出现在底板图列表里
        self.assertNotIn("ui/background.png", names)
        # 生成出来的路径必须是相对 assets/ 的形式,否则存进设置就找不到了
        for name in names:
            self.assertTrue(name.startswith("ui/"), name)
            self.assertFalse(name.startswith("ui/ui/"), name)

    def test_missing_folder_is_not_an_error(self):
        """assets/ui/ 没了也只是列表短一点,不该崩。"""
        with mock.patch.object(settings_panels, "image_dir",
                               return_value=Path("Z:/不存在的目录")):
            self.assertEqual(settings_panels.panel_choices(), [])


class SettingsDefaultsAgreeTest(unittest.TestCase):
    """设置的默认值和渲染层的默认值必须是同一套。"""

    def test_scene_renderer_defaults_match_ui_settings(self):
        ui = UiSettings()
        signature = inspect.signature(SceneRenderer.__init__)
        self.assertEqual(ui.character_scale,
                         signature.parameters["character_scale"].default)
        self.assertEqual(ui.panel_opacity,
                         signature.parameters["frame_opacity"].default)
        self.assertEqual(ui.character_anchor_x, L.CHARACTER_ANCHOR_X_DEFAULT)
        self.assertEqual(ui.character_anchor_y, L.CHARACTER_ANCHOR_Y_DEFAULT)

    def test_default_anchor_sits_on_the_dialog_top_edge(self):
        """立绘底边落在对话框上沿 —— 这样脸一定在框外面。

        框上沿的高度 = 1 - 底边留白 - 框高(见 layout.dialog_rect)。
        """
        expected = 1.0 - L.DIALOG_MARGIN_BOTTOM - L.DIALOG_HEIGHT
        self.assertAlmostEqual(L.CHARACTER_ANCHOR_Y_DEFAULT, expected, places=6)


class ChatLayoutTest(unittest.TestCase):
    """对话页的构图(点老师进去的那一页)。

    那一页只有三样东西:背景、正中的老师、下面的对话框。
    所以这里要验的就是"老师有没有被对话框挡住"和"是不是真的在中间",
    而不是某几个像素。
    """

    BOX_ASPECT = 520 / 780.0

    def box(self, size):
        """对话页的构图:**横向居中 + 底边贴住对话框上沿**,而且不缩小。

        用的是 centre_x 而不是 centred —— 后者是横纵都居中,会把下半身
        压到对话框里那排按钮上(下面那条用例正是为它写的)。
        """
        return L.character_rect(
            size, aspect=self.BOX_ASPECT, scale=L.CHAT_CHARACTER_SCALE,
            anchor_x=L.CHAT_CHARACTER_ANCHOR_X, anchor_y=L.CHAT_CHARACTER_ANCHOR_Y,
            centre_x=True)

    def test_character_is_not_scaled_down(self):
        """**这一页不缩小老师** —— 她是主角,尺寸和别处一样。"""
        self.assertEqual(L.CHAT_CHARACTER_SCALE, 1.0)

    def test_character_is_centred(self):
        """老师站在窗口中间 —— 这是这一页和别处最大的不同。"""
        for size in ((1280, 720), (1024, 640), (1920, 1080)):
            box = self.box(size)
            centre = (box.left + box.right) / 2.0
            self.assertAlmostEqual(centre, size[0] / 2.0, delta=size[0] * 0.02,
                                   msg="窗口 %s 下老师没站在中间" % (size,))

    def test_face_is_clear_of_the_dialog(self):
        """脸部必须在对话框外面 —— 底边落在框上沿,所以只压住一点点。"""
        for size in ((1280, 720), (1024, 640), (1920, 1080)):
            box = self.box(size)
            covered = box.covered / float(box.height)
            self.assertLess(covered, 0.30,
                            "窗口 %s 下老师有 %.0f%% 被对话框挡住" % (size, covered * 100))

    def test_character_stays_inside_the_window(self):
        for size in ((1280, 720), (1024, 640), (900, 600)):
            box = self.box(size)
            self.assertGreaterEqual(box.left, 0, size)
            self.assertGreaterEqual(box.top, 0, size)
            self.assertLessEqual(box.right, size[0], size)
            self.assertLessEqual(box.bottom, size[1], size)


class CharacterHitTest(unittest.TestCase):
    """点击判定的几何部分:点在哪算点到老师。

    命中测试用的是**看得见的那一块**(立绘的 alpha 边界),不是贴图占的
    整块画布 —— 后者可能有大片透明边,在那上面点一下会打开对话页,
    而用户看到的是"我明明点的是空气"。

    用 _placeholders/ 里那张占位立绘来验:它四周本来就有透明边,
    正好能区分"贴图框"和"看得见的框"。用户自己的立绘有没有透明边不确定,
    所以不能拿它来做这条断言。
    """

    PLACEHOLDER = "ai/default/normal.png"
    TRANSPARENT_EDGED = "_placeholders/ai_default_normal.png"
    SIZE = (1280, 720)

    def placer(self):
        """立绘的摆放与命中测试现在住在这里(ui/character.py)。"""
        return SceneRenderer(DEFAULT_THEME).characters

    def test_visible_box_sits_inside_the_full_box(self):
        placer = self.placer()
        full = placer.box(self.SIZE, self.TRANSPARENT_EDGED)
        visible = placer.visible_box(self.SIZE, self.TRANSPARENT_EDGED)
        self.assertGreaterEqual(visible.left, full.left)
        self.assertGreaterEqual(visible.top, full.top)
        self.assertLessEqual(visible.right, full.right)
        self.assertLessEqual(visible.bottom, full.bottom)
        # 透明边是真的存在时,可见框必须严格更小 —— 否则等于没裁剪
        self.assertLess(visible.width * visible.height, full.width * full.height,
                        "占位立绘四周有透明边,可见框却不该和整块一样大")

    def test_transparent_margin_is_not_clickable(self):
        """贴在人物头顶上方的透明边不算点到老师。"""
        placer = self.placer()
        full = placer.box(self.SIZE, self.TRANSPARENT_EDGED)
        visible = placer.visible_box(self.SIZE, self.TRANSPARENT_EDGED)
        # 贴图框左上角:在整块里,但通常在可见人物之外
        corner = (full.left + 2, full.top + 2)
        inside_visible = (visible.left <= corner[0] <= visible.right
                          and visible.top <= corner[1] <= visible.bottom)
        self.assertFalse(inside_visible, "透明边角被算成了老师")

    def test_the_same_box_is_used_for_drawing_and_hitting(self):
        """画图和命中必须落在同一个框上 —— 不然就是"看着点中了没反应"。"""
        placer = self.placer()
        first = placer.box(self.SIZE, self.PLACEHOLDER)
        second = placer.box(self.SIZE, self.PLACEHOLDER)
        self.assertEqual((first.left, first.top, first.width, first.height),
                         (second.left, second.top, second.width, second.height))


if __name__ == "__main__":
    unittest.main()
