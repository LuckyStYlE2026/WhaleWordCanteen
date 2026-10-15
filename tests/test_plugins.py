# -*- coding: utf-8 -*-
"""插件加载器测试。

**本文件里最重要的一条是"坏插件不能拖垮程序"。** 插件是别人写的代码,
一定会有人写错 —— 缩进错了、import 了不存在的库、register 里除零。
无论哪种,用户看到的都应该是"这个插件被跳过了",
而不是一个打不开的背单词软件。

其余测试围绕"发现"与"加载"的分离:看一眼有哪些插件,绝不该执行插件代码。
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import plugins, storage                            # noqa: E402
from core.registry import Registry                           # noqa: E402

GOOD_PLUGIN = '''
from pathlib import Path

from core.interfaces import WordPackExporter


class MarkdownExporter(WordPackExporter):
    """把词表导成 Markdown 列表。示例插件的主要产物。"""

    name = "markdown"

    def export(self, words, path):
        target = path.with_suffix(".md")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "\\n".join("- %s: %s" % (word.word, word.translation) for word in words),
            encoding="utf-8")
        return target


def register(registry):
    registry.register_exporter("markdown", MarkdownExporter)
'''

BROKEN_PLUGIN = '''
def register(registry):
    raise RuntimeError("插件作者写错了")
'''

SYNTAX_ERROR_PLUGIN = '''
def register(registry)
    pass          # 少了个冒号
'''


class PluginTestCase(unittest.TestCase):
    """每个测试都在自己的临时数据目录里造插件。"""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="remember_plugins_"))
        self._previous = os.environ.get("REMEMBER_DATA_DIR")
        os.environ["REMEMBER_DATA_DIR"] = str(self.temp_dir)
        self.plugins_root = self.temp_dir / "plugins"
        self.plugins_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        for name in list(sys.modules):
            if name.startswith("remember_plugin_"):
                sys.modules.pop(name, None)
        if self._previous is None:
            os.environ.pop("REMEMBER_DATA_DIR", None)
        else:
            os.environ["REMEMBER_DATA_DIR"] = self._previous
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ---- 造插件 ----------------------------------------------------------

    def write_plugin(self, folder, source, manifest=None, entry="__init__.py"):
        directory = self.plugins_root / folder
        directory.mkdir(parents=True, exist_ok=True)
        if manifest is not None:
            (directory / plugins.MANIFEST_NAME).write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        (directory / entry).write_text(source, encoding="utf-8")
        return directory

    def manifest(self, name=None, **overrides):
        data = {"name": name, "version": "1.0", "author": "测试",
                "api_version": plugins.API_VERSION, "entry": "__init__"}
        data.update(overrides)
        return data

    def find(self, infos, name):
        for info in infos:
            if info.name == name:
                return info
        self.fail("没有找到插件 %r" % name)

    def log_text(self):
        log = storage.logs_dir() / "errors.log"
        return log.read_text(encoding="utf-8") if log.exists() else ""


# --------------------------------------------------------------------------
# 发现:只读清单,绝不执行代码
# --------------------------------------------------------------------------

class TestDiscovery(PluginTestCase):

    def test_empty_directory_yields_nothing(self):
        self.assertEqual(plugins.discover(), [])

    def test_missing_directory_yields_nothing(self):
        shutil.rmtree(self.plugins_root)
        self.assertEqual(plugins.discover(), [])

    def test_reads_manifest_fields(self):
        self.write_plugin("demo", GOOD_PLUGIN,
                          self.manifest(name="demo", version="2.1", author="某人"))
        info = self.find(plugins.discover(), "demo")
        self.assertEqual(info.version, "2.1")
        self.assertEqual(info.author, "某人")

    def test_folder_name_is_the_fallback_name(self):
        self.write_plugin("noname", GOOD_PLUGIN, {"api_version": 1})
        self.assertEqual(self.find(plugins.discover(), "noname").name, "noname")

    def test_discovery_does_not_execute_plugin_code(self):
        """看一眼有哪些插件,这件事必须绝对安全。

        所以 discover() 只读清单,不 import 任何东西 —— 否则打开插件列表
        就会执行别人的代码,而那个代码可能是坏的。
        """
        self.write_plugin("danger", "raise RuntimeError('被 import 了!')",
                          self.manifest(name="danger"))
        plugins.discover()
        self.assertNotIn("remember_plugin_danger", sys.modules)

    def test_internal_folders_are_ignored(self):
        (self.plugins_root / "__pycache__").mkdir()
        (self.plugins_root / "_hidden").mkdir()
        (self.plugins_root / ".git").mkdir()
        (self.plugins_root / "a_file.txt").write_text("x", encoding="utf-8")
        self.assertEqual(plugins.discover(), [])

    def test_code_without_a_manifest_gets_a_clear_complaint(self):
        """插件作者忘了写清单时会一直困惑"为什么我的插件不生效",
        所以要明确告诉他缺了什么。"""
        self.write_plugin("forgot", GOOD_PLUGIN, manifest=None)
        info = self.find(plugins.discover(), "forgot")
        self.assertIn(plugins.MANIFEST_NAME, info.error)

    def test_broken_manifest_is_treated_as_missing(self):
        directory = self.write_plugin("badjson", GOOD_PLUGIN, manifest=None)
        (directory / plugins.MANIFEST_NAME).write_text("{ 这不是 json", encoding="utf-8")
        info = self.find(plugins.discover(), "badjson")
        self.assertTrue(info.error)


# --------------------------------------------------------------------------
# 加载:好的应该能用
# --------------------------------------------------------------------------

class TestGoodPlugin(PluginTestCase):

    def test_a_working_plugin_registers_its_export_point(self):
        self.write_plugin("demo", GOOD_PLUGIN, self.manifest(name="demo"))
        target = Registry()
        infos = plugins.load_all(target)

        info = self.find(infos, "demo")
        self.assertTrue(info.loaded)
        self.assertEqual(info.error, "")
        self.assertIn("markdown", target.exporters.names())

    def test_the_registered_exporter_actually_works(self):
        """接缝是通的 —— 注册进去的东西真的能拿来用。"""
        from core.models import Word
        self.write_plugin("demo", GOOD_PLUGIN, self.manifest(name="demo"))
        target = Registry()
        plugins.load_all(target)

        words = [Word(id="w_1", spelling_key="bank", word="bank", translation="银行")]
        written = target.get_exporter("markdown").export(words, self.temp_dir / "out")
        self.assertTrue(written.exists())
        self.assertIn("bank", written.read_text(encoding="utf-8"))

    def test_plugin_named_after_stdlib_does_not_hijack_it(self):
        """给插件文件夹起名叫 json 不能把标准库顶掉。

        这不是假想问题 —— 用户给文件夹起什么名字都有可能,
        而模块名冲突的后果(整个程序悄悄用错模块)极难排查。
        """
        import json as real_json
        self.write_plugin("json", GOOD_PLUGIN, self.manifest(name="json"))
        plugins.load_all(Registry())

        self.assertIs(sys.modules["json"], real_json)
        self.assertEqual(real_json.loads('{"a": 1}'), {"a": 1})

    def test_plugin_using_a_sidecar_module_file(self):
        self.write_plugin("side", "def register(registry):\n    registry.register_judge('x', object)\n",
                          self.manifest(name="side", entry="plugin.py"), entry="plugin.py")
        info = self.find(plugins.load_all(Registry()), "side")
        self.assertTrue(info.loaded)


# --------------------------------------------------------------------------
# 加载:坏的必须被隔离 ← 本文件最重要的一组
# --------------------------------------------------------------------------

class TestBrokenPluginsAreIsolated(PluginTestCase):

    def test_a_plugin_that_raises_does_not_stop_startup(self):
        self.write_plugin("good", GOOD_PLUGIN, self.manifest(name="good"))
        self.write_plugin("bad", BROKEN_PLUGIN, self.manifest(name="bad"))

        target = Registry()
        infos = plugins.load_all(target)          # ← 这一行不该抛异常

        self.assertTrue(self.find(infos, "good").loaded, "好插件应该照常加载")
        self.assertFalse(self.find(infos, "bad").loaded)
        self.assertIn("插件作者写错了", self.find(infos, "bad").error)
        self.assertIn("markdown", target.exporters.names())

    def test_a_plugin_with_a_syntax_error_is_isolated(self):
        self.write_plugin("good", GOOD_PLUGIN, self.manifest(name="good"))
        self.write_plugin("typo", SYNTAX_ERROR_PLUGIN, self.manifest(name="typo"))

        infos = plugins.load_all(Registry())
        self.assertTrue(self.find(infos, "good").loaded)
        self.assertIn("SyntaxError", self.find(infos, "typo").error)

    def test_a_plugin_that_imports_a_missing_library_is_isolated(self):
        self.write_plugin("nope", "import 根本不存在的库\n"
                          "def register(registry):\n    pass\n",
                          self.manifest(name="nope"))
        info = self.find(plugins.load_all(Registry()), "nope")
        # ModuleNotFoundError 是 ImportError 的子类,两种都算合理;
        # 关键是报错里要能看出缺的是哪个库
        self.assertIn("根本不存在的库", info.error)

    def test_a_plugin_without_register_is_reported(self):
        self.write_plugin("empty", "VALUE = 1\n", self.manifest(name="empty"))
        info = self.find(plugins.load_all(Registry()), "empty")
        self.assertIn("register", info.error)

    def test_a_plugin_with_a_broken_entry_file_is_reported(self):
        self.write_plugin("ghost", "", self.manifest(name="ghost", entry="missing.py"),
                          entry="missing.py")
        info = self.find(plugins.load_all(Registry()), "ghost")
        self.assertTrue(info.error)

    def test_failures_are_written_to_the_log(self):
        """用户不该靠猜 —— 出问题的插件必须在日志里留下痕迹。"""
        self.write_plugin("bad", BROKEN_PLUGIN, self.manifest(name="bad"))
        plugins.load_all(Registry())
        self.assertIn("插件作者写错了", self.log_text())

    def test_a_failed_module_is_not_left_in_the_module_cache(self):
        """半成品模块留在 sys.modules 里,别的插件可能拿到一个残缺的东西。"""
        self.write_plugin("bad", BROKEN_PLUGIN, self.manifest(name="bad"))
        plugins.load_all(Registry())
        self.assertNotIn("remember_plugin_bad", sys.modules)

    def test_a_plugin_that_duplicates_a_name_is_rejected(self):
        """两个插件抢同一个扩展点名字是真实的 bug,应该立刻暴露。"""
        source = ("def register(registry):\n"
                  "    registry.register_exporter('clash', object)\n")
        self.write_plugin("first", source, self.manifest(name="first"))
        self.write_plugin("second", source, self.manifest(name="second"))

        infos = plugins.load_all(Registry())
        self.assertTrue(self.find(infos, "first").loaded)
        self.assertIn("DuplicateNameError", self.find(infos, "second").error)

    def test_every_broken_plugin_is_still_listed_in_the_ui(self):
        """出错也要出现在列表里,不然用户会以为插件没被装上。"""
        self.write_plugin("bad", BROKEN_PLUGIN, self.manifest(name="bad"))
        info = self.find(plugins.load_all(Registry()), "bad")
        self.assertEqual(info.status, "出错")


# --------------------------------------------------------------------------
# 接口版本与开关
# --------------------------------------------------------------------------

class TestVersionAndToggle(PluginTestCase):

    def test_a_plugin_for_a_newer_api_is_refused_clearly(self):
        """版本对不上时要明确拒绝,而不是以一种说不清的方式出错。"""
        self.write_plugin("future", GOOD_PLUGIN,
                          self.manifest(name="future", api_version=plugins.API_VERSION + 1))
        info = self.find(plugins.load_all(Registry()), "future")
        self.assertFalse(info.loaded)
        self.assertIn("接口版本", info.error)

    def test_a_disabled_plugin_is_skipped(self):
        self.write_plugin("off", GOOD_PLUGIN, self.manifest(name="off"))
        storage.save_plugin_state({"off": {"enabled": False}})

        target = Registry()
        info = self.find(plugins.load_all(target), "off")
        self.assertFalse(info.loaded)
        self.assertFalse(info.enabled)
        self.assertNotIn("markdown", target.exporters.names())

    def test_disabled_plugin_is_not_an_error(self):
        self.write_plugin("off", GOOD_PLUGIN, self.manifest(name="off"))
        storage.save_plugin_state({"off": {"enabled": False}})
        info = self.find(plugins.load_all(Registry()), "off")
        self.assertEqual(info.status, "已停用")

    def test_toggling_persists_across_discovery(self):
        self.write_plugin("demo", GOOD_PLUGIN, self.manifest(name="demo"))
        info = self.find(plugins.discover(), "demo")
        self.assertTrue(info.enabled)

        plugins.set_enabled(info, False)
        self.assertFalse(self.find(plugins.discover(), "demo").enabled)

        plugins.set_enabled(info, True)
        self.assertTrue(self.find(plugins.discover(), "demo").enabled)

    def test_toggle_only_touches_the_targeted_plugin(self):
        self.write_plugin("a", GOOD_PLUGIN, self.manifest(name="a"))
        self.write_plugin("b", GOOD_PLUGIN, self.manifest(name="b"))
        plugins.set_enabled(self.find(plugins.discover(), "a"), False)

        self.assertFalse(self.find(plugins.discover(), "a").enabled)
        self.assertTrue(self.find(plugins.discover(), "b").enabled)


IMPORTER_PLUGIN = '''
from core.interfaces import ImportResult, RawWord, RowError, WordPackImporter


class MyWordsImporter(WordPackImporter):
    # 认识 .mywords 文件:每行 "拼写|释义"
    name = "mywords"

    def can_handle(self, path):
        return path.suffix.lower() == ".mywords"

    def load(self, path):
        result = ImportResult(format=self.name)
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            parts = line.split("|")
            if len(parts) != 2:
                result.errors.append(RowError(number, line, "要用 | 分成两段"))
                continue
            result.words.append(RawWord(word=parts[0].strip(),
                                        translation=parts[1].strip(),
                                        source_line=number))
        return result


def register(registry):
    registry.register_importer(MyWordsImporter.name, MyWordsImporter)
'''


# --------------------------------------------------------------------------
# 接缝是通的:插件注册的格式真的会被用到
# --------------------------------------------------------------------------

class TestImportExportSeamIsLive(PluginTestCase):
    """注册进注册表还不够 —— 得真的被用上。

    这一组测试存在的理由:内置的导入导出曾经是写死的(直接调 CsvExporter、
    遍历一个常量元组),注册表里那两条路只有插件会走。那样的接缝迟早会在
    没人写插件的时候悄悄坏掉,而坏的当天不会有任何测试变红。
    所以这里断言的是"界面能看到的列表"和"真的会走的那条路"。
    """

    def fresh_registry(self):
        """一个装了全部内置实现的新注册表。

        register_builtins 传了 target 就会往那个注册表里登记,
        所以每个测试都能拿到互相隔离的一份 —— 不会污染全局单例。
        """
        from core.builtins import register_builtins
        target = Registry()
        register_builtins(target)
        return target

    def test_plugin_exporter_joins_the_builtin_ones_in_the_list(self):
        from core.wordpack_export import available_exporters
        target = self.fresh_registry()
        self.write_plugin("demo", GOOD_PLUGIN, self.manifest(name="demo"))
        plugins.load_all(target)

        names = [name for _label, name in available_exporters(target)]
        self.assertIn("csv", names)             # 内置的还在
        self.assertIn("json", names)
        self.assertIn("markdown", names)        # 插件的也进来了

    def test_every_listed_format_can_actually_write(self):
        from core.wordpack_export import available_exporters, export_with
        from core.models import Word
        target = self.fresh_registry()
        self.write_plugin("demo", GOOD_PLUGIN, self.manifest(name="demo"))
        plugins.load_all(target)

        words = [Word(id="w_1", spelling_key="bank", word="bank",
                      translation="n. 银行")]
        for _label, name in available_exporters(target):
            written = export_with(words, name, self.temp_dir / name, target)
            self.assertTrue(written.exists(), "%s 没写出文件" % name)
            self.assertIn("bank", written.read_text(encoding="utf-8"))

    def test_export_all_writes_one_file_per_format(self):
        from core.wordpack_export import export_all
        from core.models import Word
        target = self.fresh_registry()
        self.write_plugin("demo", GOOD_PLUGIN, self.manifest(name="demo"))
        plugins.load_all(target)

        written = export_all([Word(id="w_1", spelling_key="bank",
                                   word="bank", translation="n. 银行")],
                             self.temp_dir / "out", target)
        self.assertEqual(len(written), 3)       # csv + json + markdown

    def test_plugin_importer_gets_a_turn_before_the_catch_all(self):
        """插件导入器必须排在兜底的 plain 前面。

        plain 的 can_handle 永远返回 True(它什么都认),排它后面
        等于插件注册的格式永远不会被问到 —— 而且是那种"注册成功了、
        日志里没有错、就是不起作用"的失败,最难排查。
        """
        from core.wordpack_import import import_file
        target = self.fresh_registry()
        self.write_plugin("mywords", IMPORTER_PLUGIN, self.manifest(name="mywords"))
        plugins.load_all(target)

        path = self.temp_dir / "custom.mywords"
        path.write_text("atmosphere|n. 大气层\ncrust|n. 地壳\n", encoding="utf-8")

        result = import_file(path, target)
        self.assertEqual(result.format, "mywords")
        self.assertEqual([w.word for w in result.words], ["atmosphere", "crust"])
        self.assertEqual(result.words[0].translation, "n. 大气层")

    def test_builtin_detection_still_wins_for_txt_files(self):
        """插件插进来不能把内置格式挤掉。"""
        from core.wordpack_import import detect_format
        from core.importers import PlainTextImporter
        target = self.fresh_registry()
        self.write_plugin("mywords", IMPORTER_PLUGIN, self.manifest(name="mywords"))
        plugins.load_all(target)

        path = self.temp_dir / "plain.txt"
        path.write_text("atmosphere\tn. 大气层\n", encoding="utf-8")
        # .txt 不是 .mywords,插件不该抢;落到兜底的 plain
        self.assertIsInstance(detect_format(path, target), PlainTextImporter)


if __name__ == "__main__":
    unittest.main(verbosity=2)
