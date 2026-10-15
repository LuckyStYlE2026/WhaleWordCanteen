# -*- coding: utf-8 -*-
"""词表导入 / 导出测试。

最要紧的两条:
  · 释义里带逗号("n. 大气层, 大气圈; 气氛")往返之后必须一字不差
  · 重复导入同一份词表,不能把已经背了半个月的进度清零
"""

import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import Mastery, Word                     # noqa: E402
from core.wordpack_export import (                        # noqa: E402
    CsvExporter,
    JsonExporter,
    export_both,
)
from core.wordpack_import import (                        # noqa: E402
    CsvImporter,
    JsonImporter,
    LegacyLineImporter,
    PlainTextImporter,
    apply_import,
    detect_format,
    import_file,
    spelling_key,
)

TODAY = date(2026, 10, 12)
# 这条释义里同时有逗号和分号 —— 正是最容易把 CSV 写坏的那种
TRICKY_TRANSLATION = "n. 大气层, 大气圈; 气氛"


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="remember_io_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def write(self, name, content, encoding="utf-8"):
        path = self.temp_dir / name
        path.write_text(content, encoding=encoding)
        return path


class TestSpellingKey(unittest.TestCase):
    def test_case_and_whitespace_insensitive(self):
        self.assertEqual(spelling_key("  Atmosphere "), "atmosphere")
        self.assertEqual(spelling_key("ATMOSPHERE"), spelling_key("atmosphere"))

    def test_full_width_normalised(self):
        self.assertEqual(spelling_key("ｂａｎｋ"), "bank")


class TestJsonImport(TempDirTestCase):
    def test_canonical_format(self):
        path = self.write("a.json", """
        {"version": 1, "words": [
          {"单词": "atmosphere", "翻译": "n. 大气层", "组合": "1"},
          {"单词": "lithosphere", "翻译": "n. 岩石圈"}
        ]}""")
        result = JsonImporter().load(path)
        self.assertEqual(result.format, "json")
        self.assertEqual(len(result.words), 2)
        self.assertEqual(result.words[0].group, "1")
        self.assertEqual(result.words[1].phonetic, "")

    def test_bare_array_also_accepted(self):
        """有些工具就是导出一个裸数组,不该因此失败。"""
        path = self.write("a.json", '[{"单词": "bank", "翻译": "银行"}]')
        self.assertEqual(len(JsonImporter().load(path).words), 1)

    def test_broken_json_reports_error_not_crash(self):
        path = self.write("a.json", "{ 这不是 json")
        result = JsonImporter().load(path)
        self.assertEqual(result.words, [])
        self.assertTrue(result.errors)

    def test_entry_missing_required_fields_is_reported(self):
        path = self.write("a.json", '{"words": [{"单词": "bank"}, {"翻译": "银行"}]}')
        result = JsonImporter().load(path)
        self.assertEqual(result.words, [])
        self.assertEqual(len(result.errors), 2)


class TestCsvImport(TempDirTestCase):
    def test_chinese_headers(self):
        path = self.write("a.csv",
                          "单词,发音,翻译,例句,搭配,组合\n"
                          "atmosphere,/x/,n. 大气层,,,1\n")
        result = CsvImporter().load(path)
        self.assertEqual(len(result.words), 1)
        self.assertEqual(result.words[0].translation, "n. 大气层")

    def test_english_headers_also_work(self):
        """用户自己拿英文表头建的表也要能吃。"""
        path = self.write("a.csv", "word,translation,group\nbank,银行,2\n")
        result = CsvImporter().load(path)
        self.assertEqual(result.words[0].word, "bank")
        self.assertEqual(result.words[0].group, "2")

    def test_translation_containing_commas_survives(self):
        """释义里的逗号必须被 csv 模块正确引用,不能被切成两列。"""
        path = self.temp_dir / "a.csv"
        CsvExporter().export(
            [Word(id="w_1", spelling_key="x", word="atmosphere",
                  translation=TRICKY_TRANSLATION)], path)
        result = CsvImporter().load(path.with_suffix(".csv"))
        self.assertEqual(result.words[0].translation, TRICKY_TRANSLATION)

    def test_gbk_encoded_file_is_read(self):
        """中文版 Excel 另存的 CSV 是 GBK 编码,不能读成乱码。"""
        path = self.temp_dir / "gbk.csv"
        path.write_bytes("单词,翻译\natmosphere,n. 大气层\n".encode("gb18030"))
        result = CsvImporter().load(path)
        self.assertEqual(result.words[0].translation, "n. 大气层")

    def test_utf8_bom_file_is_read(self):
        path = self.write("bom.csv", "单词,翻译\nbank,银行\n", encoding="utf-8-sig")
        self.assertEqual(CsvImporter().load(path).words[0].word, "bank")

    def test_blank_rows_are_ignored(self):
        path = self.write("a.csv", "单词,翻译\nbank,银行\n,,\n")
        result = CsvImporter().load(path)
        self.assertEqual(len(result.words), 1)
        self.assertEqual(result.errors, [], "空行不该算错误")

    def test_row_missing_translation_is_reported_with_line_number(self):
        path = self.write("a.csv", "单词,翻译\nbank,银行\nkey,\n")
        result = CsvImporter().load(path)
        self.assertEqual(len(result.words), 1)
        self.assertEqual(result.errors[0].line, 3, "应指出是第 3 行")

    def test_header_without_required_columns_is_reported(self):
        path = self.write("a.csv", "名称,备注\nbank,银行\n")
        result = CsvImporter().load(path)
        self.assertTrue(result.errors)


