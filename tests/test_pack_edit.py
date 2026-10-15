# -*- coding: utf-8 -*-
"""词包增删词 / 删包的纯逻辑测试。

这套逻辑最要紧的一条:**删一个共用词不能误删别人的词,删一个独有词
必须连学习记录一起清掉,不留孤儿。** 因为单词记录只有全局一份、
词包只存 id,这两件事一旦搞反,用户会看到"另一个包里少了个词"
或者"全局索引里越积越多的隐形词"。
"""

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.interfaces import RawWord                     # noqa: E402
from core.pack_edit import (                            # noqa: E402
    attach_words,
    detach_all,
    detach_word,
    find_today_result_pack,
    remove_pack,
)
from core.packs import (                                # noqa: E402
    PACK_TYPE_EXAM,
    PACK_TYPE_STUDY,
    WordPack,
    make_vocab_pack,
)
from core.wordpack_import import apply_import           # noqa: E402

TODAY = date(2026, 10, 12)


def build_index_and_packs():
    """造一个词库 + 两个包:甲{bank, planet},乙{bank}。

    bank 是两包共用的,planet 是甲独有的 —— 正好覆盖两种删除路径。
    """
    index = {}
    _, ids_a = apply_import(
        index,
        [RawWord(word="bank", translation="银行"),
         RawWord(word="planet", translation="行星")],
        pack_id="pack_a", today=TODAY, return_ids=True)
    _, ids_b = apply_import(
        index, [RawWord(word="bank", translation="银行")],
        pack_id="pack_b", today=TODAY, return_ids=True)
    pack_a = make_vocab_pack("pack_a", "甲", ids_a, TODAY.isoformat())
    pack_b = make_vocab_pack("pack_b", "乙", ids_b, TODAY.isoformat())
    return index, pack_a, pack_b, ids_a, ids_b


class TestDetachWord(unittest.TestCase):
    def test_removes_id_from_that_pack_only(self):
        index, pack_a, pack_b, ids_a, _ = build_index_and_packs()
        detach_word(index, [pack_a, pack_b], pack_a, ids_a[1])   # 摘 planet
        self.assertNotIn(ids_a[1], pack_a.word_ids)
        self.assertEqual(pack_b.word_ids, [ids_a[0]], "乙包不该被动")

    def test_unique_word_record_is_deleted(self):
        """只属于甲包的词,摘掉之后连学习记录一起删 —— 不留孤儿。"""
        index, pack_a, pack_b, ids_a, _ = build_index_and_packs()
        planet_id = ids_a[1]
        removed = detach_word(index, [pack_a, pack_b], pack_a, planet_id)
        self.assertTrue(removed)
        self.assertNotIn(planet_id, index)

    def test_shared_word_survives(self):
        """bank 还在乙包里,摘出甲包后记录必须保留。"""
        index, pack_a, pack_b, ids_a, ids_b = build_index_and_packs()
        bank_id = ids_a[0]
        removed = detach_word(index, [pack_a, pack_b], pack_a, bank_id)
        self.assertFalse(removed)
        self.assertIn(bank_id, index, "共用词被误删了")
        self.assertNotIn("pack_a", index[bank_id].source_packs, "甲包引用该摘掉")
        self.assertIn("pack_b", index[bank_id].source_packs, "乙包引用该保留")
        self.assertIn(bank_id, pack_b.word_ids)

    def test_scrubs_dangling_mistake_id(self):
        """别包错题缓存里若还留着这个词 id,一并清掉,免得指向不存在的词。"""
        index, pack_a, pack_b, ids_a, _ = build_index_and_packs()
        planet_id = ids_a[1]
        pack_b.mistakes.append(planet_id)          # 人为制造一条悬空引用
        detach_word(index, [pack_a, pack_b], pack_a, planet_id)
        self.assertNotIn(planet_id, pack_b.mistakes)

    def test_unknown_word_is_noop(self):
        index, pack_a, pack_b, _, _ = build_index_and_packs()
        self.assertFalse(detach_word(index, [pack_a, pack_b], pack_a, "w_不存在"))
        self.assertNotIn("w_不存在", pack_a.word_ids)


class TestDetachAll(unittest.TestCase):
    def test_empties_pack_and_keeps_shared_words(self):
        index, pack_a, pack_b, ids_a, _ = build_index_and_packs()
        detach_all(index, [pack_a, pack_b], pack_a)
        self.assertEqual(pack_a.word_ids, [])
        # planet 独有 → 删;bank 共用 → 留
        self.assertNotIn(ids_a[1], index)
        self.assertIn(ids_a[0], index)
        self.assertEqual(pack_b.word_ids, [ids_a[0]])


