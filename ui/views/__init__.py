# -*- coding: utf-8 -*-
"""内置界面板块的注册。

和 core/builtins.py 是一个套路:内置板块也走注册表,不搞第二条路。
这样"插件能不能替换某个界面"和"内置界面怎么挂上去的"是同一个答案。

板块名是和插件共用的契约,一旦发布就不能随便改名 ——
插件可能用 `replace=True` 覆盖掉 "curve" 这个板块,
改名会让它的覆盖悄悄失效。所以名字用简洁的英文单词,别带版本号。
"""

from typing import List, Tuple

# (板块名, 模块名, 类名, 是否需要知道"从哪一页来的")
# 用字符串而不是 import 进来的类,是为了让这份清单不用逐个导入 ——
# 每加一页就要在文件开头加一行 import,这行 import 忘写了只会得到
# 一个启动时的 ImportError,而不是什么有用的提示。
#
# 最后一列只有对话页是 True:它靠这个把「返回」落回你进来的那一页。
_BUILTINS: List[Tuple[str, str, str, bool]] = [
    ("menu", "menu", "MenuView", False),
    ("start", "start", "StartView", False),
    # 「开始」的二级页:选完学习还是考试之后,在这一步挑词包。
    # 两条注册名而不是一条带参数的页面,是因为换主题时 App 会**不带参数**
    # 重进当前页,靠参数区分模式的页面会在那一刻静默变成另一页。
    ("study_pick", "study_pick", "StudyPickView", False),
    ("exam_pick", "exam_pick", "ExamPickView", False),
    ("study", "study", "StudyView", False),
    ("exam", "exam", "ExamView", False),
    # 对话页:点画面上的老师进来。它不在主菜单的卡片里 ——
    # 入口就是"老师本人",这也正是它能被发现的方式(鼠标移上去会变小手)。
    ("chat", "chat", "ChatView", True),
    ("wordset", "wordset", "WordSetView", False),
    # 词包内编辑:从词包列表「打开」进来,不是主菜单的一级入口,
    # 但和 wordset 走同一套注册,免得它需要第二条加载路径
    ("wordpack_editor", "wordpack_editor", "WordPackEditorView", False),
    ("curve", "curve", "CurveView", False),
    ("ai_select", "ai_select", "AiSelectView", False),
    ("settings", "settings_view", "SettingsView", False),
]

# 和 core/builtins.py 同样的理由:重复调用必须安全。
# 插件加载完之后如果再调一次 register_all,不加这个守卫就会抛
# DuplicateNameError,而那会表现成"启动失败",排查起来毫无头绪。
_registered = False


def register_all(target) -> None:
    """把内置板块注册进注册表。重复调用不会重复注册。"""
    global _registered
    if _registered:
        return
    _registered = True

    from importlib import import_module

    for name, module_name, class_name, wants_source in _BUILTINS:
        module = import_module("." + module_name, __name__)
        view_class = getattr(module, class_name)
        # 第一个注册的自动成为默认板块 —— 内核不必硬编码"启动进哪一页"
        target.register_view(name, view_class, is_default=(name == "menu"),
                             wants_source=wants_source)
