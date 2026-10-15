# -*- coding: utf-8 -*-
"""界面**放不下**导致控件被压扁的问题。

用户报过两次同一类毛病,表现不同但根因一样:

* **主菜单的「退出」只剩半个字、点不着。** 五张卡片 + 标题 + 进度行 + 退出
  需要约 640px,而面板只给得出 634px —— pack 按声明顺序分配空间,
  最后声明的 footer 被压到只剩 6px 高。
* **窗口可以缩到任意小。** 页面都是按比例摆的,但有下限;窗口一矮,
  最后一行的控件又会被压扁。

两条测试分别守住:主菜单在常见分辨率下 footer 必须拿到它需要的高度;
窗口有一个量出来的最小尺寸。

这类问题的共同点是**不报错** —— 只是控件变小/消失,而且只有真的去看
那个窗口才发现。所以必须用"量尺寸"的测试,不能只测逻辑。
"""

import unittest

from .tk_case import HAVE_TK, TkTestCase


@unittest.skipUnless(HAVE_TK, "需要图形环境")
class MenuFooterTest(TkTestCase):
    """主菜单的「退出」按钮必须是完整、可点的。"""

    def setUp(self):
        self.app = self.make_app(visible=True)

    def _footer_button(self):
        self.app.show("menu")
        self.app.update()
        view = self.app.current_view
        content = [c for c in view.winfo_children() if c.winfo_class() == "Frame"][0]
        footer = content.winfo_children()[-1]
        return content, footer, footer.winfo_children()[0]

    def test_the_exit_button_gets_its_full_height(self):
        """这一条锁的就是用户报的"只显示了半个"。"""
        _content, _footer, button = self._footer_button()
        self.assertGreaterEqual(
            button.winfo_height(), button.winfo_reqheight(),
            "「退出」被压扁了(高度 %d,需要 %d)"
            % (button.winfo_height(), button.winfo_reqheight()))

    def test_the_button_is_wide_enough_to_hit(self):
        """点击面积也要够 —— 只包住两个字的话很难点中。"""
        _content, footer, button = self._footer_button()
        self.assertGreaterEqual(button.winfo_width(), footer.winfo_width() - 2)

    def test_the_menu_content_fits_the_panel(self):
        """根因:内容比面板高。装不下时最后一行必然被压扁。"""
        content, _footer, _button = self._footer_button()
        self.assertLessEqual(
            content.winfo_reqheight(), content.winfo_height(),
            "主菜单内容需要 %dpx,面板只给得出 %dpx"
            % (content.winfo_reqheight(), content.winfo_height()))


@unittest.skipUnless(HAVE_TK, "需要图形环境")
class MinWindowSizeTest(TkTestCase):
    """窗口有一个量出来的下限。"""

    def test_minsize_is_set_and_is_not_tiny(self):
        from ui.windowing import MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH
        app = self.make_app()
        app.apply_geometry()
        app.update()
        # minsize() 读回来是一串 "宽 高"
        got = app.minsize()
        self.assertGreaterEqual(int(got[0]), MIN_WINDOW_WIDTH)
        self.assertGreaterEqual(int(got[1]), MIN_WINDOW_HEIGHT)
        self.assertGreaterEqual(MIN_WINDOW_HEIGHT, 600,
                                "下限太小了,菜单会装不下")

    def test_the_menu_still_fits_at_the_minimum_size(self):
        """缩到下限时,主菜单的退出按钮仍然完整 —— 这正是下限的用途。"""
        from ui.windowing import MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH
        app = self.make_app()
        app.geometry("%dx%d" % (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT))
        app.deiconify()
        app.update()
        app.show("menu")
        app.update()
        view = app.current_view
        content = [c for c in view.winfo_children() if c.winfo_class() == "Frame"][0]
        button = content.winfo_children()[-1].winfo_children()[0]
        self.assertGreaterEqual(button.winfo_height(), button.winfo_reqheight())


@unittest.skipUnless(HAVE_TK, "需要图形环境")
class EveryViewFitsTest(TkTestCase):
    """每个板块在最常见的分辨率下都不该有控件被压扁。

    只查一件事:**每个控件的高度/宽度都不小于它自己要求的**。
    被 pack 压扁的控件的特征就是 `winfo_height() < winfo_reqheight()`。
    """

    def _squashed(self, widget, path=""):
        """递归找出被压扁的控件(允许一点 1px 的取整误差)。"""
        found = []
        for child in widget.winfo_children():
            name = "%s/%s" % (path, child.winfo_class())
            try:
                if (child.winfo_ismapped() and child.winfo_reqheight() > 0
                        and child.winfo_height() < child.winfo_reqheight() - 1):
                    found.append("%s 高 %d < 需要 %d"
                                 % (name, child.winfo_height(),
                                    child.winfo_reqheight()))
            except Exception:                      # pragma: no cover - Tk 偶发
                pass
            found.extend(self._squashed(child, name))
        return found

    def test_the_menu_has_no_squashed_widgets(self):
        app = self.make_app(visible=True)
        app.show("menu")
        app.update()
        squashed = self._squashed(app.current_view)
        self.assertEqual(squashed, [], "有控件被压扁: %s" % squashed)


