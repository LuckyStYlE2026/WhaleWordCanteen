# -*- coding: utf-8 -*-
"""词表导出。

导出**同时给两种格式**,因为它们服务的目的不同:

  CSV  (utf-8-sig)  给人看、给 Excel 改。表头用中文,不含内部字段。
  JSON              给程序读。带 id 和学习状态,重新导入时进度不会丢。

只导出 CSV 的话,用户改完再导回来就会发现进度全没了 ——
因为 CSV 里根本没有承载进度的字段。只导出 JSON 的话,用户打不开看。
所以两个都给。

编码必须是 utf-8-sig(带 BOM):中文版 Excel 打开不带 BOM 的 UTF-8 文件时
会按 GBK 解码,整列翻译变成乱码。带 BOM 它才认。
"""

import csv
from pathlib import Path
from typing import List, Optional, Tuple

from .interfaces import WordPackExporter
from .models import Word
from .registry import Registry, registry

# CSV 的表头顺序。与 guige.md 里的字段顺序一致,读起来顺。
CSV_HEADERS = ("单词", "发音", "翻译", "例句", "搭配", "组合")


def _row_from_word(word: Word) -> List[str]:
    return [word.word, word.phonetic, word.translation,
            word.example, word.collocation, word.group]


class CsvExporter(WordPackExporter):
    """导出成 Excel 能直接打开的 CSV。不含 id 与学习状态。"""

    name = "csv"
    title = "CSV(Excel 能直接打开,改完可以再导回来)"

    def export(self, words: List[Word], path: Path) -> Path:
        # 写成 .csv;若调用方传了别的后缀也统一改掉,免得 Excel 不认
        target = path.with_suffix(".csv")
        target.parent.mkdir(parents=True, exist_ok=True)

        # newline="" 是 csv 模块的硬性要求,否则 Windows 上会多出空行
        with open(target, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(CSV_HEADERS)
            for word in words:
                writer.writerow(_row_from_word(word))
        return target


class JsonExporter(WordPackExporter):
    """导出成规范 JSON。带 id 和完整学习状态,是真正无损的那一份。"""

    name = "json"
    title = "JSON(带学习进度,重新导入不会丢)"

    def export(self, words: List[Word], path: Path) -> Path:
        import json

        target = path.with_suffix(".json")
        target.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "version": 1,
            "name": path.stem,
            "words": [word.to_dict() for word in words],
        }
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        return target


def export_both(words: List[Word], base_path: Path) -> List[Path]:
    """一次导出两种内置格式,返回实际写出的文件路径。

    "点一次导出就两种格式都拿到"仍然是默认行为 —— 用户不需要理解
    CSV 和 JSON 的区别。想单独挑一种、或者用插件注册的格式,
    走 export_with / export_all。
    """
    return [CsvExporter().export(words, base_path),
            JsonExporter().export(words, base_path)]


# --------------------------------------------------------------------------
# 走注册表的导出
# --------------------------------------------------------------------------

def export_with(words: List[Word], exporter_name: str, base_path: Path,
                where: Optional[Registry] = None) -> Path:
    """用注册表里的某个导出器写一份词表。

    界面上的"导出成什么格式"列表就是注册表里 exporter 的全部名字,
    所以插件注册进来的格式会和内置的并排出现 —— 不需要界面为插件改代码。
    """
    exporter = (where or registry).get_exporter(exporter_name)
    return exporter.export(words, base_path)


def export_all(words: List[Word], base_path: Path,
               where: Optional[Registry] = None) -> List[Path]:
    """用注册表里**全部**导出器各写一份。

    某个导出器出错时不中断其余的:用户装了五个插件,其中一个写文件时
    崩了,他应该拿到另外四份,而不是一片空白加一个报错。
    """
    target = where or registry
    written: List[Path] = []
    for name in target.exporters.names():
        try:
            written.append(export_with(words, name, base_path, target))
        except OSError:
            continue               # 写不出去的那一份跳过,别的照写
    return written


def available_exporters(where: Optional[Registry] = None) -> List[Tuple[str, str]]:
    """当前可用的导出格式,返回 [(显示给用户的名字, 内部名), ...]。

    注册表里的全部导出器都在这个列表里 —— 内置的和插件注册的并排出现,
    界面不需要知道哪个是谁注册的。构造实例只是为了读它的 title,
    导出器没有构造代价(见 registry.Slot 的说明)。
    """
    target = where or registry
    options: List[Tuple[str, str]] = []
    for name in target.exporters.names():
        try:
            exporter = target.get_exporter(name)
        except KeyError:
            continue
        options.append((getattr(exporter, "title", "") or name, name))
    return options
