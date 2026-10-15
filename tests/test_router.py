# -*- coding: utf-8 -*-
"""页面切换:切页、记住来源、**临时离开一页再原样回来**。

最后那一条是这一组里最要紧的 —— 它对应的 bug 是用户实测报上来的:

    从「开始学习 → 挑词包 → 学习页」点老师进对话页,按返回却回到了主菜单。

原因不在对话页,而在"返回"的实现方式:当时是 `app.show(source)`,
也就是**重建**上一页。而学习页要有 plan 参数才能成立,参数没地方读,
于是它自己认出"没有计划"就把你送回主菜单;就算参数能重放,
页码和成绩单也会清零,等于学到一半被踢回第一屏。

所以改成 push/pop:把上一页**藏起来**,回来时原样摆回去。

⚠️ **这些用例不许动全局注册表。** 第一版把它们注册到
`core.registry.registry` 上再清空重填,结果整包跑测试时把真实板块表
清掉了 —— `App()` 一构造就报"view 扩展点里没有 'a'",而且**单独跑这个
文件却是绿的**(顺序一换就红),排查起来非常费劲。现在用一个本地桩件
替掉 `ui.router` 里的注册表,全局那份一个字都不碰。

这一组需要真窗口(它测的就是 Tk 的控件生命周期),
所以单独一个文件;不需要图形环境的那些在 tests/test_views_registry.py。
"""

import unittest
import tkinter as tk

from core.registry import Slot
from ui import router as router_module
from ui.router import ViewRouter

from .tk_case import HAVE_TK, _ROOT


class FakeView(tk.Frame):
    """一个记着"自己被喂了什么参数"的假板块。"""

    def __init__(self, app) -> None:
        super().__init__(app.container)
        self.app = app
        self.entered = []

    def on_enter(self, **kwargs):
        self.entered.append(kwargs)


class FakeApp(tk.Frame):
    """够 ViewRouter 用就行:一个 container。"""

    def __init__(self, master):
        super().__init__(master)
        self.container = tk.Frame(self)
        self.container.pack()


class StubRegistry:
    """只有 views 一个槽位的注册表桩件。"""

    def __init__(self) -> None:
        self.views = Slot("view")


@unittest.skipUnless(HAVE_TK, "需要图形环境")
class RouterTest(unittest.TestCase):
    """路由本身的行为。用假板块 + 假注册表,完全不牵扯真实界面。"""

    def setUp(self):
        self.stub = StubRegistry()
        for name in ("a", "b", "c", "src"):
            self.stub.views.register(name, lambda app: FakeView(app), is_default=name == "a")
        self.stub.views.mark_source_aware("src")
        # 换掉模块里那一个名字 —— 全局注册表因此毫发无损
        self._real_registry = router_module.registry
        router_module.registry = self.stub

        self.app = FakeApp(_ROOT)
        self.router = ViewRouter(self.app, self.app.container)

    def tearDown(self):
        router_module.registry = self._real_registry
        self.app.destroy()

    def test_show_replaces_the_previous_view(self):
        self.router.show("a")
        first = self.router.current
        self.router.show("b")
        self.assertEqual(self.router.current_name, "b")
        self.assertIsNot(self.router.current, first)
        # 普通跳转是**销毁**上一页 —— 只有 push 才留着
        self.assertFalse(first.winfo_exists())

    def test_push_keeps_the_previous_view_alive(self):
        """push 时上一页必须活着,不然回来就无从谈起。"""
        self.router.show("a")
        parked = self.router.current
        self.router.push("b")
        self.assertEqual(self.router.current_name, "b")
        self.assertTrue(parked.winfo_exists(), "被藏起来的那一页被销毁了")

    def test_pop_restores_the_exact_same_view(self):
        """回来的必须是**同一个对象** —— 不是重建出来的新页面。"""
        self.router.show("a")
        parked = self.router.current
        parked.marker = "学到第 3 屏"          # 模拟"页面上有状态"
        self.router.push("b")
        self.assertTrue(self.router.pop())
        self.assertIs(self.router.current, parked)
        self.assertEqual(self.router.current.marker, "学到第 3 屏")
        self.assertEqual(self.router.current_name, "a")

    def test_pop_destroys_the_page_it_left(self):
        """从对话页回来之后,对话页该被销毁,不该留在内存里。"""
        self.router.show("a")
        self.router.push("b")
        leaving = self.router.current
        self.router.pop()
        self.assertFalse(leaving.winfo_exists())

    def test_pop_without_push_says_so_instead_of_lying(self):
        """没得回时必须如实返回 False —— 调用方据此回主菜单。

        编一个"回主菜单的成功"出来,会让"从主菜单点老师"和"从学习页点老师"
        两条路长得一模一样,以后想区分就没法分了。
        """
        self.router.show("a")
        self.assertFalse(self.router.pop())
        self.assertEqual(self.router.current_name, "a")

    def test_round_trip_can_be_repeated(self):
        """点进去、退出来、再点进去、再退出来 —— 不能只有第一次能用。"""
        self.router.show("a")
        parked = self.router.current
        for _ in range(3):
            self.router.push("b")
            self.assertTrue(self.router.pop())
            self.assertIs(self.router.current, parked)

    def test_show_after_push_does_not_kill_the_parked_view(self):
        """这一条锁的是一个真 bug。

        push 之后被藏起来的那一页**仍然挂在 current 上**(只是没 pack),
        而 show() 开头会销毁 current —— 没防住的话,它会在进入对话页的
        那一刻被拆掉,回来时报"bad window path name"。
        """
        self.router.show("a")
        parked = self.router.current
        self.router.push("b")
        self.assertTrue(parked.winfo_exists())
        self.assertTrue(self.router.pop())

    def test_only_views_that_ask_for_it_get_the_source(self):
        """来源页只传给声明要它的板块(目前只有对话页)。"""
        self.router.show("a")
        self.router.show("src")
        self.assertEqual(self.router.current.entered[-1].get("source"), "a")
        # 没声明的板块收不到这个参数
        self.router.show("b")
        self.assertNotIn("source", self.router.current.entered[-1])


if __name__ == "__main__":
    unittest.main()
