# -*- coding: utf-8 -*-
"""本地文件读写。**这是唯一允许碰 save/ 目录的模块。**

其他模块想存东西,一律调用这里的函数。好处是将来若把存档换成 SQLite、
或者加上加密、云同步,只需要改这一个文件,界面层一行都不用动。

路径怎么定的见 paths.py —— 那里解释了为什么"只读资源"和"用户存档"
必须是两个不同的根目录。这里只负责读写,不负责决定放哪儿。

写入策略一律是"先写临时文件再改名"(见 _atomic_write_json),
读取策略一律是"出错就返回空,绝不抛异常"。对一个单机软件来说,
存档损坏时能继续启动(大不了从头开始)比精确报错重要得多。
"""

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import Settings, default_settings_dict
from .models import Word
from .pack_edit import dedupe_word_ids
from .packs import WordPack
# data_root 也经 storage.data_root 被使用(测试的环境变量用例);
# 其余路径函数的调用方都直接 import core.paths,这里不再转手。
from .paths import (
    ai_cache_path,
    characters_path,
    data_root,
    image_dir,
    logs_dir,
    packs_dir,
    plugins_dir,
    plugins_state_path,
    save_dir,
    settings_path,
    settings_template_path,
    wordlist_dir,
    words_path,
)


# --------------------------------------------------------------------------
# 基础读写
# --------------------------------------------------------------------------

