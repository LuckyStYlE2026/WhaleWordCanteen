# -*- coding: utf-8 -*-
"""词包进度与书签的纯逻辑测试(1.3 新加的一层)。

最要紧的两条:

1. **进度只前进不后退。** 用户回头把前面几课再看一遍是常事,那不该把
   「接着上次」打回第一课 —— 而且打回去之后界面上一句解释都没有,
   用户只会觉得这软件记不住事。
2. **存储 0 起、显示 +1 起,换算只在 core/pack_progress 里做一次。**
   这里要是错了不会崩,只会让所有人对着一个"差不多的数字" ——
   所以必须锁住。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import Word                            # noqa: E402
from core.pack_progress import (                        # noqa: E402
    bookmark_index,
    clamp_index,
    clear_bookmark,
    note_words,
    progress_label,
    record_progress,
    set_bookmark,
    study_range,
)
from core.packs import make_vocab_pack                  # noqa: E402


def make_pack(count=5):
    """造一个含 count 个词的词表包,id 就是它在包里的位置(方便断言)。"""
    ids = ["w_%d" % i for i in range(count)]
    return make_vocab_pack("pack_a", "甲", ids, "2026-10-12")


def words(*ids):
    """造几个 Word。note_words 只读 id,其余字段填占位。"""
    return [Word(id=wid, spelling_key=wid, word=wid, translation="释义")
            for wid in ids]


class TestClampIndex(unittest.TestCase):
    def test_negative_goes_to_zero(self):
        self.assertEqual(clamp_index(make_pack(), -3), 0)

    def test_upper_bound_is_word_count_not_count_minus_one(self):
        """上界是"词数":next_index == 词数 表示"这一包学到头了"。
        按"词数 - 1"夹的话,这个状态就没地方放。"""
        self.assertEqual(clamp_index(make_pack(), 99), 5)

    def test_inside_range_is_untouched(self):
        self.assertEqual(clamp_index(make_pack(), 3), 3)


class TestStudyRange(unittest.TestCase):
    def test_count_cuts_a_slice(self):
        begin, ids = study_range(make_pack(), 1, 2)
        self.assertEqual(begin, 1)
        self.assertEqual(ids, ["w_1", "w_2"])

    def test_zero_count_means_to_the_end(self):
        begin, ids = study_range(make_pack(), 3, 0)
        self.assertEqual(begin, 3)
        self.assertEqual(ids, ["w_3", "w_4"])

    def test_negative_count_also_means_to_the_end(self):
        """设置里"每次学习数量"填负数没有意义,但也不该把用户卡住。"""
        _begin, ids = study_range(make_pack(), 0, -5)
        self.assertEqual(len(ids), 5)

    def test_count_past_the_end_stops_at_the_end(self):
        # 20 词一轮但只剩 2 个 —— 给 2 个,不是报错也不是补齐
        begin, ids = study_range(make_pack(), 3, 20)
        self.assertEqual((begin, ids), (3, ["w_3", "w_4"]))

    def test_start_past_the_end_gives_an_empty_slice(self):
        begin, ids = study_range(make_pack(), 99, 5)
        self.assertEqual(begin, 5, "起点夹到词数 —— 表示「没有更多了」")
        self.assertEqual(ids, [])

    def test_negative_start_goes_to_the_first_word(self):
        begin, ids = study_range(make_pack(), -1, 2)
        self.assertEqual((begin, ids), (0, ["w_0", "w_1"]))

    def test_empty_pack_is_not_an_error(self):
        self.assertEqual(study_range(make_pack(0), 0, 10), (0, []))


class TestRecordProgress(unittest.TestCase):
    def test_moves_forward(self):
        pack = make_pack()
        record_progress(pack, 3)
        self.assertEqual(pack.progress.next_index, 3)

    def test_never_moves_backward(self):
        """回头复习前面的词不该把进度打回去 —— 这是这个函数存在的全部理由。"""
        pack = make_pack()
        record_progress(pack, 4)
        record_progress(pack, 1)
        self.assertEqual(pack.progress.next_index, 4)

    def test_clamped_at_word_count(self):
        """学完整包时正好等于词数,再往后没有意义。"""
        pack = make_pack()
        record_progress(pack, 999)
        self.assertEqual(pack.progress.next_index, 5)


class TestNoteWords(unittest.TestCase):
    """学习页每评价一屏就调它一次(1.3)。返回值是"下次从第几个接着学"。"""

    def test_advances_past_the_batch(self):
        """评价了第 1..3 个词 → 下次从第 4 个开始。"""
        self.assertEqual(note_words(make_pack(5), 0, words("w_0", "w_1", "w_2")), 3)

    def test_takes_the_farthest_position_not_the_page_order(self):
        """分屏会把同「组合」的词拉到一起,屏序和包里的先后并不一致。
        按最后一个词算(而不是按屏号或列表顺序)才不会一路算到错的词头上。"""
        self.assertEqual(note_words(make_pack(10), 0, words("w_7", "w_2")), 8)

    def test_skipped_words_are_not_counted(self):
        """跳过的那屏不在 words 里 —— 跳过是"我还没准备好评价它",不算学过。"""
        self.assertEqual(note_words(make_pack(10), 5, words("w_5", "w_6")), 7)

    def test_empty_batch_leaves_progress_alone(self):
        self.assertEqual(note_words(make_pack(5), 2, []), 2)

    def test_never_moves_backward(self):
        """回头复习前面的部分不该把进度打回去(与 record_progress 同一条规矩)。"""
        self.assertEqual(note_words(make_pack(10), 8, words("w_0")), 8)

    def test_words_from_another_pack_are_ignored(self):
        """跨来源会话里混着别处的词,只认属于本包的那些。"""
        pack = make_pack(3)
        self.assertEqual(note_words(pack, 0, words("w_0", "别的包的词")), 1)


class TestBookmark(unittest.TestCase):
    def test_default_is_no_bookmark(self):
        self.assertEqual(bookmark_index(make_pack()), -1)

    def test_set_and_read_back(self):
        pack = make_pack()
        set_bookmark(pack, 2)
        self.assertEqual(bookmark_index(pack), 2)

    def test_out_of_range_is_clamped_not_stored(self):
        pack = make_pack()
        set_bookmark(pack, 999)
        self.assertEqual(pack.progress.bookmark, 5)

    def test_clear(self):
        pack = make_pack()
        set_bookmark(pack, 2)
        clear_bookmark(pack)
        self.assertEqual(bookmark_index(pack), -1)

    def test_hand_edited_save_is_clamped_on_read(self):
        """存档是可以被手工改的 —— 与其在每个调用方判断越界,不如读的时候夹一次。"""
        pack = make_pack()
        pack.progress.bookmark = 500
        self.assertEqual(bookmark_index(pack), 5)


class TestProgressLabel(unittest.TestCase):
    def test_positions_are_shown_one_based(self):
        """存的是第 346 个(0 起),界面要说"下次从第 347 个开始"。"""
        pack = make_pack(10)
        record_progress(pack, 3)
        set_bookmark(pack, 2)
        text = progress_label(pack)
        self.assertIn("下次从第 4 个开始", text)
        self.assertIn("标记在第 3 个", text)
        self.assertIn("共 10 个单词", text)

    def test_fresh_pack_only_shows_the_count(self):
        """没进度也没标记时只说词数 —— 一行里塞三个"无"比不提示更迷惑。"""
        text = progress_label(make_pack(7))
        self.assertNotIn("下次从", text)
        self.assertNotIn("标记", text)
        self.assertEqual(text, "共 7 个单词")

    def test_finished_pack_says_so(self):
        pack = make_pack(3)
        record_progress(pack, 3)
        self.assertIn("已经学到头了", progress_label(pack))


if __name__ == "__main__":
    unittest.main(verbosity=2)
