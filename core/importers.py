# -*- coding: utf-8 -*-
"""四种词表格式的读取器。

设计原则是**尽量都能吃**:用户手头有什么文件,就让他用什么文件,
不要逼人家先转格式。所以这里既有规范的 JSON,也有从 Excel 另存的 CSV,
还有 guige.md 里示范的那种一行一条的老写法,最后一个兜底读纯文本。

每个类都要回答两个问题:
  can_handle(path)  这个文件归我管吗?(认领之前可以先看一眼内容)
  load(path)        归我管的话,怎么读成一串 RawWord

调用方不直接挑类,统一走 wordpack_import.detect_format —— 顺序有讲究,
见那个文件里的说明。
"""

import csv
import io
import json
from pathlib import Path

from .interfaces import ImportResult, RawWord, RowError, WordPackImporter
from .textio import (
    COLUMN_ALIASES,
    clean_field,
    map_columns,
    raw_from_mapping,
    read_text,
    row_has_content,
    split_outside_quotes,
    split_word_and_translation,
    strip_quotes,
)


class JsonImporter(WordPackImporter):
    """规范 JSON 格式。本程序导出的文件也用它读回来。"""

    name = "json"

    def can_handle(self, path: Path) -> bool:
        if path.suffix.lower() == ".json":
            return True
        try:
            text = read_text(path).lstrip()
        except OSError:
            return False
        if text[:1] not in ("{", "["):
            return False
        # 老式的一行一条格式({单词: "…"})也以 { 开头,
        # 光看首字符区分不了。所以这里真的解析一次:
        # 能解析的才是 JSON,解析不了的就让给 LegacyLineImporter。
        try:
            json.loads(text)
        except ValueError:
            return False
        return True

    def load(self, path: Path) -> ImportResult:
        result = ImportResult(format="json")
        try:
            payload = json.loads(read_text(path))
        except (ValueError, OSError) as exc:
            result.errors.append(RowError(0, "", "JSON 解析失败:%s" % exc))
            return result

        # 兼容两种写法:{"words": [...]} 或者直接就是一个数组
        entries = payload.get("words") if isinstance(payload, dict) else payload
        if not isinstance(entries, list):
            result.errors.append(RowError(0, "", "JSON 结构不对:找不到单词数组"))
            return result

        for index, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict):
                result.errors.append(RowError(index, str(entry)[:40], "不是一个对象"))
                continue
            raw = raw_from_mapping(entry, index)
            if raw is None:
                result.errors.append(
                    RowError(index, str(entry)[:40], "缺少「单词」或「翻译」"))
            else:
                result.words.append(raw)
        return result


class CsvImporter(WordPackImporter):
    """逗号分隔。用 csv 模块解析,不自己 split(',') —— 释义里几乎一定有逗号。"""

    name = "csv"

    def can_handle(self, path: Path) -> bool:
        if path.suffix.lower() == ".csv":
            return True
        try:
            head = read_text(path).splitlines()[:1]
        except OSError:
            return False
        if not head:
            return False
        # 大括号开头的是 JSON 或老式行格式,不是 CSV。
        # 否则第一行里的"单词"两个字会让 CSV 误领这份文件。
        if head[0].lstrip()[:1] in ("{", "[", "<"):
            return False
        return any(
            alias in head[0]
            for aliases in COLUMN_ALIASES.values() for alias in aliases
        )

    def load(self, path: Path) -> ImportResult:
        result = ImportResult(format="csv")
        try:
            text = read_text(path)
        except OSError as exc:
            result.errors.append(RowError(0, "", "读取失败:%s" % exc))
            return result

        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            result.errors.append(RowError(0, "", "文件是空的,或者没有表头行"))
            return result

        if not map_columns(list(reader.fieldnames)):
            result.errors.append(
                RowError(1, ",".join(reader.fieldnames),
                         "表头里找不到「单词」和「翻译」两列"))

        for line_number, row in enumerate(reader, start=2):   # 表头占第 1 行
            raw = raw_from_mapping(row, line_number)
            if raw is None:
                # 完全空白的行直接忽略,不当作错误 —— Excel 里很常见
                if row_has_content(row):
                    result.errors.append(
                        RowError(line_number, str(row)[:40], "缺少「单词」或「翻译」"))
            else:
                result.words.append(raw)
        return result


