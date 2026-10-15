# -*- coding: utf-8 -*-
"""地基测试:数据模型、词包、注册表、设置、存储、AI 形象。

这些是整个项目后面所有功能的地基,所以测试写得比较密。
重点验证三件事:
  1. 所有模型 to_dict / from_dict 往返无损(存档不会悄悄丢数据)
  2. 缺字段 / 损坏文件时程序不崩溃(单机软件的健壮性底线)
  3. 注册表的默认项与重名检测按预期工作(插件系统的地基)
"""

import os
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

# 让测试可以直接 python -m unittest 运行,不必先设 PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import characters, storage                        # noqa: E402
from core.config import (                                   # noqa: E402
    RESULT_PACK_ASK,
    RESULT_PACK_MERGE,
    Settings,
)
from core.interfaces import LinePack                        # noqa: E402
from core.interfaces import JudgeItem, JudgeResult, Turn    # noqa: E402
from core.models import (                                   # noqa: E402
    BUCKET_NEW,
    Grade,
    HistoryEntry,
    Mastery,
    Word,
    WordState,
)
from core.packs import (                                    # noqa: E402
    PACK_TYPE_STUDY,
    PACK_TYPE_VOCAB,
    ExamResult,
    PackSchedule,
    SessionRecord,
    WordPack,
    make_vocab_pack,
)
from core.registry import DuplicateNameError, Registry      # noqa: E402


class RoundTripMixin:
    """给 dataclass 模型提供统一的往返断言。"""

    def assert_round_trip(self, obj):
        restored = type(obj).from_dict(obj.to_dict())
        self.assertEqual(restored.to_dict(), obj.to_dict())


class TestWordModels(unittest.TestCase, RoundTripMixin):
    def test_word_state_round_trip(self):
        state = WordState(mastery=Mastery.FUZZY, box=3, interval_days=7,
                          next_review="2026-10-20", wrong_count=2)
        state.append_history("2026-10-12", Grade.WRONG)
        self.assert_round_trip(state)

    def test_word_round_trip_with_chinese(self):
        word = Word(id="w_1", spelling_key="atmosphere", word="atmosphere",
                    translation="n. 大气层, 大气圈; 气氛",
                    example="The atmosphere is thick.", group="1")
        word.state.mastery = Mastery.KNOWN
        self.assert_round_trip(word)
        # 中文必须原样往返,不能被转义
        self.assertEqual(word.to_dict()["translation"], "n. 大气层, 大气圈; 气氛")

    def test_missing_fields_fall_back_to_defaults(self):
        """老存档缺字段也要能读进来 —— 这是向前兼容的关键。"""
        sparse = {"id": "w_1", "spelling_key": "bank", "word": "bank",
                  "translation": "n. 银行"}
        word = Word.from_dict(sparse)
        self.assertEqual(word.phonetic, "")
        self.assertEqual(word.state.mastery, Mastery.NEW)
        self.assertEqual(word.state.bucket, BUCKET_NEW)
        self.assertEqual(word.state.ease, 2.5)

    def test_history_ring_buffer_is_capped(self):
        """历史记录必须被截断,否则存档会无限膨胀。"""
        state = WordState()
        for index in range(WordState.HISTORY_LIMIT + 15):
            state.append_history("2026-10-%02d" % ((index % 28) + 1), Grade.CORRECT)
        self.assertEqual(len(state.history), WordState.HISTORY_LIMIT)

    def test_append_history_does_not_touch_counters(self):
        """append_history 只写历史,计数器归 scheduler 管。

        这条测试是刻意的:如果哪天有人图省事让 append_history 顺手改计数器,
        状态就会被两处代码分别改写,迟早对不上。
        """
        state = WordState()
        state.append_history("2026-10-12", Grade.WRONG)
        self.assertEqual(state.wrong_count, 0)
        self.assertEqual(state.review_count, 0)

    def test_is_mistake_rule(self):
        cases = [
            (2, 5, True),    # 错过两次 —— 进了错题本
            (1, 0, True),    # 错过一次且还没连对 —— 也算
            (1, 1, False),   # 错过一次但已经连对上了 —— 放它一马
            (0, 0, False),   # 从没错过
        ]
        for wrong, streak, expected in cases:
            state = WordState(wrong_count=wrong, streak_correct=streak)
            self.assertEqual(state.is_mistake(), expected,
                             "wrong_count=%d streak=%d" % (wrong, streak))

    def test_is_graduated(self):
        self.assertFalse(WordState(streak_correct=2).is_graduated(3))
        self.assertTrue(WordState(streak_correct=3).is_graduated(3))

    def test_judge_result_is_correct(self):
        self.assertTrue(JudgeResult(Grade.CORRECT, 1.0).is_correct)
        self.assertFalse(JudgeResult(Grade.FUZZY, 0.7).is_correct)

    def test_judge_and_turn_are_plain_containers(self):
        item = JudgeItem(word_id="w_1", word="bank", translation="银行", answer="银行")
        self.assertEqual(item.answer, "银行")
        self.assertEqual(Turn(role="user", content="你好").role, "user")

    def test_history_entry_uses_short_json_keys(self):
        entry = HistoryEntry(day="2026-10-12", result=Grade.CORRECT)
        self.assertEqual(entry.to_dict(), {"t": "2026-10-12", "r": "correct"})