class TestLegacyLineImport(TempDirTestCase):
    """guige.md 第 27-28 行的示范格式。"""

    LEGACY = (
        '{单词: "atmosphere",发音: "/əmˈtʃuːzət/", 翻译: "n. 大气层,大气圈; 气氛", '
        '例句: "The atmosphere of the earth is very thick.", 搭配:"atmosphere pressure", 组合:"1"}\n'
        '{单词: "lithosphere",发音: "", 翻译: "n. 岩石圈", 例句: "", 搭配:"", 组合:"1"}\n'
    )

    def test_spec_sample_parses(self):
        path = self.write("a.txt", self.LEGACY)
        result = LegacyLineImporter().load(path)
        self.assertEqual(len(result.words), 2)
        self.assertEqual(result.errors, [])

        first = result.words[0]
        self.assertEqual(first.word, "atmosphere")
        # 引号里的逗号不能被当成字段分隔符
        self.assertEqual(first.translation, "n. 大气层,大气圈; 气氛")
        self.assertEqual(first.group, "1")
        self.assertEqual(first.collocation, "atmosphere pressure")

        second = result.words[1]
        self.assertEqual(second.word, "lithosphere")
        self.assertEqual(second.phonetic, "")

    def test_full_width_colon_accepted(self):
        path = self.write("a.txt", '{单词："bank"，翻译："银行"}')
        result = LegacyLineImporter().load(path)
        self.assertEqual(result.words[0].translation, "银行")

    def test_unquoted_values_accepted(self):
        path = self.write("a.txt", "{单词: bank, 翻译: 银行}\n")
        self.assertEqual(LegacyLineImporter().load(path).words[0].word, "bank")

    def test_malformed_line_reports_line_number(self):
        path = self.write("a.txt", '{单词: "bank", 翻译: "银行"}\n这一行是废话\n')
        result = LegacyLineImporter().load(path)
        self.assertEqual(len(result.words), 1)
        self.assertEqual(result.errors[0].line, 2)


class TestPlainImport(TempDirTestCase):
    def test_tab_separated(self):
        path = self.write("a.txt", "atmosphere\tn. 大气层\nbank\t银行\n")
        result = PlainTextImporter().load(path)
        self.assertEqual(len(result.words), 2)
        self.assertEqual(result.words[0].translation, "n. 大气层")

    def test_space_separated(self):
        path = self.write("a.txt", "atmosphere n. 大气层\n")
        self.assertEqual(PlainTextImporter().load(path).words[0].word, "atmosphere")

    def test_single_token_line_is_reported(self):
        path = self.write("a.txt", "atmosphere\n")
        result = PlainTextImporter().load(path)
        self.assertEqual(result.words, [])
        self.assertEqual(result.errors[0].line, 1)


class TestFormatDetection(TempDirTestCase):
    def test_json_by_extension_and_content(self):
        self.assertIsInstance(detect_format(self.write("a.json", "{}")), JsonImporter)

    def test_csv_by_header(self):
        self.assertIsInstance(detect_format(self.write("a.txt", "单词,翻译\nx,y\n")), CsvImporter)

    def test_legacy_by_content(self):
        self.assertIsInstance(
            detect_format(self.write("a.txt", '{单词: "a", 翻译: "b"}')), LegacyLineImporter)

    def test_plain_as_last_resort(self):
        self.assertIsInstance(detect_format(self.write("a.txt", "a\tb")), PlainTextImporter)

    def test_import_file_end_to_end(self):
        path = self.write("a.csv", "单词,翻译\nbank,银行\n")
        self.assertEqual(import_file(path).words[0].translation, "银行")

    def test_unknown_extension_still_gets_a_parser(self):
        path = self.write("a.xyz", "bank\t银行")
        self.assertEqual(len(import_file(path).words), 1)


