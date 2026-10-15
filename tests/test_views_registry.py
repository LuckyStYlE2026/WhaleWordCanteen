# -*- coding: utf-8 -*-
"""界面板块注册表的测试。

这一条比它看起来重要:**板块名是和插件共用的契约**。插件可以
`replace=True` 覆盖掉 "curve" 这个板块,所以注册名一旦写错或者漏注册,
插件会以为自己接上了、其实被静默忽略 —— 那种 bug 在界面上看不出来。

这里只验证"名字能解析到类",不构造真窗口 —— 构造窗口的活交给
启动时的无头渲染冒烟(没必要让单元测试去创建 Tk 根窗口)。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.registry import registry                       # noqa: E402
from ui.views import _BUILTINS, register_all             # noqa: E402


class TestBuiltinViews(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        register_all(registry)

    def test_every_builtin_name_resolves_to_a_class(self):
        for name, module_name, class_name, _source in _BUILTINS:
            factory = registry.views.get_factory(name)
            self.assertTrue(callable(factory), "%s 应该能取到工厂" % name)
            self.assertEqual(getattr(factory, "__name__", ""), class_name,
                             "%s 解析出来的不是 %s(模块 %s)"
                             % (name, class_name, module_name))

    def test_the_two_pick_pages_are_registered(self):
        """二级页在这里,是为了它们和插件共用注册通道,不是特例。"""
        self.assertIn("study_pick", registry.views.names())
        self.assertIn("exam_pick", registry.views.names())

    def test_menu_is_the_default_view(self):
        self.assertEqual(registry.views.default_name(), "menu")
        self.assertEqual(registry.views.get_factory().__name__, "MenuView")

    def test_registering_twice_is_safe(self):
        """插件加载完可能再调一次;重复注册会抛异常,表现成"启动失败"。"""
        before = registry.views.names()
        register_all(registry)
        self.assertEqual(registry.views.names(), before)

    def test_names_are_unique(self):
        # 每条是 (板块名, 模块名, 类名, 是否需要来源页),这里只看名字
        names = [entry[0] for entry in _BUILTINS]
        self.assertEqual(len(names), len(set(names)))

    def test_only_the_chat_page_asks_for_its_source(self):
        """目前只有对话页需要知道"从哪一页来的"(它要把返回落回原地)。

        这条不是洁癖:多标一个页面会让 App 给它传一个它不认的参数,
        少标一个会让"返回"失灵 —— 两种情况都该在测试里现形。
        """
        aware = [entry[0] for entry in _BUILTINS if entry[3]]
        self.assertEqual(aware, ["chat"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