class TestPackModels(unittest.TestCase, RoundTripMixin):
    def test_pack_round_trip(self):
        pack = WordPack(
            id="pack_20261012_001", pack_type=PACK_TYPE_STUDY,
            title="2026-10-12 学习词包", created_at="2026-10-12",
            word_ids=["w_1", "w_2"], source_mode="sequential",
            schedule=PackSchedule(recommended_next="2026-10-13",
                                  sessions=[SessionRecord(day="2026-10-12", on_time=True,
                                                          correct=8, wrong=2)]),
            exam=ExamResult(known=["w_1"], newly=["w_2"], wrong_ids=["w_2"],
                            score=0.5, taken_at="2026-10-12"),
            mistakes=["w_2"],
        )
        self.assert_round_trip(pack)
        self.assertEqual(pack.word_count, 2)

    def test_word_count_is_derived_not_stored(self):
        """word_count 必须由 word_ids 算出来,不能各存一份。

        存两份就有"数字和列表对不上"的风险,这是最难查的一类 bug。
        """
        payload = WordPack(id="p", pack_type=PACK_TYPE_STUDY, title="t",
                           created_at="2026-10-12", word_ids=["a", "b", "c"]).to_dict()
        # 就算 JSON 里的 word_count 是错的,读回来的也是对的
        payload["word_count"] = 999
        self.assertEqual(WordPack.from_dict(payload).word_count, 3)

    def test_exam_result_new_key_maps_to_newly(self):
        """JSON 里用 "new" 作键(贴合规格用词),Python 属性叫 newly 避开内置名。"""
        payload = ExamResult(newly=["w_9"]).to_dict()
        self.assertIn("new", payload)
        self.assertEqual(payload["new"], ["w_9"])
        self.assertEqual(ExamResult.from_dict(payload).newly, ["w_9"])

    def test_pack_without_exam_round_trips(self):
        pack = WordPack(id="p", pack_type=PACK_TYPE_STUDY, title="t",
                        created_at="2026-10-12", word_ids=["a"])
        self.assertIsNone(WordPack.from_dict(pack.to_dict()).exam)

    def test_pack_progress_round_trips(self):
        pack = make_vocab_pack("pack_a", "甲", ["w_1", "w_2"], "2026-10-12")
        pack.progress.next_index = 2
        pack.progress.bookmark = 1
        self.assert_round_trip(pack)

    def test_pack_progress_defaults_when_missing(self):
        """v1.3 之前的存档没有 progress 这个键 ——
        读回来必须是"从头开始、没标记过",而不是报错或 None。"""
        pack = WordPack.from_dict({"id": "p", "pack_type": PACK_TYPE_VOCAB})
        self.assertEqual(pack.progress.next_index, 0)
        self.assertEqual(pack.progress.bookmark, -1)