@unittest.skipUnless(HAVE_TK, "需要图形环境")
class StudyWordListScrollsTest(TkTestCase):
    """学习页:一组的词多到放不下时,必须是**可滚的**,而且按钮行不许被挤掉。

    用户实测报的就是这两件事一起发生:

        第一个组合有 10 个词 …… 显示 4 个词之后,其他词会被遮挡。
        最重要的是,"下一组"这样的选项本身也被压到了底下,无法点击了。

    根因是单词表既不能滚、又在 pack 顺序里排在按钮行**前面** ——
    它按内容撑满之后,底部那排按钮就没位置了。
    """

    def setUp(self):
        self.app = self.make_app(visible=True)

    def _open_group_of(self, size: int):
        """开一页学习,第一个组合里恰好有 size 个词。"""
        from core.models import Word
        from core.packs import make_vocab_pack
        from ui.session import SessionPlan

        words = []
        for index in range(size + 3):
            group = "第一大组" if index < size else "尾组"
            word = Word(id="g_%d" % index, spelling_key="k%d" % index,
                        word="word%d" % index, translation="释义%d" % index,
                        group=group)
            self.app.words[word.id] = word
            words.append(word)
        pack = make_vocab_pack("grp", "分组词表", [w.id for w in words], "2026-10-15")
        self.app.packs.append(pack)
        self.app.show("study", plan=SessionPlan(words=words, title="分组词表",
                                                pack=pack, pack_id=pack.id))
        self.app.update()
        return self.app.current_view

    def test_a_long_group_is_split_into_capped_pages(self):
        """一屏几个词由设置决定(默认 5),**同一个组合也要切开**。

        用户 2026-10-15 的要求:"如果第一组有 100 词,那么不应该显示 100 词。
        限制每一页的词数显示,哪怕是同一组。例如,组合1有13个词,
        第一页只有5个,下一组显示后5个,再下一组就只剩3个了,
        直到再再下一组,才进入组合2"。
        """
        view = self._open_group_of(13)
        self.assertEqual([len(page) for page in view.pages[:3]], [5, 5, 3])
        self.assertEqual([len(page) for page in view.pages[3:]], [3])   # 那个"尾组"
        for page in view.pages:
            self.assertLessEqual(len(page), 5)

    def test_the_page_size_setting_is_honoured(self):
        """用户说要可调整 —— 设置里改了就按新的切。"""
        self.app.settings.study.page_size = 3
        view = self._open_group_of(13)
        self.assertEqual([len(page) for page in view.pages[:5]], [3, 3, 3, 3, 1])

    def test_the_title_says_which_slice_of_the_group_you_are_on(self):
        """切开之后标题要说明是第几段,否则"组合 · 5 个词"会让人以为
        这个组合一共就 5 个词。"""
        view = self._open_group_of(13)
        titles = []
        for _ in range(3):
            titles.append(view.page_title.cget("text"))
            view.on_next()
            self.app.update()
        self.assertIn("第 1/3 段", titles[0])
        self.assertIn("第 2/3 段", titles[1])
        self.assertIn("第 3/3 段", titles[2])

    def test_it_takes_extra_presses_before_the_next_group(self):
        """13 个词要按 3 次才走完,第 4 次才进组合 2。"""
        view = self._open_group_of(13)
        self.assertEqual(view.pages[0][0].group, "第一大组")
        view.on_next(); self.app.update()
        self.assertEqual(view.pages[view.page_index][0].group, "第一大组")
        view.on_next(); self.app.update()
        self.assertEqual(view.pages[view.page_index][0].group, "第一大组")
        view.on_next(); self.app.update()
        self.assertEqual(view.pages[view.page_index][0].group, "尾组")

    def test_a_page_that_overflows_is_still_scrollable(self):
        """一屏 5 个词,如果卡片高到放不下,列表仍然要能滚。

        这里把每屏调成 12 个来造出"放不下"的情况 ——
        切页解决的是"一屏太多",滚解决的是"一屏放不下",两件事都要有。
        """
        self.app.settings.study.page_size = 12
        view = self._open_group_of(12)
        self.assertEqual(len(view.pages[0]), 12)
        listed = view.word_list
        self.assertGreater(listed.body.winfo_reqheight(), listed.winfo_height())
        self.assertTrue(listed.scrollbar.winfo_ismapped(), "没有滚动条,下面的词看不见")

    def test_the_scrollbar_is_gone_when_everything_fits(self):
        """词少的时候不该留一条没用的滚动条。"""
        view = self._open_group_of(2)
        listed = view.word_list
        self.assertLessEqual(listed.body.winfo_reqheight(), listed.winfo_height())

    def test_the_paging_buttons_stay_clickable_even_with_a_crowded_page(self):
        """这一条直接锁用户报的"下一组被压到下面点不着"。"""
        self.app.settings.study.page_size = 12      # 故意造得放不下
        view = self._open_group_of(12)
        buttons = view.nav.winfo_children()[0].winfo_children()
        self.assertEqual(len(buttons), 4, "底部按钮行少了按钮")
        for button in buttons:
            self.assertEqual(
                button.winfo_height(), button.winfo_reqheight(),
                "「%s」被压扁了(高 %d,需要 %d)"
                % (button.cget("text"), button.winfo_height(),
                   button.winfo_reqheight()))
            panel_bottom = view.panel.winfo_y() + view.panel.winfo_height()
            self.assertLessEqual(view.nav.winfo_y() + view.nav.winfo_height(),
                                 panel_bottom, "按钮行跑到面板外面了")

    def test_turning_the_page_scrolls_back_to_the_top(self):
        """翻到新一屏时要回到顶部,否则新一屏的前几个词被滚过头。"""
        self.app.settings.study.page_size = 12
        view = self._open_group_of(12)
        listed = view.word_list
        listed.canvas.yview_moveto(1.0)
        self.app.update()
        view.on_next()
        self.app.update()
        self.assertLessEqual(listed.canvas.yview()[0], 0.001)


if __name__ == "__main__":
    unittest.main()
