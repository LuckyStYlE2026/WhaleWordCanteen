# -*- coding: utf-8 -*-
"""插件发现与加载。

插件就是一个子文件夹,里面放一份清单和一个入口模块:

    plugins/example_export/
    ├── plugin.json      {"name": ..., "version": ..., "api_version": 1, "entry": "__init__"}
    └── __init__.py      def register(registry): ...

**异常隔离是这个文件存在的首要理由。** 插件是别人写的代码,一定会有人写错。
用户装上十个插件,其中一个有语法错误 —— 那个插件应该被跳过并写进日志,
而不是让整个游戏打不开。这是插件系统对用户唯一有意义的保护。
所以下面每一处调用插件的代码都被 try/except Exception 包住,
而且**故意**捕获所有异常(见 _load_one 里的说明)。

第一版不做的事:插件市场、热重载、依赖解析、沙箱。插件是本机用户自己
放进来的代码,信任边界在"用户愿意装它"这一步,靠沙箱给人虚假的安全感
没有意义。
"""

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from . import storage
from .paths import plugins_dir
from .registry import Registry, registry

# 内核与插件约定的接口版本。插件清单里必须声明它。
# 将来接口发生不兼容改动时,把这里 +1,老插件会被明确地拒绝加载,
# 而不是以一种说不清的方式出错。
API_VERSION = 1

MANIFEST_NAME = "plugin.json"

# 清单里 entry 的默认值:表示"入口就是文件夹里的 __init__.py"
DEFAULT_ENTRY = "__init__"


@dataclass
class PluginInfo:
    """一个插件的状态。界面上的插件列表显示的就是它。"""

    name: str
    directory: Path
    version: str = "0.0.0"
    author: str = ""
    description: str = ""
    api_version: int = API_VERSION
    entry: str = DEFAULT_ENTRY
    enabled: bool = True
    loaded: bool = False
    error: str = ""          # 非空表示这个插件出过问题,内容给用户看

    @property
    def status(self) -> str:
        if self.error:
            return "出错"
        if not self.enabled:
            return "已停用"
        return "已启用" if self.loaded else "未加载"


# --------------------------------------------------------------------------
# 发现
# --------------------------------------------------------------------------

def _is_candidate(directory: Path) -> bool:
    """这个子文件夹值不值得看一眼。

    跳过 __pycache__、点开头的隐藏目录、下划线开头的工作目录 ——
    它们不可能是插件,列出来只会让列表变脏。
    """
    name = directory.name
    return (directory.is_dir()
            and not name.startswith(".")
            and not name.startswith("_")
            and name != "__pycache__")


def _read_manifest(directory: Path) -> Optional[dict]:
    """读清单。读不出来返回 None。"""
    manifest_path = directory / MANIFEST_NAME
    if not manifest_path.exists():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


def discover() -> List[PluginInfo]:
    """扫描插件目录,列出所有插件及其状态。

    这里**只读清单,不 import 任何东西** —— 因为界面要随时能刷新这个列表,
    而 import 会执行插件代码。发现和加载分开,是让"看一眼有哪些插件"
    变成一件绝对安全的事。
    """
    root = plugins_dir()
    if not root.exists():
        return []

    enabled_map = storage.load_plugin_state()
    found: List[PluginInfo] = []

    for directory in sorted(root.iterdir()):
        if not _is_candidate(directory):
            continue

        manifest = _read_manifest(directory)
        if manifest is None:
            # 有代码但没清单。多半是插件作者忘了写,给出明确提示 ——
            # 否则他会一直困惑"为什么我的插件不生效"。
            if (directory / "__init__.py").exists() or list(directory.glob("*.py")):
                found.append(PluginInfo(
                    name=directory.name, directory=directory, enabled=False,
                    error="缺少 %s,无法确认这是一个插件" % MANIFEST_NAME))
            continue

        info = PluginInfo(
            name=str(manifest.get("name") or directory.name),
            directory=directory,
            version=str(manifest.get("version", "0.0.0")),
            author=str(manifest.get("author", "")),
            description=str(manifest.get("description", "")),
            api_version=int(manifest.get("api_version", API_VERSION)),
            entry=str(manifest.get("entry", DEFAULT_ENTRY)),
        )
        state = enabled_map.get(info.name) or {}
        info.enabled = bool(state.get("enabled", True))
        found.append(info)

    return found