class TestExport(TempDirTestCase):
    def make_words(self):
        word = Word(id="w_1", spelling_key="atmosphere", word="atmosphere",
                    translation=TRICKY_TRANSLATION, phonetic="/x/",
                    example="The atmosphere is thick.", collocation="atmosphere pressure",
                    group="1")
        return [word]

    def test_csv_has_bom_and_chinese_headers(self):
        """没有 BOM 的话,中文 Excel 会把整列翻译显示成乱码。"""
        path = CsvExporter().export(self.make_words(), self.temp_dir / "out")
        raw = path.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "缺少 UTF-8 BOM")
        self.assertIn("单词", raw.decode("utf-8-sig"))

    def test_csv_excludes_internal_fields(self):
        """CSV 是给 Excel 看的,不该出现 id、box 这些内部字段。"""
        path = CsvExporter().export(self.make_words(), self.temp_dir / "out")
        content = path.read_text(encoding="utf-8-sig")
        self.assertNotIn("w_1", content)
        self.assertNotIn("spelling_key", content)

    def test_json_is_lossless_including_state(self):
        words = self.make_words()
        words[0].state.mastery = Mastery.KNOWN
        words[0].state.box = 4
        path = JsonExporter().export(words, self.temp_dir / "out")

        restored = JsonImporter().load(path).words
        # JsonImporter 产出的是 RawWord(还没进词库),所以这里直接看原文
        import json
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["words"][0]["state"]["box"], 4)
        self.assertEqual(payload["words"][0]["id"], "w_1")

    def test_comma_translation_survives_a_full_round_trip(self):
        """先导出再导入,释义必须一字不差 —— 这是来回编辑不丢数据的前提。"""
        path = CsvExporter().export(self.make_words(), self.temp_dir / "out")
        self.assertEqual(CsvImporter().load(path).words[0].translation, TRICKY_TRANSLATION)

    def test_export_both_writes_two_files(self):
        written = export_both(self.make_words(), self.temp_dir / "out")
        self.assertEqual(len(written), 2)
        self.assertEqual({p.suffix for p in written}, {".csv", ".json"})
        for path in written:
            self.assertTrue(path.exists())


class TestApplyImport(unittest.TestCase):
    """合并进词库的规则 —— 尤其"重复导入不丢进度"这一条。"""

    def setUp(self):
        from core.interfaces import RawWord
        self.RawWord = RawWord

    def test_new_words_get_ids_and_initial_state(self):
        index = {}
        stats = apply_import(index, [self.RawWord(word="bank", translation="银行")], today=TODAY)
        self.assertEqual(stats["added"], 1)
        word = list(index.values())[0]
        self.assertTrue(word.id.startswith("w_"))
        self.assertEqual(word.state.next_review, "2026-10-12")

    def test_reimport_preserves_learning_progress(self):
        """这是整个导入逻辑里最要紧的一条。

        用户背了半个月后重新导入一次词表,进度必须还在。
        如果这里退化成"重新建词",用户的 box、错题记录全没了 ——
        那是最不能接受的一类 bug。
        """
        index = {}
        apply_import(index, [self.RawWord(word="bank", translation="银行")], today=TODAY)
        word = list(index.values())[0]
        word.state.box = 5
        word.state.mastery = Mastery.KNOWN
        word.state.wrong_count = 3
        word.state.next_review = "2026-11-01"
        original_id = word.id

        stats = apply_import(
            index, [self.RawWord(word="bank", translation="n. 银行; 河岸")], today=TODAY)

        self.assertEqual(stats["updated"], 1)
        self.assertEqual(stats["added"], 0)
        self.assertEqual(len(index), 1, "不该产生第二个词条")
        self.assertEqual(word.id, original_id, "id 必须复用")
        self.assertEqual(word.state.box, 5, "box 丢了")
        self.assertEqual(word.state.wrong_count, 3, "错题次数丢了")
        self.assertEqual(word.state.next_review, "2026-11-01", "复习日期丢了")
        self.assertEqual(word.translation, "n. 银行; 河岸", "释义应该更新")

    def test_dedup_is_case_insensitive(self):
        index = {}
        apply_import(index, [self.RawWord(word="Bank", translation="银行")], today=TODAY)
        apply_import(index, [self.RawWord(word="bank", translation="银行")], today=TODAY)
        self.assertEqual(len(index), 1)

    def test_same_word_different_meaning_is_merged_not_duplicated(self):
        """多义词按拼写合并。用户想分开的话应该用组合字段区分。"""
        index = {}
        apply_import(index, [self.RawWord(word="bank", translation="银行")], today=TODAY)
        apply_import(index, [self.RawWord(word="bank", translation="河岸")], today=TODAY)
        self.assertEqual(len(index), 1)

    def test_source_pack_is_recorded(self):
        index = {}
        apply_import(index, [self.RawWord(word="bank", translation="银行")],
                     pack_id="pack_1", today=TODAY)
        self.assertEqual(list(index.values())[0].source_packs, ["pack_1"])

    def test_source_pack_not_duplicated_on_reimport(self):
        index = {}
        raw = [self.RawWord(word="bank", translation="银行")]
        apply_import(index, raw, pack_id="pack_1", today=TODAY)
        apply_import(index, raw, pack_id="pack_1", today=TODAY)
        self.assertEqual(list(index.values())[0].source_packs, ["pack_1"])

    def test_blank_word_is_skipped(self):
        stats = apply_import({}, [self.RawWord(word="  ", translation="x")], today=TODAY)
        self.assertEqual(stats["skipped"], 1)

    def test_return_ids_matches_words_and_order(self):
        """return_ids=True 时返回的 id 列表要和 raw_words 一一对应、按序,
        跳过的词不在里面。建词包时靠它把词挂到包上,错位或漏一个,
        词包就会显示错词或少词。"""
        raws = [self.RawWord(word="bank", translation="银行"),
                self.RawWord(word="  ", translation="空词被跳过"),
                self.RawWord(word="atmosphere", translation="大气层")]
        index = {}
        stats, ids = apply_import(index, raws, today=TODAY, return_ids=True)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(len(ids), 2)
        self.assertEqual(ids[0], index[ids[0]].id)
        self.assertEqual(ids[1], index[ids[1]].id)
        self.assertEqual(index[ids[0]].word, "bank")
        self.assertEqual(index[ids[1]].word, "atmosphere")

    def test_return_ids_default_false_keeps_old_contract(self):
        """默认 return_ids=False,老调用拿到的还是单纯的 stats 字典。"""
        result = apply_import({}, [self.RawWord(word="bank", translation="银行")],
                              today=TODAY)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["added"], 1)


