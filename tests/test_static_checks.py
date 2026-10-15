# -*- coding: utf-8 -*-
"""静态检查:不许有"用了但没定义"的名字。

**为什么值得一个测试。** 用户实测撞上过一次:清理 import 时顺手删掉了
`ui/views/study_pick.py` 里还在用的 `PACK_TYPE_VOCAB`,于是一点
「开始学习」就 `NameError` —— 而**单元测试是绿的**,因为没有任何用例
走到那条分支。

未定义的名字是**崩溃**,不是邋遢;而它恰好生在测试覆盖不到的地方
(用户点出来的路径)。所以这里用静态检查兜住:AST 走一遍,凡是 Load 的
Name,既不在模块命名空间、也不在所处作用域、也不是内置名,就失败。

检查器本身在 tools/check_names.py(所以也能当命令行工具用:
`python tools/check_names.py`)。
"""

import pathlib
import sys
import unittest

# 让 tools/ 能被 import(它就在仓库里,不是第三方包)
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.check_names import check_file, DEFAULT_ROOTS  # noqa: E402


class NoUndefinedNamesTest(unittest.TestCase):
    """整个 ui/ core/ plugins/ 和 main.py 都不许有未定义的名字。"""

    def test_the_checker_actually_catches_a_missing_import(self):
        """先证明这个检查器有用 —— 检查器自己失效的话,下面那条测试就是摆设。

        做法:拿一个真的文件,把它的一个 import 拿掉,结果必须报出来。
        """
        source = ROOT / "ui" / "views" / "study_pick.py"
        self.assertTrue(source.exists())
        text = source.read_text(encoding="utf-8")
        broken = text.replace("from core.packs import PACK_TYPE_VOCAB\n", "")
        self.assertNotEqual(broken, text, "这个文件已经不用 PACK_TYPE_VOCAB 了,换一个")

        temp = ROOT / "ui" / "views" / "_undefined_name_probe.py"
        temp.write_text(broken, encoding="utf-8")
        try:
            hits = check_file(temp)
        finally:
            temp.unlink()
        self.assertTrue(hits, "拿掉 import 之后检查器没报出来 —— 它失效了")
        self.assertTrue(any("PACK_TYPE_VOCAB" in hit for hit in hits))

    def test_no_file_has_undefined_names(self):
        targets = [path
                   for root in DEFAULT_ROOTS
                   for path in sorted((ROOT / root).rglob("*.py"))]
        targets.append(ROOT / "main.py")

        problems = []
        for path in targets:
            if "__pycache__" in path.parts or not path.exists():
                continue
            problems.extend(check_file(path))

        self.assertEqual(problems, [],
                         "这些名字没有定义,运行到那一行就会 NameError:\n%s"
                         % "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
