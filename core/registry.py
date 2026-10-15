# -*- coding: utf-8 -*-
"""扩展点注册表。

内核里所有"可能被替换"的东西都登记在这里:判分器、调度器、词表格式、
AI 后端、台词包、界面板块。

用法:内置实现在启动时注册(见 builtins.py),插件在加载时注册。
两者用的是同一套 API —— 这是刻意的,见 interfaces.py 里的说明。

对外暴露的方法刻意写成 register_xxx / get_xxx / list_xxx 的显式形式,
而不是统一的 register(kind, ...) —— 显式写法让调用处一眼能看出在注册什么,
IDE 也能给出准确的补全和类型提示。
"""

from typing import Callable, Dict, List, Optional

from .interfaces import (
    AIProvider,
    Judge,
    LinePack,
    Scheduler,
    WordPackExporter,
    WordPackImporter,
)


class DuplicateNameError(ValueError):
    """同名扩展点重复注册。

    默认报错而不是静默覆盖 —— 两个插件抢同一个名字是真实的 bug,
    应该在看日志时立刻发现,而不是表现成"某个插件莫名其妙不生效"。
    确实想覆盖时,显式传 replace=True。
    """


class Slot:
    """一个扩展点的登记处。持有 名字 → 工厂 的映射,并记住默认项。

    工厂(factory)可以是类本身,也可以是返回实例的函数。
    统一用工厂而不是实例,是为了让每个扩展点可以懒加载 ——
    没配 API 就不该构造 HTTP 客户端。
    """

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._factories: Dict[str, Callable[[], object]] = {}
        self._default_name: Optional[str] = None
        # 需要知道"用户是从哪一页来的"那些板块。见 register_view 的说明。
        self._source_aware: set = set()

    def register(self, name: str, factory: Callable[[], object],
                 is_default: bool = False, replace: bool = False) -> None:
        if name in self._factories and not replace:
            raise DuplicateNameError(
                "%s 扩展点里已经注册过 %r;确实要覆盖请传 replace=True" % (self.kind, name)
            )
        self._factories[name] = factory
        # 第一个注册的自动成为默认,这样内核不必硬编码一个默认名
        if is_default or self._default_name is None:
            self._default_name = name

    def mark_source_aware(self, name: str) -> None:
        """标记某个板块需要知道来源页(切页时 App 会把它传进 on_enter)。"""
        self._source_aware.add(name)

    def wants_source(self, name: str) -> bool:
        return name in self._source_aware

    def get_factory(self, name: Optional[str] = None) -> Callable[[], object]:
        target = name or self._default_name
        if target is None or target not in self._factories:
            raise KeyError("%s 扩展点里没有 %r" % (self.kind, target))
        return self._factories[target]

    def create(self, name: Optional[str] = None) -> object:
        """实例化一个扩展点。"""
        return self.get_factory(name)()

    def names(self) -> List[str]:
        return sorted(self._factories.keys())

    def default_name(self) -> Optional[str]:
        return self._default_name

    def __contains__(self, name: str) -> bool:
        return name in self._factories


class Registry:
    """全局扩展点注册表。

    全局只有一个实例(见 module 底部的 `registry`),插件通过它注册。
    不做多实例是为了让"注册表"这个概念保持简单 —— 这是个单机单用户的软件,
    没有隔离多套配置的需求。将来真需要了再改成传参,不影响插件写法。
    """

    def __init__(self) -> None:
        self.judges = Slot("judge")
        self.schedulers = Slot("scheduler")
        self.ai_providers = Slot("ai_provider")
        self.importers = Slot("importer")
        self.exporters = Slot("exporter")
        self.linepacks = Slot("linepack")
        # 界面板块。工厂签名是 factory(app) -> 控件 —— 那个 app 参数是
        # ui 层定义的"应用上下文"(主题、词库、各项服务),core 层不认识它,
        # 也不需要认识:注册表只负责把工厂存下来,怎么调用由 ui 层决定。
        self.views = Slot("view")

    # ---- 判分器 ----------------------------------------------------------
    def register_judge(self, name: str, factory: Callable[[], Judge],
                       is_default: bool = False, replace: bool = False) -> None:
        self.judges.register(name, factory, is_default, replace)

    def get_judge(self, name: Optional[str] = None) -> Judge:
        return self.judges.create(name)  # type: ignore[return-value]

    # ---- 复习调度器 ------------------------------------------------------
    def register_scheduler(self, name: str, factory: Callable[[], Scheduler],
                           is_default: bool = False, replace: bool = False) -> None:
        self.schedulers.register(name, factory, is_default, replace)

    def get_scheduler(self, name: Optional[str] = None) -> Scheduler:
        return self.schedulers.create(name)  # type: ignore[return-value]

    # ---- AI 后端 ---------------------------------------------------------
    def register_ai_provider(self, name: str, factory: Callable[[], AIProvider],
                             is_default: bool = False, replace: bool = False) -> None:
        self.ai_providers.register(name, factory, is_default, replace)

    def get_ai_provider(self, name: Optional[str] = None) -> AIProvider:
        return self.ai_providers.create(name)  # type: ignore[return-value]

    # ---- 词表导入 / 导出 -------------------------------------------------
    def register_importer(self, name: str, importer_cls: type,
                          is_default: bool = False, replace: bool = False) -> None:
        self.importers.register(name, importer_cls, is_default, replace)

    def get_importer(self, name: Optional[str] = None) -> WordPackImporter:
        return self.importers.create(name)  # type: ignore[return-value]

    def register_exporter(self, name: str, exporter_cls: type,
                          is_default: bool = False, replace: bool = False) -> None:
        self.exporters.register(name, exporter_cls, is_default, replace)

    def get_exporter(self, name: Optional[str] = None) -> WordPackExporter:
        return self.exporters.create(name)  # type: ignore[return-value]

    # ---- 台词包 ----------------------------------------------------------
    def register_linepack(self, name: str, pack: LinePack,
                          is_default: bool = False, replace: bool = False) -> None:
        # 台词包是纯数据,没有构造代价,所以这里直接存实例而不是工厂。
        # 传一个 lambda 包一层,让 Slot 的接口保持一致,不必为它写特例。
        self.linepacks.register(name, lambda: pack, is_default, replace)

    def get_linepack(self, name: Optional[str] = None) -> LinePack:
        return self.linepacks.create(name)  # type: ignore[return-value]

    # ---- 界面板块 --------------------------------------------------------
    def register_view(self, name: str, factory: Callable[..., object],
                      is_default: bool = False, replace: bool = False,
                      wants_source: bool = False) -> None:
        """注册一个界面板块。factory 会被调用为 factory(app)。

        app 的类型由 ui 层定义(见 ui/app.py 的 App),core 只把它当
        object 传递 —— 这样注册表能在不认识 Tk 的前提下服务于界面。

        wants_source=True 表示**这个板块需要知道用户是从哪一页跳过来的**
        (目前只有对话页:它靠这个把「返回」落回原地)。
        写成注册时的一个声明,而不是在 App 里 `if name == "chat"` ——
        后者会让路由层认识某一页的名字,插件想做一个"从哪来回哪去"的
        页面时也无处声明。
        """
        self.views.register(name, factory, is_default, replace)
        if wants_source:
            self.views.mark_source_aware(name)


# 全局单例。插件直接 from core.registry import registry 即可注册。
registry = Registry()
