# -*- coding: utf-8 -*-
"""词表导入的对外入口。

这个文件现在只做两件事:
  1. 挑一个能读懂这份文件的读取器(detect_format / import_file)
  2. 把读出来的词条合并进词库(apply_import)

具体的格式解析在 importers.py,文本清洗工具在 textio.py。
这里顺手把它们重新导出,所以调用方只 import 这一个模块就够了 ——
"从哪个文件导入词表"这件事,不应该让使用者记住三个模块名。
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
from datetime import date

from .interfaces import ImportResult, RawWord, RowError
from .models import Word
from .packs import WordPack, make_vocab_pack
from .registry import Registry, registry
from .scheduler import initial_state

# 重新导出,保持 core.wordpack_import 是导入功能唯一的对外名字
from .importers import (              # noqa: F401
    CsvImporter,
    JsonImporter,
    LegacyLineImporter,
    PlainTextImporter,
    parse_plain_lines,
)
from .textio import new_word_id, spelling_key              # noqa: F401


# 内置导入器的尝试顺序,**顺序不能随便调**:
#   json   最先,因为它有严格校验(真的解析一次),不会误领别的格式
#   legacy 次之,它的特征很明确(以 { 开头且含"单词")
#   csv    再次
#   plain  最后兜底,它什么都认,放前面会抢走所有文件
IMPORTER_ORDER = ("json", "legacy_line", "csv")
CATCH_ALL_IMPORTER = "plain"

# 兜底名单:直接使用 core(单元测试、脚本)时注册表里可能什么都没登记,
# 那时退回这几个类。正常运行时注册表里一定有它们 —— 见 builtins.py。
IMPORTER_CLASSES = (JsonImporter, LegacyLineImporter, CsvImporter, PlainTextImporter)


def _importer_names(target: Registry) -> List[str]:
    """按尝试顺序列出可用的导入器名字。

    内置那三个的顺序写死在 IMPORTER_ORDER 里(理由见上)。插件注册进来的
    导入器插在它们之后、兜底的 plain 之前 —— plain 什么都认,
    排在它后面等于永远不会被问到。

    插件之间的相对顺序按名字排序(Registry 的 names() 就是排好序的),
    所以同一份插件在两个机器上的行为一致,不会今天认成 A 格式明天认成 B。
    """
    slot = target.importers
    known = [name for name in IMPORTER_ORDER if name in slot]
    catch_all = [CATCH_ALL_IMPORTER] if CATCH_ALL_IMPORTER in slot else []
    plugins = [name for name in slot.names()
               if name not in known and name not in catch_all]
    return known + plugins + catch_all


def _candidates(where: Optional[Registry] = None) -> List[object]:
    """按尝试顺序给出导入器**实例**。"""
    target = where or registry
    if not target.importers.names():
        return [importer_class() for importer_class in IMPORTER_CLASSES]

    instances: List[object] = []
    for name in _importer_names(target):
        try:
            instances.append(target.get_importer(name))
        except KeyError:
            continue                    # 名字在上一步之后被摘掉了,跳过
    return instances


def detect_format(path: Path, where: Optional[Registry] = None) -> Optional[object]:
    """挑一个能处理这个文件的导入器。都不认就返回 None。

    候选来自注册表,所以插件注册的导入格式能和内置格式平起平坐 ——
    界面不需要为插件改一行代码。

    can_handle 里会读文件,所以这里要接住 OSError(文件被占用、
    权限不足等),不能让"某个读取器读不了"变成"整个导入崩掉"。
    """
    for importer in _candidates(where):
        try:
            if importer.can_handle(path):
                return importer
        except OSError:
            continue
    return None


def import_file(path: Path, where: Optional[Registry] = None) -> ImportResult:
    """导入一个文件,自动识别格式。"""
    importer = detect_format(path, where)
    if importer is None:
        result = ImportResult()
        result.errors.append(RowError(0, path.name, "无法识别的文件格式"))
        return result
    return importer.load(path)


def apply_import(index: Dict[str, Word], raw_words: List[RawWord],
                 pack_id: str = "", today: Optional[date] = None,
                 return_ids: bool = False
                 ) -> Union[Dict[str, int], Tuple[Dict[str, int], List[str]]]:
    """把导入的原始词条合并进词库,返回统计。

    合并规则(这是整个导入逻辑里最要紧的一条):
      词库里已经有这个拼写 → **复用原 id,只更新释义文字,保留学习状态**
      词库里没有           → 新建,分配 id 和初始状态

    所以重复导入同一份词表不会毁掉进度,用户也可以放心地
    "导入了发现少两个词,补上再导一次"。

    return_ids=True 时额外返回这一批词的 id 列表(新建的 + 命中已有更新
    的都算,顺序与 raw_words 一致,跳过的不在里面)。导入即建包时靠它
    把词挂到词包上。默认 False,老调用照旧只拿 stats 字典。
    """
    when = today or date.today()
    by_spelling = {word.spelling_key: word for word in index.values()}

    stats = {"added": 0, "updated": 0, "skipped": 0}
    word_ids: List[str] = []
    for raw in raw_words:
        key = spelling_key(raw.word)
        if not key:
            stats["skipped"] += 1
            continue

        existing = by_spelling.get(key)
        if existing is not None:
            _update_text_fields(existing, raw, pack_id)
            stats["updated"] += 1
            word_ids.append(existing.id)
            continue

        word = _create_word(raw, key, when, pack_id)
        index[word.id] = word
        by_spelling[key] = word
        stats["added"] += 1
        word_ids.append(word.id)

    if return_ids:
        return stats, word_ids
    return stats


def import_as_pack(index: Dict[str, Word], path: Path, pack_id: str,
                   today: Optional[date] = None,
                   where: Optional[Registry] = None
                   ) -> Tuple[WordPack, ImportResult, Dict[str, int]]:
    """导入一个文件并直接建成一个词表包。

    和 apply_import 的区别:这里把"这一份文件 = 一个词表包"也记下来 ——
    pack_id 由调用方传进来(因为多文件导入时要逐个存盘才不会撞 id,
    见 ui/views/wordset.py 的循环)。词包的 word_ids 指向刚加入/更新的词。

    重复导入同一份文件会建出**第二个词表包**,但词的进度仍保留
    (同拼写复用 id,见 apply_import 的合并规则)。

    返回 (词表包, 原始读取结果含 errors, 统计)。即使没读到任何词也返回 ——
    调用方自己决定要不要把空包丢掉。
    """
    when = today or date.today()
    result = import_file(path, where)
    stats, word_ids = apply_import(index, result.words, pack_id=pack_id,
                                   today=when, return_ids=True)
    pack = make_vocab_pack(pack_id, path.stem, word_ids, when.isoformat())
    return pack, result, stats


def _update_text_fields(word: Word, raw: RawWord, pack_id: str) -> None:
    """只覆盖文字字段。state / id / created_at 一律不动 ——
    这就是"重新导入不丢进度"的实现点。"""
    word.word = raw.word
    word.translation = raw.translation
    word.phonetic = raw.phonetic
    word.example = raw.example
    word.collocation = raw.collocation
    word.group = raw.group
    if pack_id and pack_id not in word.source_packs:
        word.source_packs.append(pack_id)


def _create_word(raw: RawWord, key: str, when: date, pack_id: str) -> Word:
    word = Word(
        id=new_word_id(),
        spelling_key=key,
        word=raw.word,
        translation=raw.translation,
        phonetic=raw.phonetic,
        example=raw.example,
        collocation=raw.collocation,
        group=raw.group,
        created_at=when.isoformat(),
        source_packs=[pack_id] if pack_id else [],
    )
    word.state = initial_state(when)
    return word
