# -*- coding: utf-8 -*-
"""检查"用了但没定义"的名字。

**为什么要单独有这个检查。** 清理 import 时很容易顺手删掉一个还在用的名字
(这一版就发生了:`ui/views/study_pick.py` 的 `PACK_TYPE_VOCAB` 被删掉,
用户一点「开始学习」就 NameError)。而未定义的名字是**崩溃**,不是邋遢 ——
单元测试没覆盖到的分支会带着它直接上线。

实现:拿每个模块的 AST 走一遍,凡是 Load 的 Name,既不在本模块的顶层
命名空间、也不在所处的函数 / 类作用域、也不是内置名,就报出来。

用法::

    python tools/check_names.py          # 扫 ui/ core/ plugins/ main.py
    python tools/check_names.py 某个.py  # 只扫指定文件
"""

import ast
import builtins
import pathlib
import sys

SKIP_PARTS = ("__pycache__",)
DEFAULT_ROOTS = ("ui", "core", "plugins")

# 这些名字由运行时注入,静态看不出来
EXTRA_BUILTINS = {"__file__", "__name__", "__doc__", "self", "cls",
                  "__class__", "__spec__", "__package__", "__builtins__"}


def _module_names(tree) -> set:
    """模块顶层定义了哪些名字。

    ⚠️ **要钻进 try/except 里看。** 顶层那种"可用就 import、不可用就置 None"
    的写法(`try: import requests / except ImportError: requests = None`)
    是常见写法,只扫最外层语句会把它误报成未定义。
    """
    names = set()

    def walk_statements(statements):
        for node in statements:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    names.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                   ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in ast.walk(node):
                    if isinstance(target, ast.Name) and \
                            isinstance(target.ctx, ast.Store):
                        names.add(target.id)
            elif isinstance(node, ast.AnnAssign) and \
                    isinstance(node.target, ast.Name):
                names.add(node.target.id)
            elif isinstance(node, ast.Global):
                names.update(node.names)
            elif isinstance(node, ast.Try):
                # 尝试、兜底、以及 finally 里定义的都算
                walk_statements(node.body)
                for handler in node.handlers:
                    walk_statements(handler.body)
                walk_statements(node.orelse)
                walk_statements(node.finalbody)
            elif isinstance(node, (ast.If, ast.With, ast.AsyncWith)):
                walk_statements(getattr(node, "body", []))
                walk_statements(getattr(node, "orelse", []))
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                walk_statements(node.body)
                walk_statements(node.orelse)

    walk_statements(tree.body)
    return names


def _scope_names(node) -> set:
    """这个函数 / 类内部又定义了哪些名字。"""
    found = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.arg):
            found.add(sub.arg)
        elif isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
            found.add(sub.id)
        elif isinstance(sub, (ast.Import, ast.ImportFrom)):
            for alias in sub.names:
                found.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(sub, ast.ExceptHandler) and sub.name:
            found.add(sub.name)
        elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.add(sub.name)
    return found


def check_file(path) -> list:
    """返回 ["文件:行 未定义 '名字'"] 形式的清单。"""
    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    module = _module_names(tree)
    known = set(dir(builtins)) | EXTRA_BUILTINS
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        scope = module | _scope_names(node)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                if sub.id not in scope and sub.id not in known:
                    hits.append("%s:%d  未定义 %r(在 %s 里)"
                                % (path, sub.lineno, sub.id, node.name))
    return hits


def main(argv) -> int:
    if len(argv) > 1:
        targets = [pathlib.Path(arg) for arg in argv[1:]]
    else:
        targets = [path
                   for root in DEFAULT_ROOTS
                   for path in sorted(pathlib.Path(root).rglob("*.py"))]
        targets.append(pathlib.Path("main.py"))

    problems = []
    scanned = 0
    for path in targets:
        if any(part in SKIP_PARTS for part in path.parts) or not path.exists():
            continue
        scanned += 1
        problems.extend(check_file(path))

    if problems:
        print("\n".join(problems))
        print("\n共 %d 处 —— 这些都会在运行到那一行时抛 NameError。" % len(problems))
        return 1
    print("没有未定义的名字(扫了 %d 个文件)" % scanned)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
