# -*- coding: utf-8 -*-
"""把内置实现注册进注册表。

**内置功能和插件走的是同一条路。** 这不是洁癖 —— 如果内置的判分器直接
被 new 出来用,而插件走注册表,那么注册表那条路就只有插件在走,
一旦哪里对不上,要等到有人写插件时才会暴露。让内置也走同一条路,
接缝处每天都被验证,不会年久失修。

启动顺序:main.py 先调 register_builtins(),再调 plugins.load_all(),
最后才建界面 —— 因为界面要从注册表里取要显示哪些东西。
"""

from typing import Optional

from . import storage
from .ai_client import ApiProvider, NullAIProvider
from .importers import CsvImporter, JsonImporter, LegacyLineImporter, PlainTextImporter
from .interfaces import AIProvider
from .judge import OfflineJudge
from .lines import default_linepack
from .registry import Registry, registry
from .scheduler import EbbinghausScheduler
from .wordpack_export import CsvExporter, JsonExporter

# 内置实现的注册名。写成常量而不是散落的字符串字面量,
# 是为了让"设置里该填什么名字"有唯一出处。
JUDGE_OFFLINE = "offline"
SCHEDULER_EBBINGHAUS = "ebbinghaus"
AI_NULL = "null"
AI_OPENAI_COMPATIBLE = "openai_compatible"

_registered = False


def _make_api_provider() -> AIProvider:
    """构造 OpenAI 兼容后端。

    **为什么从存档里现读设置?** 因为注册表存的是"工厂函数",
    注册发生在读设置之前。而这个后端真正需要参数是**被实例化**的那一刻,
    那时设置早就读好了。现读一次磁盘换来"不用维护一份全局设置副本",
    很划算 —— 而且用户在设置页改完密钥,下次构造就自动生效。
    """
    return ApiProvider(storage.load_settings().ai)


def register_builtins(target: Optional[Registry] = None) -> None:
    """注册全部内置实现。重复调用是安全的(第二次直接返回)。"""
    global _registered
    if _registered and target is None:
        return

    where = target or registry

    # 判分器。离线那个是默认 —— 没配 API 时程序必须照常工作。
    where.register_judge(JUDGE_OFFLINE, OfflineJudge, is_default=True)

    # 复习调度器
    where.register_scheduler(SCHEDULER_EBBINGHAUS, EbbinghausScheduler, is_default=True)

    # AI 后端。空后端是默认,"什么都没配"也是一条正常路径。
    where.register_ai_provider(AI_NULL, NullAIProvider, is_default=True)
    where.register_ai_provider(AI_OPENAI_COMPATIBLE, _make_api_provider)

    # 词表格式。顺序在 detect_format 里另有讲究,这里只是登记名字。
    for importer_class in (JsonImporter, LegacyLineImporter, CsvImporter, PlainTextImporter):
        where.register_importer(importer_class.name, importer_class)
    for exporter_class in (CsvExporter, JsonExporter):
        where.register_exporter(exporter_class.name, exporter_class)

    # 台词包。中文是默认。
    where.register_linepack("default_zh", default_linepack("zh-CN"), is_default=True)
    where.register_linepack("default_en", default_linepack("en"))

    _registered = True
