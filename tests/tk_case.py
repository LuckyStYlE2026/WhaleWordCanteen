# -*- coding: utf-8 -*-
"""需要真窗口的测试的公共基类。

**两件必须在导入应用代码之前做完的事**,所以它们写在模块顶层:

1. **把存档目录指向临时目录。** 否则跑一次测试就会往用户真实的
   `save/packs/` 里塞几个测试词包(这一版就发生过:测试跑完,
   用户的词包列表里多出「测试词表」)。`core/paths.py` 认
   `REMEMBER_DATA_DIR`,这里给一个进程级的临时目录。
2. **注册内置实现与界面板块。** `App()` 一构造就要调度器、判分器、
   各个板块的工厂;缺一个就是"启动失败"。以前各测试文件各自
   `setUpClass` 里注册,于是**单独跑一个文件**就会因为别人没跑而全红 ——
   这正是 `python -m unittest tests.test_study_flow` 与整包一起跑
   表现不一致的原因。

做完这两件事之后,基类只提供 `make_app()`:造一个隐藏的窗口。
"""

import atexit
import os
import shutil
import tempfile
import unittest

# ⚠️ 这两行必须在 import ui.* 之前执行(见模块开头的说明)。
_TEMP_ROOT = tempfile.mkdtemp(prefix="remember_test_")
os.environ["REMEMBER_DATA_DIR"] = _TEMP_ROOT
atexit.register(lambda: shutil.rmtree(_TEMP_ROOT, ignore_errors=True))

import tkinter as tk                                 # noqa: E402

from core.builtins import register_builtins          # noqa: E402
from ui.app import App, register_builtin_views       # noqa: E402

register_builtins()
register_builtin_views()

try:
    _ROOT = tk.Tk()
    _ROOT.withdraw()
    HAVE_TK = True
except Exception:                                    # pragma: no cover
    _ROOT = None
    HAVE_TK = False


class TkTestCase(unittest.TestCase):
    """需要真窗口的测试:自动指向临时存档,并且能一键造一个 App。"""

    def setUp(self) -> None:
        # ⚠️ **每个用例都要重新按一次。** 别的测试文件会把
        # REMEMBER_DATA_DIR 弹掉(它们自己 setUp 里设、tearDown 里清),
        # 而 unittest 不保证顺序 —— 一旦它先跑,后面这些用例就会
        # 落到**用户真实的 save/** 里,往词包列表塞测试数据。
        # 这一版就吃过这个亏:跑一次测试,用户的词包多一个。
        os.environ["REMEMBER_DATA_DIR"] = _TEMP_ROOT

    def make_app(self, visible: bool = False) -> App:
        """造一个应用窗口。默认隐藏 —— 测试不该在用户屏幕上弹窗。

        需要真实尺寸的测试(量面板宽度那种)传 visible=True,
        并且记得自己 `app.update()` 让布局跑完。
        """
        app = App()
        if visible:
            app.deiconify()
            app.update()
        else:
            app.withdraw()
        self.addCleanup(self._close_app, app)
        return app

    @staticmethod
    def _close_app(app) -> None:
        try:
            app.destroy()
        except tk.TclError:
            pass          # 已经关掉了(某个用例自己 destroy 过)
