# -*- coding: utf-8 -*-
"""板块路由:切页、记住来源、临时离开一页再原样回来。

**为什么单独一个模块。** 这三件事是同一件事的三个面,而且都不需要认识
App 的其余部分(词库、设置、各项服务)—— 它们只认注册表、容器控件和
"应用上下文"。留在 ui/app.py 里的时候,那一个文件同时装着"全局状态"和
"页面怎么换",而后者恰恰是最容易被改错的一块(见下面那段)。

App 把这几件事各转发成一个同名方法,所以界面层的写法没变。

**关于"临时离开一页"**:对话页就是这么打开的。

    学习页 --push_view("chat")--> 对话页 --pop_view()--> 学习页(原样)

为什么不能像别的跳转那样"重建"上一页:

* 学习页是靠 plan 参数造出来的,而 plan 不记在哪个全局地方 ——
  直接 `show("study")` 不传参数,那一页会认出"没有计划"然后把你送回主菜单
  (**用户实测就是这个现象**);
* 就算把参数重放一遍,学习页的页码、成绩单、进度也会**清零**,
  等于学到一半被踢回第一屏。

所以"临时离开"用的是藏起来(pack_forget)而不是销毁,回来时原样摆回去。
"""

import tkinter as tk
from typing import Any, Optional

from core.registry import registry


class ViewRouter:
    """页面切换。只依赖"应用上下文 + 容器控件 + 注册表"。"""

    def __init__(self, app, container: tk.Misc) -> None:
        self.app = app
        self.container = container
        self.current: Optional[tk.Widget] = None
        self.current_name = ""
        # 被"临时离开"藏起来的那一页。同一时刻只会有一页。
        self._parked: Optional[tk.Widget] = None
        self._parked_name = ""

    # ---- 普通跳转 --------------------------------------------------------

    def show(self, name: str, **kwargs: Any) -> None:
        """切到某个板块。kwargs 会传给板块的 on_enter()。

        两件事都在这一个入口里:

        * **记下上一个板块名**,交给"需要知道来源"的板块(注册表里
          wants_source 为真的那些,目前只有对话页 —— 它靠这个决定开场白)。
        * 页面是通过 `app.show(...)` 跳转的,跳完当前页已经销毁,
          所以来源只能由这里记。
        """
        # ⚠️ 被 push_view 藏起来的那一页此刻还挂在 current 上
        # (push_view 只是把它 pack_forget 了),这里 destroy 会把它拆掉,
        # 回来时就得到一个"控件已不存在"的报错。
        if self.current is not None:
            if self.current is not self._parked:
                self.current.destroy()
            self.current = None

        previous = self.current_name
        view = registry.views.get_factory(name)(self.app)
        view.pack(fill="both", expand=True)
        self.current = view
        self.current_name = name
        if previous and previous != name and registry.views.wants_source(name):
            kwargs.setdefault("source", previous)

        # 板块构造完再喂数据 —— 构造时还不知道自己被传了什么参数,
        # 分成两步能避免在 __init__ 里写一堆 if kwargs
        on_enter = getattr(view, "on_enter", None)
        if callable(on_enter):
            on_enter(**kwargs)

    # ---- 临时离开一页,再原样回来 ----------------------------------------

    def push(self, name: str, **kwargs: Any) -> None:
        """临时切到另一页,把当前页留着以便原样返回。"""
        parked = self.current
        if parked is not None:
            parked.pack_forget()
        self._parked = parked
        self._parked_name = self.current_name
        try:
            self.show(name, **kwargs)
        except BaseException:
            # 切页失败(插件板块抛异常等)就把上一页摆回来,
            # 否则用户会盯着一片空白,而且没有退路
            self.pop()
            raise

    def pop(self) -> bool:
        """回到 push 之前的页面。没有可回的就返回 False。

        返回 False 时调用方自己决定去哪儿(通常是回主菜单)—— 这一层
        不替它做主,因为"没得回"在用户看来应该有个明确的落点。
        """
        parked = self._parked
        if parked is None:
            return False

        if self.current is not None:
            self.current.destroy()
        self._parked = None
        self.current = parked
        self.current_name = self._parked_name or "menu"
        # 摆回放在最后一件事:在这之前任何一步失败,current 都还是 None,
        # 而不是"指着一个已经销毁的控件"
        parked.pack(fill="both", expand=True)
        return True
