# -*- coding: utf-8 -*-
"""词包里的**重复 id**:出现过一次真事故,这一组锁住它。

用户 2026-10-15 报的:

    学习 20 词,生成了 30 词的词包。前 10 词添加了 2 遍。

他的存档里确实有一个 30 个 id、只有 20 个唯一词的包。而 `attach_words`
本来就去重 —— 所以这一组测试守两件事:

1. **去重本身**必须对(包括"同一批里传进重复的 id"这种更刁的输入);
2. **存档里已经有的重复要能被修掉**,而且读的时候顺手修 ——
   老存档不会有别的机会被收拾。
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from core import storage
from core.models import Word
from core.pack_edit import attach_words, dedupe_word_ids
from core.packs import PACK_TYPE_STUDY, WordPack


def make_words(count: int, prefix: str = "d"):
    return [Word(id="%s_%d" % (prefix, index), spelling_key="k%d" % index,
                 word="w%d" % index, translation="释义%d" % index)
            for index in range(count)]


def make_pack(word_ids=None) -> WordPack:
    return WordPack(id="pack_test", pack_type=PACK_TYPE_STUDY, title="测试",
                    created_at="2026-10-15", word_ids=list(word_ids or []))


class DedupeTest(unittest.TestCase):
    """dedupe_word_ids 本身。"""

    def test_it_removes_repeats_and_keeps_the_first_position(self):
        pack = make_pack(["a", "b", "a", "c", "b"])
        removed = dedupe_word_ids(pack)
        self.assertEqual(removed, 2)
        self.assertEqual(pack.word_ids, ["a", "b", "c"])

    def test_a_clean_pack_is_untouched(self):
        pack = make_pack(["a", "b", "c"])
        self.assertEqual(dedupe_word_ids(pack), 0)
        self.assertEqual(pack.word_ids, ["a", "b", "c"])

    def test_it_reports_how_many_it_removed(self):
        pack = make_pack(["x", "x", "x"])
        self.assertEqual(dedupe_word_ids(pack), 2)
        self.assertEqual(pack.word_ids, ["x"])

    def test_an_empty_pack_is_fine(self):
        pack = make_pack([])
        self.assertEqual(dedupe_word_ids(pack), 0)


class AttachWordsTest(unittest.TestCase):
    """加词必须**永远**不能造出重复。"""

    def test_adding_the_same_batch_twice_adds_nothing_the_second_time(self):
        """这就是用户遇到的那个场景的**正常**行为:

        上午学了前 10 个 —— 结果包里有 10 个;
        下午学了前 20 个 —— 前 10 个已经在包里了,只该新增 10 个。
        """
        words = make_words(20)
        pack = make_pack()
        self.assertEqual(attach_words(pack, words[:10]), 10)
        self.assertEqual(attach_words(pack, words), 10)      # 不是 20
        self.assertEqual(pack.word_count, 20)
        self.assertEqual(len(set(pack.word_ids)), 20)

    def test_a_duplicate_within_one_batch_is_also_blocked(self):
        """同一批里传重了也要挡 —— 判据得覆盖"加完之后一定没有重复"。"""
        words = make_words(3)
        pack = make_pack()
        added = attach_words(pack, [words[0], words[1], words[0], words[2]])
        self.assertEqual(added, 3)
        self.assertEqual(pack.word_ids, [words[0].id, words[1].id, words[2].id])

    def test_a_dirty_pack_heals_itself_on_the_next_attach(self):
        """包里带着重复时,再 attach 一次应当顺手修好。"""
        words = make_words(3)
        pack = make_pack([words[0].id, words[1].id, words[0].id])
        added = attach_words(pack, [words[2]])
        self.assertEqual(added, 1)
        self.assertEqual(pack.word_ids, [words[0].id, words[1].id, words[2].id])


class StorageHealsDirtySavesTest(unittest.TestCase):
    """读存档时自动修掉重复 —— 老存档的唯一机会。"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="dedupe_test_")
        import os
        self._saved = os.environ.get("REMEMBER_DATA_DIR")
        os.environ["REMEMBER_DATA_DIR"] = self.temp_dir
        storage.bootstrap()

    def tearDown(self):
        import os
        if self._saved is None:
            os.environ.pop("REMEMBER_DATA_DIR", None)
        else:
            os.environ["REMEMBER_DATA_DIR"] = self._saved
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_dirty_pack(self):
        """直接往磁盘写一个"前 10 个 id 各出现两次"的包,模拟坏存档。"""
        pack = WordPack(id="pack_dirty", pack_type=PACK_TYPE_STUDY, title="坏包",
                        created_at="2026-10-15",
                        word_ids=["a", "b", "c", "a", "b", "c", "d", "e"])
        path = Path(storage.pack_path("pack_dirty"))
        path.write_text(json.dumps(pack.to_dict(), ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return path

    def test_reading_repairs_the_pack_in_memory(self):
        self._write_dirty_pack()
        packs = [p for p in storage.list_packs() if p.id == "pack_dirty"]
        self.assertEqual(len(packs), 1)
        self.assertEqual(packs[0].word_ids, ["a", "b", "c", "d", "e"])

    def test_reading_also_writes_the_repair_back(self):
        """只改内存没用 —— 下次启动又要修一遍,用户会以为"改了又变回来"。"""
        path = self._write_dirty_pack()
        storage.list_packs()
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["word_ids"], ["a", "b", "c", "d", "e"])

    def test_a_healthy_pack_is_not_rewritten_needlessly(self):
        pack = WordPack(id="pack_ok", pack_type=PACK_TYPE_STUDY, title="好包",
                        created_at="2026-10-15", word_ids=["a", "b"])
        path = Path(storage.pack_path("pack_ok"))
        path.write_text(json.dumps(pack.to_dict(), ensure_ascii=False, indent=2),
                        encoding="utf-8")
        before = path.stat().st_mtime_ns
        storage.list_packs()
        self.assertEqual(path.stat().st_mtime_ns, before)


if __name__ == "__main__":
    unittest.main()