def _atomic_write_json(path: Path, data: Any) -> None:
    """原子地写一个 JSON 文件。

    先写临时文件再 os.replace 改名。os.replace 在 Windows/NTFS 上是原子的,
    所以不会出现"写到一半断电,存档全毁"的情况 —— 要么是旧的,要么是新的。

    ensure_ascii=False 让中文在文件里保持可读。存档是给用户看得懂的,
    存成 \\u5927\\u6c14\\u5c42 就失去意义了。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(str(tmp), str(path))


def _read_json(path: Path) -> Optional[Any]:
    """读一个 JSON 文件。文件不存在或内容损坏都返回 None,不抛异常。

    存档损坏时程序应该还能启动,而不是直接崩溃。
    这是本地单机软件最重要的健壮性要求之一。
    """
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (ValueError, OSError) as exc:
        log_error("读取 %s 失败: %s" % (path, exc))
        return None


def log_error(message: str) -> None:
    """把一个错误追加到 save/logs/errors.log。

    插件出错、存档损坏、API 异常都走这里。写日志本身再失败就放弃 ——
    记日志不该成为新的崩溃来源。
    """
    try:
        logs_dir().mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(logs_dir() / "errors.log", "a", encoding="utf-8") as handle:
            handle.write("[%s] %s\n" % (stamp, message))
    except OSError:
        pass


# --------------------------------------------------------------------------
# 首次运行
# --------------------------------------------------------------------------

def bootstrap() -> None:
    """首次运行时把目录结构建好。可以重复调用,已存在的不会被覆盖。"""
    save_dir().mkdir(parents=True, exist_ok=True)
    packs_dir().mkdir(parents=True, exist_ok=True)
    logs_dir().mkdir(parents=True, exist_ok=True)
    plugins_dir().mkdir(parents=True, exist_ok=True)
    for folder in (image_dir() / "ui", image_dir() / "ai", wordlist_dir()):
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            # 打包后的资源目录可能不可写(比如装到了 Program Files),
            # 这不是致命问题 —— 只读资源本来就只需要能读。
            pass

    # 用户设置不存在时,从模板复制一份;模板也没有就用代码里的默认值
    if not settings_path().exists():
        template = _read_json(settings_template_path())
        data = template if isinstance(template, dict) else default_settings_dict()
        _atomic_write_json(settings_path(), Settings.from_dict(data).to_dict())


# --------------------------------------------------------------------------
# 设置
# --------------------------------------------------------------------------

def load_settings() -> Settings:
    """读设置。文件缺失或损坏时回退到默认值,保证程序总能启动。"""
    data = _read_json(settings_path())
    if not isinstance(data, dict):
        data = _read_json(settings_template_path())
    if not isinstance(data, dict):
        return Settings()
    return Settings.from_dict(data)


def save_settings(settings: Settings) -> None:
    _atomic_write_json(settings_path(), settings.to_dict())


# --------------------------------------------------------------------------
# 单词库(权威状态源)
# --------------------------------------------------------------------------

def load_words() -> Dict[str, Word]:
    """读出全部单词,返回 {单词id: Word}。

    返回字典而不是列表,因为绝大多数操作都是按 id 找词。
    """
    data = _read_json(words_path())
    if not isinstance(data, dict):
        return {}
    raw_words = data.get("words")
    if not isinstance(raw_words, dict):
        return {}

    words: Dict[str, Word] = {}
    for word_id, raw in raw_words.items():
        try:
            words[word_id] = Word.from_dict(raw)
        except (KeyError, TypeError, ValueError) as exc:
            # 单个词条损坏不该带走整个词库,跳过并记日志
            log_error("词条 %s 解析失败,已跳过: %s" % (word_id, exc))
    return words


def save_words(words: Dict[str, Word]) -> None:
    payload = {
        "version": 1,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "words": {word_id: word.to_dict() for word_id, word in words.items()},
    }
    _atomic_write_json(words_path(), payload)


# --------------------------------------------------------------------------
# 词包
# --------------------------------------------------------------------------

def pack_path(pack_id: str) -> Path:
    return packs_dir() / ("%s.json" % pack_id)


def new_pack_id(kind: str, when: Optional[date] = None) -> str:
    """生成词包 id,形如 pack_20261012_001。

    同一天多次学习会递增编号,所以先扫一遍已有文件再定序号。
    """
    day = (when or date.today()).strftime("%Y%m%d")
    prefix = "pack_%s_" % day
    used = 0
    if packs_dir().exists():
        for existing in packs_dir().glob("%s*.json" % prefix):
            tail = existing.stem[len(prefix):]
            if tail.isdigit():
                used = max(used, int(tail))
    return "%s%03d" % (prefix, used + 1)


def save_pack(pack: WordPack) -> None:
    _atomic_write_json(pack_path(pack.id), pack.to_dict())


def delete_pack(pack_id: str) -> None:
    """删掉一个词包文件。

    存盘是把词包写进磁盘,所以"删词包"必须真的把文件删掉 ——
    只从内存列表里移除的话,下次 list_packs() 一读盘,它又回来了,
    表现成"我明明删了,重启之后它还在"。文件不存在时静默放过,
    这样重复删除是安全的(和 new_pack_id 的幂等口味一致)。
    """
    try:
        pack_path(pack_id).unlink()
    except FileNotFoundError:
        return


def load_pack(pack_id: str) -> Optional[WordPack]:
    data = _read_json(pack_path(pack_id))
    if not isinstance(data, dict):
        return None
    try:
        return WordPack.from_dict(data)
    except (KeyError, TypeError, ValueError) as exc:
        log_error("词包 %s 解析失败: %s" % (pack_id, exc))
        return None


def list_packs() -> List[WordPack]:
    """列出全部词包,按创建日期从新到旧。"""
    if not packs_dir().exists():
        return []
    packs: List[WordPack] = []
    for path in packs_dir().glob("pack_*.json"):
        data = _read_json(path)
        if not isinstance(data, dict):
            continue
        try:
            pack = WordPack.from_dict(data)
        except (KeyError, TypeError, ValueError) as exc:
            log_error("词包文件 %s 解析失败,已跳过: %s" % (path.name, exc))
            continue
        # 顺手修掉存档里的重复 id。读的时候修是**唯一**能覆盖老存档的地方:
        # 用户的包可能已经带着重复(见 core/pack_edit.dedupe_word_ids 那段
        # 说明),不在这里收拾,那个包会永远显示成虚高的词数。
        removed = dedupe_word_ids(pack)
        if removed:
            log_error("词包 %s 里有 %d 个重复 id,已自动去重(不影响学习状态)"
                      % (pack.id, removed))
            save_pack(pack)
        packs.append(pack)
    packs.sort(key=lambda pack: (pack.created_at, pack.id), reverse=True)
    return packs


# --------------------------------------------------------------------------
# AI 判分缓存
# --------------------------------------------------------------------------

def load_ai_cache() -> Dict[str, Any]:
    """读 AI 判分缓存。

    键是"单词id|归一化后的答案",值是判分结果。
    有了它,同一个错误答案答第二次就不必再花钱问一遍模型。
    """
    data = _read_json(ai_cache_path())
    return data if isinstance(data, dict) else {}


def save_ai_cache(cache: Dict[str, Any]) -> None:
    _atomic_write_json(ai_cache_path(), cache)


# --------------------------------------------------------------------------
# AI 形象 / 人设,以及插件状态
# --------------------------------------------------------------------------

def load_characters_data() -> Optional[Any]:
    """读 AI 形象/人设的原始数据。解析交给 characters.py,这里只管 IO。"""
    return _read_json(characters_path())


def save_characters_data(data: Any) -> None:
    _atomic_write_json(characters_path(), data)


def load_plugin_state() -> Dict[str, Any]:
    """读插件启用列表。结构:{插件名: {"enabled": true}}"""
    data = _read_json(plugins_state_path())
    return data if isinstance(data, dict) else {}


def save_plugin_state(state: Dict[str, Any]) -> None:
    _atomic_write_json(plugins_state_path(), state)
