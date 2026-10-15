# -*- coding: utf-8 -*-
"""导入导出共用的文本/字段小工具。

这里放的都是"把一团乱七八糟的文本变成干净字段"的纯函数:猜编码、
归一化全角字符、把一行 CSV 映射成 RawWord。它们不关心文件是什么格式,
也不碰网络和界面,所以可以放心单独测试。

单独成模块的原因:这些函数原本散在 wordpack_import.py 里,把那个文件
撑到了 478 行 —— 而"这行到底该按哪种格式读"这种真正的业务判断反而
被淹没了。工具与业务分开之后,两边都变短了。
"""

import re
import unicodedata
import uuid
from typing import Dict, List, Optional, Tuple

from .interfaces import RawWord


# --------------------------------------------------------------------------
# 单词身份
# --------------------------------------------------------------------------

def spelling_key(word: str) -> str:
    """归一化拼写,仅用于导入去重。

    不能拿它当主键 —— 多义词(bank 既是"银行"又是"河岸")会撞车。
    所以去重时用它找"是不是同一个词",但状态始终挂在生成出来的 id 上。
    """
    return unicodedata.normalize("NFKC", word).strip().casefold()


def new_word_id() -> str:
    """生成一个稳定的单词 id。一经生成永不改变。"""
    return "w_" + uuid.uuid4().hex[:8]


# --------------------------------------------------------------------------
# 读文件
# --------------------------------------------------------------------------

def read_text(path) -> str:
    """按可能的编码依次尝试读取。

    先试 utf-8-sig:它既能正确读带 BOM 的文件,也能读普通 UTF-8。
    再试 gb18030:中文版 Excel 另存的 CSV 往往是这个编码。
    顺序不能反 —— gb18030 几乎能把任何字节序列解出来(只是乱码),
    放在前面会让 UTF-8 文件被解成乱码却不报错。
    """
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    # 两种都不行,只能带替换字符硬解,保证不抛异常
    return raw.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------
# 清洗单个字段
# --------------------------------------------------------------------------

def clean_field(text: str) -> str:
    """把字段里的全角字符折成半角并去掉首尾空白。

    NFKC 会把"ｂａｎｋ"和"bank"归一成同一个词,这是中文用户
    经常全角/半角混着敲导致的,不归一化就会重复导入。
    """
    return unicodedata.normalize("NFKC", text or "").strip()


def strip_quotes(text: str) -> str:
    """去掉最外层成对的引号。只剥一层,不做递归。"""
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        return text[1:-1].strip()
    return text


def split_outside_quotes(text: str) -> List[str]:
    """按逗号切分,但引号内的逗号不算。

    半角逗号和全角逗号都要认 —— 用户多半是在中文输入法下敲的,
    分隔符往往是"，"而不是","。
    """
    parts: List[str] = []
    buffer: List[str] = []
    inside_quotes = False
    for character in text:
        if character in ('"', "'"):
            inside_quotes = not inside_quotes
        if character in (",", "，") and not inside_quotes:
            parts.append("".join(buffer))
            buffer = []
        else:
            buffer.append(character)
    parts.append("".join(buffer))
    return parts


# --------------------------------------------------------------------------
# 列名映射:一行表格 → RawWord
# --------------------------------------------------------------------------

# 中文表头 ↔ 英文字段的对应关系。用户用哪种写法都能认。
COLUMN_ALIASES: Dict[str, Tuple[str, ...]] = {
    "word": ("单词", "word", "spelling", "term", "英文", "词"),
    "translation": ("翻译", "translation", "meaning", "definition", "释义", "中文", "意思"),
    "phonetic": ("发音", "phonetic", "pronunciation", "音标"),
    "example": ("例句", "example", "sentence", "例子"),
    "collocation": ("搭配", "collocation", "phrase", "词组"),
    "group": ("组合", "group", "分组"),
}

# 把别名全部预先小写化,省得每次比较都算一遍
_LOWERED_ALIASES: Dict[str, Tuple[str, ...]] = {
    internal: tuple(alias.lower() for alias in aliases)
    for internal, aliases in COLUMN_ALIASES.items()
}


def _internal_name(column: str) -> Optional[str]:
    """把一个表头名翻成内部字段名,认不出来返回 None。"""
    key = clean_field(column).lower()
    for internal, aliases in _LOWERED_ALIASES.items():
        if key in aliases:
            return internal
    return None


def map_columns(fieldnames: List[str]) -> Dict[str, str]:
    """把实际的表头映射成内部字段名:{原始列名: 内部字段名}。

    返回空字典说明这份文件的表头里既没有"单词"也没有"翻译",
    调用方据此给出"找不到必需的列"这种明确提示。
    """
    mapping: Dict[str, str] = {}
    for column in fieldnames or []:
        internal = _internal_name(column)
        if internal:
            mapping[column] = internal
    return mapping


def raw_from_mapping(row: Dict[str, object], line: int) -> Optional[RawWord]:
    """把一行映射转成 RawWord。缺少必填项时返回 None。

    同时接受中文键和英文键,这样无论是本程序导出的 CSV,
    还是用户自己用 Excel 随手建的表,都能读进来。

    键为 None 的行会被跳过 —— csv 模块会把"多出来的列"塞在 None 键下面。
    """
    values: Dict[str, str] = {}
    for key, value in row.items():
        if key is None:
            continue
        internal = _internal_name(key)
        if internal:
            values[internal] = clean_field(str(value) if value is not None else "")

    word = values.get("word", "")
    translation = values.get("translation", "")
    if not word or not translation:
        return None

    return RawWord(
        word=word, translation=translation,
        phonetic=values.get("phonetic", ""),
        example=values.get("example", ""),
        collocation=values.get("collocation", ""),
        group=values.get("group", ""),
        source_line=line,
    )


def row_has_content(row: Dict[str, object]) -> bool:
    """判断一行是不是"真的有内容",用来区分空行和填错的行。

    注意 csv 模块的一个坑:某一行比表头多出列时,多出来的部分会以
    None 为键、以**列表**为值塞进这一行。直接对 row.values() 调 .strip()
    会在这种行上崩掉,所以这里必须分情况处理。
    """
    for key, value in row.items():
        if key is None:
            # 多出来的列。注意 [""] 这种"列表里有但内容是空串"的情况
            # 依然算空行,不能只看列表本身非空就当成有内容。
            if isinstance(value, list):
                if any(str(item).strip() for item in value):
                    return True
            elif value:
                return True
            continue
        if isinstance(value, str) and value.strip():
            return True
    return False


def split_word_and_translation(line: str) -> Optional[Tuple[str, str]]:
    """把"单词 翻译"这种最朴素的一行切成两半。切不开返回 None。

    优先用制表符 —— 用户从 Excel 复制出来的多半是制表符。
    没有制表符时按连续空白切一次,只切一刀,剩下的全归翻译,
    因为翻译里出现空格是很正常的("n. 银行; 河岸")。
    """
    if "\t" in line:
        word, _, translation = line.partition("\t")
        return word, translation
    pieces = re.split(r"\s{2,}|\s", line, maxsplit=1)
    if len(pieces) < 2:
        return None
    return pieces[0], pieces[1]
