# -*- coding: utf-8 -*-
"""「从哪开始学」弹窗的输入解析测试。

ask_start_point 本体要弹窗,单测碰不了(它走无头冒烟);但数量输入框
背后那个 _parse 是纯函数,而且它兜着"用户手滑"的第一道防线 ——
填错了该退回默认值继续走,而不是把人拦在一个错误框前。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui.study_start import _parse                      # noqa: E402


class TestParse(unittest.TestCase):
    def test_garbage_falls_back_to_default(self):
        self.assertEqual(_parse("abc", 7, 100), 7)
        self.assertEqual(_parse("", 7, 100), 7)
        self.assertEqual(_parse(None, 7, 100), 7)

    def test_clamped_to_total(self):
        """填 9999 不该被骂,夹到词数就行。"""
        self.assertEqual(_parse("9999", 1, 100), 100)

    def test_negative_falls_back(self):
        self.assertEqual(_parse("-3", 5, 100), 5)

    def test_zero_only_when_allowed(self):
        """"学多少个"允许填 0(学到包尾),"从第几个开始"不允许。"""
        self.assertEqual(_parse("0", 5, 100, allow_zero=True), 0)
        self.assertEqual(_parse("0", 5, 100), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
