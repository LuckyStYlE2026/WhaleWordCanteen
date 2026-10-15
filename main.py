# -*- coding: utf-8 -*-
"""程序入口。

刻意做得很薄 —— 这里的每一行都在决定"谁的代码先跑"。启动顺序是有讲究的:

  1. register_builtins()   先把内核的默认实现挂上。没有它,后面要 AI 后端、
                           调度器的地方会直接找不到东西。
  2. plugins.load_all()    再让插件有机会覆盖。放在内置之后,是因为想覆盖
                           内置实现就得"后来者居上"。
  3. register_builtin_views()  界面板块也在注册表里,同样不能漏。
  4. App() + mainloop()    最后才建窗口 —— 界面一显示就该是完整的,
                           不该出现"先空白一下再长出菜单"。

任何一步失败都不该弹一个看不懂的 traceback 给用户。所以整体包了 try,
失败时写进 save/logs/ 并弹一个说明窗口。这是单机软件,用户没有终端可看。
"""

import sys
import traceback
from pathlib import Path


def _prepare_import_path() -> None:
    """保证能 import 到 core 和 ui。

    正常运行和 PyInstaller 打包后,sys.path[0] 已经是本文件所在目录。
    但双击 .py 文件时 Windows 有时会把当前工作目录设成别处,
    于是 from core import ... 就找不到了 —— 那种报错对用户来说
    完全无法理解("我什么都没干啊")。这里显式补一次,把这种可能性关掉。
    """
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)


def _report_fatal(error: BaseException) -> None:
    """启动失败时的最后一道防线。

    先写日志(程序自己的目录,用户找得到),再弹窗告诉他去哪儿看。
    弹窗用最朴素的 Tk 消息框 —— 这时候界面层可能根本没建起来,
    不能用任何我们自己写的东西。
    """
    detail = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    try:
        from core import storage
        storage.log_error("启动失败:\n%s" % detail)
    except Exception:
        pass

    message = "程序启动失败。\n\n%s: %s" % (type(error).__name__, error)
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("鲸鱼单词食堂WhaleWordCanteen", message)
        root.destroy()
    except Exception:
        # 连弹窗都起不来(比如没有图形环境),只能打到标准错误
        sys.stderr.write(message + "\n" + detail)


def main() -> int:
    _prepare_import_path()

    try:
        from core import storage
        from core.builtins import register_builtins

        storage.bootstrap()             # 目录和默认设置先就位,后面才敢读写
        register_builtins()             # 内置实现
        _load_plugins()                 # 插件可以覆盖内置

        from ui.app import App, register_builtin_views
        register_builtin_views()        # 界面板块

        app = App()
    except BaseException as error:      # noqa: BLE001 —— 见 _report_fatal 的说明
        _report_fatal(error)
        return 1

    app.mainloop()
    return 0


def _load_plugins() -> None:
    """加载插件。**失败绝不影响启动** —— 这是插件模块的核心承诺。

    单独抽成函数,是为了让 main() 读起来还是四行流程,
    而不是被 try/except 撑成一屏。
    """
    try:
        from core import plugins
        plugins.load_all()
    except Exception as error:
        from core import storage
        storage.log_error("插件加载整体失败(已忽略,继续启动): %s" % error)


if __name__ == "__main__":
    sys.exit(main())