class TestRegistry(unittest.TestCase):
    class _Fake:
        pass

    def test_first_registration_becomes_default(self):
        registry = Registry()
        registry.register_judge("offline", self._Fake)
        registry.register_judge("api", self._Fake)
        self.assertEqual(registry.judges.default_name(), "offline")
        self.assertIsInstance(registry.get_judge(), self._Fake)

    def test_explicit_default_wins(self):
        registry = Registry()
        registry.register_judge("a", self._Fake)
        registry.register_judge("b", self._Fake, is_default=True)
        self.assertEqual(registry.judges.default_name(), "b")

    def test_duplicate_name_is_rejected(self):
        """两个插件抢同一个名字必须立刻报错,而不是静默覆盖。

        静默覆盖的表现是"某个插件莫名其妙不生效",极难排查。
        """
        registry = Registry()
        registry.register_judge("offline", self._Fake)
        with self.assertRaises(DuplicateNameError):
            registry.register_judge("offline", self._Fake)

    def test_replace_flag_allows_override(self):
        """插件想替换内置实现时,显式传 replace=True 即可。"""
        registry = Registry()
        registry.register_judge("offline", self._Fake)
        registry.register_judge("offline", self._Fake, replace=True)
        self.assertEqual(registry.judges.names(), ["offline"])

    def test_unknown_name_raises_key_error(self):
        with self.assertRaises(KeyError):
            Registry().get_judge("nope")

    def test_all_extension_points_are_wired(self):
        """七个扩展点都要能用,漏掉一个插件系统就缺一块。"""
        registry = Registry()
        registry.register_judge("j", self._Fake)
        registry.register_scheduler("s", self._Fake)
        registry.register_ai_provider("a", self._Fake)
        registry.register_importer("i", self._Fake)
        registry.register_exporter("e", self._Fake)
        registry.register_linepack("l", LinePack(name="l"))
        registry.register_view("v", self._Fake)
        for slot in (registry.judges, registry.schedulers, registry.ai_providers,
                     registry.importers, registry.exporters, registry.linepacks,
                     registry.views):
            self.assertEqual(len(slot.names()), 1, slot.kind)

    def test_linepack_lookup_falls_back_by_emotion(self):
        pack = LinePack(name="t", lines={
            "correct:happy": ["太棒了!"],
            "wrong:normal": ["再想想~"],
        })
        self.assertEqual(pack.lookup("correct", "happy"), ["太棒了!"])
        # wrong 没有 sad 变体 → 回退到 wrong:normal
        self.assertEqual(pack.lookup("wrong", "sad"), ["再想想~"])
        # 完全没写的类别 → 空列表,由调用方决定兜底
        self.assertEqual(pack.lookup("fuzzy", "thinking"), [])


class TestSettings(unittest.TestCase):
    def test_defaults(self):
        settings = Settings()
        self.assertTrue(settings.study.force_semantic_match)
        self.assertFalse(settings.ai.enabled)
        self.assertFalse(settings.ai.is_configured)
        self.assertEqual(settings.study.max_api_calls_per_session, 20)

    def test_ai_configured_requires_all_three_fields(self):
        settings = Settings()
        settings.ai.enabled = True
        self.assertFalse(settings.ai.is_configured, "只填 enabled 不算配好")
        settings.ai.base_url = "https://api.example.com/v1"
        settings.ai.model = "some-model"
        self.assertFalse(settings.ai.is_configured, "还缺 api_key")
        settings.ai.api_key = "sk-x"
        self.assertTrue(settings.ai.is_configured)

    def test_missing_fields_fall_back_to_defaults(self):
        settings = Settings.from_dict({"study": {"exam_size": 7}})
        self.assertEqual(settings.study.exam_size, 7)
        self.assertEqual(settings.study.daily_due_limit, 50)
        self.assertEqual(settings.ui.language, "zh-CN")

    def test_study_batch_and_result_pack_defaults(self):
        """老存档里没有这两项(1.3 才加的),必须取默认值而不是 None ——
        result_pack_mode 是 None 的话,收尾时会当成"没配好",每场都弹窗。"""
        settings = Settings.from_dict({"study": {}})
        self.assertEqual(settings.study.batch_size, 20)
        self.assertEqual(settings.study.result_pack_mode, RESULT_PACK_ASK)

    def test_study_batch_and_result_pack_round_trip(self):
        settings = Settings()
        settings.study.batch_size = 0
        settings.study.result_pack_mode = RESULT_PACK_MERGE
        restored = Settings.from_dict(settings.to_dict())
        self.assertEqual(restored.study.batch_size, 0)
        self.assertEqual(restored.study.result_pack_mode, RESULT_PACK_MERGE)

    def test_resolution_accepts_list_and_dict(self):
        from_list = Settings.from_dict({"ui": {"resolution": [800, 600]}})
        self.assertEqual((from_list.ui.width, from_list.ui.height), (800, 600))
        from_dict = Settings.from_dict({"ui": {"resolution": {"width": 1024, "height": 768}}})
        self.assertEqual((from_dict.ui.width, from_dict.ui.height), (1024, 768))

    def test_round_trip(self):
        settings = Settings()
        settings.ai.enabled = True
        settings.ai.api_key = "sk-secret"
        settings.ui.width, settings.ui.height = 1920, 1080
        restored = Settings.from_dict(settings.to_dict())
        self.assertEqual(restored.to_dict(), settings.to_dict())
        self.assertEqual(restored.ai.api_key, "sk-secret")