class TestRemovePack(unittest.TestCase):
    def test_removes_by_identity_not_equality(self):
        """两个内容完全一样的包,删的必须是传进来的那个对象。"""
        first = make_vocab_pack("dup", "同名", ["w_1"], "2026-10-12")
        second = make_vocab_pack("dup", "同名", ["w_1"], "2026-10-12")
        self.assertEqual(first, second, "前提:两者 == 相等")
        packs = [first, second]
        remove_pack(packs, second)
        self.assertEqual(len(packs), 1)
        self.assertIs(packs[0], first, "被删的应是 second 而不是 first")

    def test_missing_pack_is_noop(self):
        first = make_vocab_pack("a", "甲", [], "2026-10-12")
        packs = [first]
        remove_pack(packs, make_vocab_pack("b", "乙", [], "2026-10-12"))
        self.assertEqual(packs, [first])


class TestAttachWords(unittest.TestCase):
    """把学完的词并进当天的结果包(1.3 加的)。"""

    def _result_pack(self, pack_id="pack_20261012_009", day="2026-10-12"):
        return WordPack(id=pack_id, pack_type=PACK_TYPE_STUDY, title="今天",
                        created_at=day)

    def test_appends_in_order_and_reports_how_many(self):
        index, _pack_a, _pack_b, ids_a, _ = build_index_and_packs()
        target = self._result_pack()
        added = attach_words(target, [index[wid] for wid in ids_a])
        self.assertEqual(added, 2)
        self.assertEqual(target.word_ids, ids_a, "先后要保持传进来的顺序")

    def test_duplicates_are_skipped(self):
        """同一天学第二场时,早上学过的词可能已经在当天的包里了 ——
        重复 append 会让词数虚高,而且列表越滚越长。"""
        index, _pack_a, _pack_b, ids_a, _ = build_index_and_packs()
        target = self._result_pack()
        attach_words(target, [index[ids_a[0]]])
        added = attach_words(target, [index[ids_a[1]], index[ids_a[0]]])
        self.assertEqual(added, 1)
        self.assertEqual(target.word_ids, ids_a)

    def test_does_not_touch_source_packs(self):
        """结果包不参与 source_packs —— 那个字段记的是"这个词从哪个词表包来"。
        混着写会让删词表包时误判成"还有别人要它",于是学习记录删不掉。

        这里用 planet(只属于甲包的那个词):bank 两包共用,断言会看不太出来。
        """
        index, _pack_a, _pack_b, ids_a, _ = build_index_and_packs()
        attach_words(self._result_pack(), [index[ids_a[1]]])
        self.assertEqual(index[ids_a[1]].source_packs, ["pack_a"])


class TestFindTodayResultPack(unittest.TestCase):
    def _study(self, pack_id, day):
        return WordPack(id=pack_id, pack_type=PACK_TYPE_STUDY,
                        title="%s 学习词包" % day, created_at=day)

    def test_finds_the_study_pack_of_that_day(self):
        yesterday = self._study("pack_20261011_001", "2026-10-11")
        today = self._study("pack_20261012_001", "2026-10-12")
        self.assertIs(find_today_result_pack([yesterday, today], TODAY), today)

    def test_ignores_exam_packs_of_the_same_day(self):
        """考试包自带一份 exam 快照,把学习记录并进去会让那份快照对不上。"""
        exam = WordPack(id="pack_20261012_001", pack_type=PACK_TYPE_EXAM,
                        title="2026-10-12 考试词包", created_at="2026-10-12")
        self.assertIsNone(find_today_result_pack([exam], TODAY))

    def test_none_when_nothing_matches(self):
        self.assertIsNone(find_today_result_pack([], TODAY))
        stale = self._study("pack_20261010_001", "2026-10-10")
        self.assertIsNone(find_today_result_pack([stale], TODAY))

    def test_picks_the_newest_when_several(self):
        """app.packs 是把新包 append 到**末尾**的,列表顺序和"由新到旧"正好
        相反,所以只能按 id 取最大的那个 —— 取列表里第一个匹配会拿到最旧的。"""
        old = self._study("pack_20261012_001", "2026-10-12")
        new = self._study("pack_20261012_004", "2026-10-12")
        self.assertIs(find_today_result_pack([old, new], TODAY), new)
        self.assertIs(find_today_result_pack([new, old], TODAY), new)


if __name__ == "__main__":
    unittest.main(verbosity=2)