class LegacyLineImporter(WordPackImporter):
    """guige.md 里示范的那种一行一条的写法。

        {单词: "atmosphere",发音: "/.../", 翻译: "n. 大气层,大气圈; 气氛", 组合:"1"}

    要点是引号里的逗号不能当成字段分隔符,否则"大气层,大气圈"会被切成两段。
    """

    name = "legacy_line"

    def can_handle(self, path: Path) -> bool:
        try:
            head = read_text(path).lstrip()
        except OSError:
            return False
        return head.startswith("{") and "单词" in head[:200]

    def load(self, path: Path) -> ImportResult:
        result = ImportResult(format="legacy_line")
        try:
            lines = read_text(path).splitlines()
        except OSError as exc:
            result.errors.append(RowError(0, "", "读取失败:%s" % exc))
            return result

        for line_number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            if not (stripped.startswith("{") and stripped.endswith("}")):
                result.errors.append(
                    RowError(line_number, stripped[:40], "这一行不是 {…} 格式"))
                continue

            fields = self._parse_fields(stripped)
            raw = raw_from_mapping({
                "单词": fields.get("单词", ""),
                "翻译": fields.get("翻译", ""),
                "发音": fields.get("发音", ""),
                "例句": fields.get("例句", ""),
                "搭配": fields.get("搭配", ""),
                "组合": fields.get("组合", ""),
            }, line_number)
            if raw is None:
                result.errors.append(
                    RowError(line_number, stripped[:40], "缺少「单词」或「翻译」"))
            else:
                result.words.append(raw)
        return result

    @staticmethod
    def _parse_fields(stripped_line: str) -> dict:
        """把 {a: 1, b: 2} 拆成 {"a": "1", "b": "2"}。

        全角冒号也认 —— 中文输入法下敲出来的多半是"：",
        而"atmosphere"这类词里不会出现冒号,所以按冒号切是安全的。
        """
        fields = {}
        for piece in split_outside_quotes(stripped_line[1:-1]):
            if ":" not in piece and "：" not in piece:
                continue
            separator = ":" if ":" in piece else "："
            key, _, value = piece.partition(separator)
            fields[clean_field(key)] = strip_quotes(value)
        return fields


class PlainTextImporter(WordPackImporter):
    """兜底:每行 "单词<TAB>翻译",或者用空白分隔。"""

    name = "plain"

    def can_handle(self, path: Path) -> bool:
        # 排在最后兜底,所以它接受任何文件。
        # 前面三个都认不出来时,与其报"无法识别的格式",不如按最朴素的
        # "单词 翻译"去试着读 —— 至少用户能拿到"第 3 行分不出单词和翻译"
        # 这种具体错误,比笼统的"格式不支持"有用得多。
        return True

    def load(self, path: Path) -> ImportResult:
        try:
            lines = read_text(path).splitlines()
        except OSError as exc:
            result = ImportResult(format="plain")
            result.errors.append(RowError(0, "", "读取失败:%s" % exc))
            return result
        return parse_plain_lines(lines)


def parse_plain_lines(lines) -> ImportResult:
    """把多行文本按"单词<TAB>翻译"解析成一串 RawWord。

    从 PlainTextImporter.load 里抽出来,是为了让"粘贴一大段文本建词包"
    这条路(见 ui/views/wordset.py 的「新建词包」)和读文件走**完全一样**
    的切分逻辑 —— 不至于出现"文件里能认、粘贴进来却不认"的别扭。
    """
    result = ImportResult(format="plain")
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        pieces = split_word_and_translation(stripped)
        if pieces is None:
            result.errors.append(
                RowError(line_number, stripped[:40], "分不出单词和翻译"))
            continue

        word, translation = clean_field(pieces[0]), clean_field(pieces[1])
        if not word or not translation:
            result.errors.append(
                RowError(line_number, stripped[:40], "缺少「单词」或「翻译」"))
            continue
        # source_line 记下来,导入结果列表里能标出"这条来自第几行"
        result.words.append(RawWord(
            word=word, translation=translation, source_line=line_number))
    return result
