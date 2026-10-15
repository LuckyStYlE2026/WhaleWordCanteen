# -*- coding: utf-8 -*-
"""路径解析。所有"文件放哪儿"的问题都在这里回答。

单独成一个模块,是因为路径解析有一个很隐蔽的坑值得集中说明:

打包成 exe 之后,程序资源被解压到一个临时目录(sys._MEIPASS),
但**用户的存档绝对不能存到那里** —— 那是临时的,进程退出就没了,
用户会发现"我明明存了,怎么重启就没了"。所以这里严格区分两个根:

  resource_root()  只读资源(图片、内置模板)。打包后在 _MEIPASS 里。
  data_root()      用户可写数据(save/)。始终在 exe 或 main.py 旁边。

其余函数都是在根目录上拼子路径,不涉及别的逻辑。
"""

import os
import sys
import tempfile
from pathlib import Path

# 用户可见的数据目录名。刻意用英文而不是中文 ——
# 中文目录名在某些 Windows 环境的命令行、打包工具和压缩软件里会出现
# 编码不一致,表现成"文件明明在,程序却说找不到"。这个问题很难排查,
# 而避免它只需要一开始就取英文名。界面上显示给用户的名字仍是中文(见 i18n)。
ASSETS_DIR_NAME = "assets"          # 美术素材:背景、立绘、UI 图
WORDLISTS_DIR_NAME = "wordlists"    # 词表导入 / 导出的默认落点


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打出来的 exe 里。"""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """只读资源的根目录。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))
    # 本文件在 game/core/paths.py,往上两层就是 game/
    return Path(__file__).resolve().parent.parent


def _running_under_tests() -> bool:
    """当前进程是不是在跑单元测试。

    ⚠️ **`sys.argv[0]` 在 `python -m unittest` 下不是路径**,而是
    `'python.exe -m unittest'` 这样一整条命令 —— 所以只能按"里面有没有
    unittest 这个词"判断,不能拿 basename 去比。第一版就是按 basename 比的,
    兜底静默失效,测试照样往真实存档里写。

    刻意不看"有没有 import unittest":那太容易误判(任何库都可能碰过它),
    而这个判断的后果是"把存档换个地方",误判的代价很大。
    """
    entry = (sys.argv[0] or "").lower()
    return "unittest" in entry or "pytest" in entry


def data_root() -> Path:
    """用户可写数据的根目录。

    三种情况,优先级从高到低:

    1. **环境变量 REMEMBER_DATA_DIR 覆盖它。** 两个用处:把存档放到 U 盘或
       网盘目录做便携版;单元测试指向临时目录。
    2. **跑测试且没人指定目录时,落到一个临时目录。** 这一条是**兜底**,
       代价很小但挡掉一类很难看的事故:测试代码一旦忘了隔离,
       就会往用户真实的 `save/` 里塞测试词包和测试单词 ——
       这一版真的发生过(跑一次测试,用户的词包列表多一个)。
       兜底之后,"哪个测试忘了隔离"最多是它自己的断言不成立,
       不会再动用户的存档。
    3. 正常运行时在 exe 或 main.py 旁边。
    """
    override = os.environ.get("REMEMBER_DATA_DIR")
    if override:
        return Path(override).resolve()
    if _running_under_tests():
        # 每个进程一个固定目录(不用 mkdtemp 是为了让同一进程里的多次
        # 调用拿到同一个根 —— 否则每次调用都在换地方,测试反而更难写)
        fallback = Path(tempfile.gettempdir()) / "remember_untracked_test_data"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback.resolve()
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


# ---- save/ 下的各项 ------------------------------------------------------

def save_dir() -> Path:
    return data_root() / "save"


def settings_path() -> Path:
    """用户实际使用的设置文件。"""
    return save_dir() / "settings.json"


def words_path() -> Path:
    """单词库 —— 每词的学习状态都存在这里。"""
    return save_dir() / "words_index.json"


def ai_cache_path() -> Path:
    """AI 判分缓存。同一个错答只花一次钱,靠的就是它。"""
    return save_dir() / "ai_cache.json"


def characters_path() -> Path:
    return save_dir() / "characters.json"


def plugins_state_path() -> Path:
    return save_dir() / "plugins.json"


def packs_dir() -> Path:
    return save_dir() / "packs"


def logs_dir() -> Path:
    return save_dir() / "logs"


def chats_dir() -> Path:
    """保存下来的对话记录。

    单独一个目录(而不是塞进 save/ 根下):这是**会长大**的东西 ——
    用户每存一次就多一份。混在根目录里会让 save/ 越来越难看清
    "哪些是程序状态、哪些是我的记录"。
    """
    return save_dir() / "chats"


# ---- 其他可写目录 --------------------------------------------------------

def plugins_dir() -> Path:
    """插件目录。开发时在 game/plugins,打包后同样在 exe 旁边。"""
    return data_root() / "plugins"


# ---- 只读目录 ------------------------------------------------------------

def settings_template_path() -> Path:
    """仓库里那份不含密钥的设置模板。"""
    return resource_root() / "settings.json"


def image_dir() -> Path:
    """用户自备的美术素材目录。"""
    return resource_root() / ASSETS_DIR_NAME


def wordlist_dir() -> Path:
    """词表导入/导出的默认落点。"""
    return resource_root() / WORDLISTS_DIR_NAME