# --------------------------------------------------------------------------
# 加载
# --------------------------------------------------------------------------

def _build_spec(info: PluginInfo):
    """为插件入口建一个 importlib 规格。

    模块名刻意加前缀,避免和标准库或第三方库重名 ——
    一个叫 "json" 的插件会悄无声息地劫持整个程序。这不是假想问题,
    用户给插件文件夹起什么名字都有可能。
    """
    if info.entry in ("", DEFAULT_ENTRY):
        entry_path = info.directory / "__init__.py"
        is_package = True
    else:
        entry_path = info.directory / info.entry
        if entry_path.suffix != ".py":
            entry_path = entry_path.with_suffix(".py")
        is_package = False

    if not entry_path.exists():
        raise FileNotFoundError("找不到入口文件 %s" % entry_path.name)

    module_name = "remember_plugin_%s" % info.directory.name
    spec = importlib.util.spec_from_file_location(
        module_name, str(entry_path),
        # 让插件文件夹内部的相对 import 也能用(入口是包时才需要)
        submodule_search_locations=[str(info.directory)] if is_package else None,
    )
    if spec is None or spec.loader is None:
        raise ImportError("无法加载 %s" % entry_path.name)
    return spec, module_name


def _load_one(info: PluginInfo, where: Registry) -> PluginInfo:
    """加载一个插件。**无论出什么问题都不会向外抛异常。**

    这里的 `except Exception` 是刻意的、也是本文件最重要的三行代码。
    插件作者可能写错缩进、import 不存在的库、在 register 里除零 ——
    这些都不该让用户打不开自己的背单词软件。
    """
    if info.error:
        return info
    if not info.enabled:
        return info
    if info.api_version != API_VERSION:
        info.error = ("插件要求接口版本 %s,当前内核是 %d,已跳过"
                      % (info.api_version, API_VERSION))
        return info

    try:
        spec, module_name = _build_spec(info)
        module = importlib.util.module_from_spec(spec)
        # 先登记再执行:模块里的相对 import 需要能在 sys.modules 里找到自己
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        register = getattr(module, "register", None)
        if register is None:
            info.error = "入口模块里没有 register(registry) 函数"
            return info
        register(where)
    except Exception as exc:                 # noqa: BLE001 —— 见上方说明
        info.error = "%s: %s" % (type(exc).__name__, exc)
        storage.log_error("插件 %s 加载失败,已跳过: %s" % (info.name, info.error))
        # 失败时把半成品模块从缓存里摘掉,免得别的插件拿到一个残缺的模块
        sys.modules.pop("remember_plugin_%s" % info.directory.name, None)
        return info

    info.loaded = True
    return info


def load_all(where: Optional[Registry] = None) -> List[PluginInfo]:
    """发现并加载全部插件,返回它们的状态。

    单个插件失败不影响其他插件,更不影响启动 —— 这是本模块的核心承诺。
    """
    target = where or registry
    results: List[PluginInfo] = []
    for info in discover():
        results.append(_load_one(info, target))
    return results


def set_enabled(info: PluginInfo, enabled: bool) -> None:
    """记住某个插件是启用还是停用。

    只写状态文件,不即时生效 —— 插件已经注册进注册表了,想真正卸载它
    得重启程序。第一版不做热重载(见模块开头),所以这里诚实地告诉用户
    "重启后生效",而不是假装立刻生效。
    """
    state = storage.load_plugin_state()
    entry = state.get(info.name) or {}
    entry["enabled"] = bool(enabled)
    state[info.name] = entry
    storage.save_plugin_state(state)
    info.enabled = bool(enabled)