class TestImportAsPack(TempDirTestCase):
    """导入即建包:一份文件 = 一个 vocab 词包。"""

    def setUp(self):
        super().setUp()
        from core.interfaces import RawWord
        from core.wordpack_import import import_as_pack
        self.RawWord = RawWord
        self.import_as_pack = import_as_pack

    def _write_plain(self, name="words.txt"):
        return self.write(name, "atmosphere\tn. 大气层\nbank\t银行\n")

    def test_creates_vocab_pack_with_stem_title(self):
        """建出来的包是 vocab 型、标题取文件名、word_ids 指向刚加入的词。"""
        path = self._write_plain("geo.txt")
        index = {}
        pack, result, stats = self.import_as_pack(index, path,
                                                  "pack_20261012_001", TODAY)
        from core.packs import PACK_TYPE_VOCAB
        self.assertEqual(pack.pack_type, PACK_TYPE_VOCAB)
        self.assertEqual(pack.title, "geo")
        self.assertEqual(pack.created_at, "2026-10-12")
        self.assertEqual(pack.exam, None)
        self.assertEqual(len(pack.word_ids), 2)
        # 词包里的 id 必须真的指向词库里的词
        for wid in pack.word_ids:
            self.assertIn(wid, index)
            self.assertIn(pack.id, index[wid].source_packs)

    def test_reimport_makes_new_pack_but_keeps_word_state(self):
        """同一份文件导第二次:建出第二个词包,但词的进度仍保留
        (同拼写复用 id)。这是用户「补几个词再导一次」的安全感来源。"""
        path = self._write_plain()
        index = {}
        pack_a, _r, _s = self.import_as_pack(index, path,
                                             "pack_20261012_001", TODAY)
        # 假装用户背了一阵
        for wid in pack_a.word_ids:
            index[wid].state.box = 4
            index[wid].state.mastery = Mastery.KNOWN

        pack_b, _r2, _s2 = self.import_as_pack(index, path,
                                              "pack_20261012_002", TODAY)
        self.assertNotEqual(pack_a.id, pack_b.id, "应是两个不同的词包")
        # 同拼写的词复用 id,进度不丢
        self.assertEqual(set(pack_a.word_ids), set(pack_b.word_ids))
        for wid in pack_b.word_ids:
            self.assertEqual(index[wid].state.box, 4)
            self.assertEqual(index[wid].state.mastery, Mastery.KNOWN)
            # 两个包都记在 source_packs 里
            self.assertIn(pack_a.id, index[wid].source_packs)
            self.assertIn(pack_b.id, index[wid].source_packs)

    def test_empty_file_still_returns_a_pack(self):
        """读不到任何词的文件也返回一个(空)包 —— 是否丢弃交给调用方决定,
        这里只保证不抛异常,让 UI 的批量循环能继续处理下一个文件。"""
        path = self.write("empty.txt", "")
        pack, result, _s = self.import_as_pack({}, path,
                                               "pack_20261012_001", TODAY)
        self.assertEqual(pack.word_ids, [])
        self.assertEqual(len(result.words), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