class TestStorage(unittest.TestCase):
    """存储测试全部指向临时目录,不碰真实存档。"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="remember_test_")
        os.environ["REMEMBER_DATA_DIR"] = self.temp_dir
        storage.bootstrap()

    def tearDown(self):
        os.environ.pop("REMEMBER_DATA_DIR", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_bootstrap_creates_directories(self):
        self.assertTrue(storage.save_dir().exists())
        self.assertTrue(storage.packs_dir().exists())
        self.assertTrue(storage.logs_dir().exists())
        self.assertTrue(storage.settings_path().exists())

    def test_bootstrap_is_idempotent(self):
        storage.bootstrap()
        storage.bootstrap()
        self.assertTrue(storage.save_dir().exists())

    def test_data_root_follows_env_override(self):
        self.assertEqual(storage.data_root(), Path(self.temp_dir).resolve())

    def test_settings_round_trip(self):
        settings = storage.load_settings()
        settings.ai.api_key = "sk-secret"
        settings.ai.enabled = True
        storage.save_settings(settings)
        self.assertEqual(storage.load_settings().ai.api_key, "sk-secret")

    def test_words_round_trip_preserves_chinese(self):
        word = Word(id="w_1", spelling_key="atmosphere", word="atmosphere",
                    translation="n. 大气层, 大气圈; 气氛")
        word.state.mastery = Mastery.FUZZY
        storage.save_words({"w_1": word})

        restored = storage.load_words()
        self.assertEqual(restored["w_1"].translation, "n. 大气层, 大气圈; 气氛")
        self.assertEqual(restored["w_1"].state.mastery, Mastery.FUZZY)

    def test_chinese_is_stored_readably_not_escaped(self):
        """存档是给用户看得懂的,不能被存成 \\uXXXX 转义序列。"""
        storage.save_words({"w_1": Word(id="w_1", spelling_key="a", word="a",
                                        translation="大气层")})
        raw = storage.words_path().read_text(encoding="utf-8")
        self.assertIn("大气层", raw)
        self.assertNotIn("\\u5927", raw)

    def test_corrupt_file_does_not_crash(self):
        """存档损坏时必须能继续启动,大不了从头开始 —— 不能直接崩。"""
        storage.words_path().write_text("{ 这不是合法的 JSON", encoding="utf-8")
        self.assertEqual(storage.load_words(), {})

    def test_corrupt_settings_falls_back_to_default(self):
        storage.settings_path().write_text("!!!", encoding="utf-8")
        self.assertTrue(storage.load_settings().study.force_semantic_match)

    def test_corrupt_pack_is_skipped_but_others_survive(self):
        good = WordPack(id="pack_20261012_001", pack_type=PACK_TYPE_STUDY,
                        title="好的", created_at="2026-10-12", word_ids=["w_1"])
        storage.save_pack(good)
        storage.pack_path("pack_20261012_002").write_text("坏文件", encoding="utf-8")
        packs = storage.list_packs()
        self.assertEqual([p.id for p in packs], ["pack_20261012_001"])

    def test_new_pack_id_increments_within_a_day(self):
        day = date(2026, 10, 12)
        first = storage.new_pack_id("study", day)
        self.assertEqual(first, "pack_20261012_001")
        storage.save_pack(WordPack(id=first, pack_type=PACK_TYPE_STUDY, title="t",
                                   created_at="2026-10-12", word_ids=["w_1"]))
        self.assertEqual(storage.new_pack_id("study", day), "pack_20261012_002")

    def test_list_packs_newest_first(self):
        for index, day in enumerate(["2026-10-10", "2026-10-12", "2026-10-11"], start=1):
            storage.save_pack(WordPack(id="pack_2026101%d_001" % index,
                                       pack_type=PACK_TYPE_STUDY, title="t",
                                       created_at=day, word_ids=["w_1"]))
        dates = [p.created_at for p in storage.list_packs()]
        self.assertEqual(dates, ["2026-10-12", "2026-10-11", "2026-10-10"])

    def test_vocab_pack_round_trips_and_lists(self):
        """用户导入/制作的词表包往返不丢字段,且和 study 包一样能被 list_packs 捞回来。"""
        pack = make_vocab_pack("pack_20261012_001", "我的六级词", ["w_1", "w_2"],
                               "2026-10-12")
        storage.save_pack(pack)
        loaded = storage.load_pack("pack_20261012_001")
        self.assertEqual(loaded.pack_type, PACK_TYPE_VOCAB)
        self.assertEqual(loaded.title, "我的六级词")
        self.assertEqual(loaded.word_ids, ["w_1", "w_2"])
        self.assertIsNone(loaded.exam)
        self.assertIn(pack, storage.list_packs())

    def test_delete_pack_removes_it_from_disk(self):
        """删词包必须真的删文件:只从内存列表摘掉的话,下次读盘它又回来了。"""
        storage.save_pack(make_vocab_pack("pack_20261012_001", "待删", ["w_1"],
                                          "2026-10-12"))
        storage.delete_pack("pack_20261012_001")
        self.assertEqual(storage.list_packs(), [])
        self.assertIsNone(storage.load_pack("pack_20261012_001"))

    def test_delete_pack_is_idempotent(self):
        """重复删除不该抛异常(和 new_pack_id、bootstrap 一样的幂等口味)。"""
        storage.delete_pack("pack_不存在_001")   # 不该崩

    def test_ai_cache_round_trip(self):
        storage.save_ai_cache({"w_1|大气": {"grade": "correct", "score": 1.0}})
        self.assertEqual(storage.load_ai_cache()["w_1|大气"]["grade"], "correct")

    def test_log_error_appends(self):
        storage.log_error("第一行")
        storage.log_error("第二行")
        content = (storage.logs_dir() / "errors.log").read_text(encoding="utf-8")
        self.assertIn("第一行", content)
        self.assertIn("第二行", content)


class TestCharacters(unittest.TestCase, RoundTripMixin):
    def test_character_round_trip(self):
        character = characters.AiCharacter(id="c1", name="小老师", directory="c1")
        self.assert_round_trip(character)

    def test_persona_round_trip(self):
        self.assert_round_trip(characters.Persona(id="p1", name="严格", prompt="你是严师"))

    def test_image_path_is_relative(self):
        """图片路径必须存相对路径,否则存档换台电脑就全失效。"""
        character = characters.AiCharacter(id="c1", name="n", directory="c1")
        path = character.image_path("happy")
        self.assertEqual(path, "ai/c1/happy.png")
        self.assertNotIn(":", path)          # 不含盘符

    def test_folder_defaults_to_id(self):
        character = characters.AiCharacter(id="c1", name="n")
        self.assertEqual(character.folder, "c1")

    def test_ensure_defaults_fills_empty_library(self):
        library = characters.CharacterLibrary()
        library.ensure_defaults()
        self.assertEqual(len(library.characters), 1)
        self.assertEqual(len(library.personas), 1)
        self.assertEqual(library.current_character().id, "default")

    def test_ensure_defaults_repairs_dangling_selection(self):
        """选中的形象被删掉后,不该让界面拿到 None。"""
        library = characters.CharacterLibrary()
        library.ensure_defaults()
        library.selected_character = "已删除的形象"
        self.assertEqual(library.current_character().id, "default")

    def test_library_round_trip(self):
        self.assert_round_trip(characters.CharacterLibrary())


if __name__ == "__main__":
    unittest.main(verbosity=2)
