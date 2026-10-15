# -*- coding: utf-8 -*-
"""判分测试。

分两块:
  1. L0 离线判分的准确性(含两个真实踩过的坑,后面有专门用例钉住)
  2. 省 Token 的闸门行为 —— 跑完整场考试必须一次 API 都不调
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import Settings                              # noqa: E402
from core.interfaces import AIProvider                        # noqa: E402
from core.judge import (                                      # noqa: E402
    OfflineJudge,
    JudgeService,
    best_score,
    normalize_answer,
    split_senses,
)
from core.interfaces import JudgeResult                       # noqa: E402
from core.models import (                                     # noqa: E402
    SOURCE_AI,
    SOURCE_CACHE,
    SOURCE_OFFLINE,
    Grade,
    Word,
)

TRANSLATION = "n. 大气层,大气圈; 气氛"


def make_word(word="atmosphere", translation=TRANSLATION, word_id="w_1"):
    return Word(id=word_id, spelling_key=word, word=word, translation=translation)


class FakeAIProvider(AIProvider):
    """假的大模型后端。记录调用次数,好断言"到底花没花钱"。"""

    def __init__(self, verdict=Grade.CORRECT):
        self.verdict = verdict
        self.batch_calls = 0
        self.items_seen = 0

    def judge_batch(self, items, persona="", history=None):
        # 判分现在也带人设和历史(v1.18:三个任务共用一个角色和一段记忆),
        # 所以替身**必须收下这两个参数** —— 否则 TypeError 会被 judge.py 里
        # 那个"兜住一切"的 except 吞掉,表现成"调用次数是 0",
        # 而真正的错因(签名对不上)完全不显示。
        self.batch_calls += 1
        self.items_seen += len(items)
        self.persona_seen = persona
        self.history_seen = list(history or [])
        return [JudgeResult(self.verdict, 1.0, SOURCE_AI, "AI 判的") for _ in items]

    def chat(self, persona, history, user_message):
        return ""

    def diagnose(self, summary, persona="", history=None):
        return ""


class BrokenAIProvider(AIProvider):
    """每次调用都炸的后端,用来验证"断网也能用"。"""

    def judge_batch(self, items, persona="", history=None):
        raise ConnectionError("模拟网络不通")

    def chat(self, persona, history, user_message):
        raise ConnectionError("模拟网络不通")

    def diagnose(self, summary, persona="", history=None):
        raise ConnectionError("模拟网络不通")


class TestSensesNormalisation(unittest.TestCase):
    def test_senses_are_split_and_pos_stripped(self):
        self.assertEqual(split_senses(TRANSLATION), ["大气层", "大气圈", "气氛"])

    def test_pos_prefix_is_stripped_before_punctuation(self):
        """钉住那个真实的坑。

        最初的写法是"先去标点、再剥词性",结果词性后面那个点号先被清掉了,
        正则 `^(n|v|...)\\.` 永远匹配不上,义项里残留一个孤零零的 "n",
        导致"大气层"只能靠包含匹配拿到 0.88,精确匹配形同虚设。
        这里要求它拿满 1.0。
        """
        self.assertEqual(split_senses("n. 大气层"), ["大气层"])
        self.assertEqual(best_score("大气层", split_senses("n. 大气层")), 1.0)

    def test_various_pos_tags(self):
        for tag in ("n.", "v.", "vt.", "adj.", "adv.", "prep.", "N."):
            self.assertEqual(split_senses("%s 测试" % tag), ["测试"], tag)

    def test_full_width_punctuation_is_normalised(self):
        """中文输入法下的全角标点必须和半角一视同仁。"""
        self.assertEqual(split_senses("大气层，大气圈；气氛"), ["大气层", "大气圈", "气氛"])

    def test_empty_and_blank_translation(self):
        self.assertEqual(split_senses(""), [])
        self.assertEqual(split_senses("   "), [])
        self.assertEqual(best_score("x", []), 0.0)

    def test_normalize_answer(self):
        self.assertEqual(normalize_answer("  大气层! "), "大气层")
        self.assertEqual(normalize_answer("ＡＴＭＯＳＰＨＥＲＥ"), "atmosphere")


class TestOfflineJudge(unittest.TestCase):
    """规格里那张判定表,逐条钉住。"""

    def setUp(self):
        self.judge = OfflineJudge()
        self.word = make_word()

    def check(self, answer, expected_grade):
        result = self.judge.judge(self.word, answer)
        self.assertEqual(result.grade, expected_grade,
                         "%r 应为 %s,实得 %s(得分 %.2f)"
                         % (answer, expected_grade.value, result.grade.value, result.score))
        self.assertEqual(result.source, SOURCE_OFFLINE)
        return result

    def test_exact_sense_matches(self):
        for answer in ("大气层", "大气圈", "气氛"):
            self.assertEqual(self.check(answer, Grade.CORRECT).score, 1.0)

    def test_partial_answer_is_correct(self):
        """答出半个义项("大气"之于"大气层")算对。"""
        self.check("大气", Grade.CORRECT)

    def test_unrelated_words_are_wrong(self):
        for answer in ("空气", "环境", "xyz", "完全不相干"):
            self.check(answer, Grade.WRONG)

    def test_transposed_characters_are_fuzzy_not_wrong(self):
        """这是第二个真实踩过的坑。

        "氛气"是"气氛"的手滑,原来的实现判成 wrong(0.50)。
        加同字异序识别后应落在模糊带 —— 用户明显是知道答案的,只是打反了。
        """
        self.check("氛气", Grade.FUZZY)

    def test_answering_with_the_word_itself_gets_a_hint(self):
        result = self.check("atmosphere", Grade.WRONG)
        self.assertIn("中文", result.feedback)

    def test_empty_answer_gets_a_hint(self):
        result = self.check("", Grade.WRONG)
        self.assertTrue(result.feedback)

    def test_wrong_answer_shows_the_correct_translation(self):
        self.assertIn("大气层", self.check("空气", Grade.WRONG).feedback)

    def test_single_character_does_not_pass_by_containment(self):
        """一个"气"字不该靠"包含于气氛"蒙混过关。"""
        self.assertNotEqual(self.judge.judge(self.word, "气").grade, Grade.CORRECT)

    def test_whitespace_and_punctuation_are_ignored(self):
        self.check(" 大气层 ", Grade.CORRECT)
        self.check("大气层!", Grade.CORRECT)

    def test_word_without_translation(self):
        """翻译是必填,但存档被手工改坏时也不能崩。"""
        self.assertEqual(self.judge.judge(make_word(translation=""), "x").grade, Grade.WRONG)


class TestTokenSavingGate(unittest.TestCase):
    """省 Token 的闸门:明确对/明确错都不该触发 API。"""

    def setUp(self):
        # 断网降级那条用例会让判分器往 logs/ 里写一行(这正是它该做的事)。
        # 但那一行不该落进开发者**真正的** save/ 目录 —— 跑一次测试就在别人的
        # 学习记录目录里留一行"模拟网络不通",下次用户看到会以为程序坏了。
        self.temp_dir = Path(tempfile.mkdtemp(prefix="remember_judge_"))
        self._previous = os.environ.get("REMEMBER_DATA_DIR")
        os.environ["REMEMBER_DATA_DIR"] = str(self.temp_dir)

        self.settings = Settings()
        # 关掉"强制语义匹配"才允许走 API
        self.settings.study.force_semantic_match = False
        self.settings.ai.enabled = True
        self.settings.ai.base_url = "https://api.example.com/v1"
        self.settings.ai.model = "test-model"
        self.settings.ai.api_key = "sk-test"
        self.word = make_word()

    def tearDown(self):
        if self._previous is None:
            os.environ.pop("REMEMBER_DATA_DIR", None)
        else:
            os.environ["REMEMBER_DATA_DIR"] = self._previous
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_full_exam_makes_zero_api_calls(self):
        """核心保证:一场全是明确对错的考试,一次 API 都不该调。"""
        provider = FakeAIProvider()
        service = JudgeService(self.settings, ai_provider=provider)

        answers = ["大气层", "大气圈", "气氛",      # 明确对
                   "空气", "环境", "xyz", "完全不相干"]  # 明确错
        for answer in answers:
            result = service.judge(self.word, answer)
            self.assertEqual(result.source, SOURCE_OFFLINE)

        self.assertEqual(provider.batch_calls, 0, "明确对错不该调用 API")
        self.assertEqual(service.api_calls_made, 0)

    def test_ambiguous_answer_escalates_exactly_once(self):
        """只有歧义带才升级,而且一次请求只发一项。"""
        provider = FakeAIProvider()
        service = JudgeService(self.settings, ai_provider=provider)

        result = service.judge(self.word, "氛气")   # 同字异序 → 模糊带

        self.assertEqual(provider.batch_calls, 1)
        self.assertEqual(provider.items_seen, 1)
        self.assertEqual(result.source, SOURCE_AI)
        self.assertEqual(service.api_calls_made, 1)

    def test_repeated_ambiguous_answer_hits_the_cache(self):
        """同一个错误答案答两次,只花一次钱。"""
        provider = FakeAIProvider()
        service = JudgeService(self.settings, ai_provider=provider)

        service.judge(self.word, "氛气")
        second = service.judge(self.word, "氛气")

        self.assertEqual(provider.batch_calls, 1, "第二次应命中缓存")
        self.assertEqual(second.source, SOURCE_CACHE)
        self.assertEqual(service.api_calls_saved_by_cache, 1)

    def test_cache_key_ignores_punctuation_differences(self):
        provider = FakeAIProvider()
        service = JudgeService(self.settings, ai_provider=provider)
        service.judge(self.word, "氛气")
        service.judge(self.word, "氛气!")     # 归一化后是同一个键
        self.assertEqual(provider.batch_calls, 1)

    def test_force_semantic_match_blocks_the_api_entirely(self):
        """"强制语义匹配"开着 = 只用本地词表,一次都不联网。"""
        self.settings.study.force_semantic_match = True
        provider = FakeAIProvider()
        service = JudgeService(self.settings, ai_provider=provider)

        result = service.judge(self.word, "氛气")

        self.assertEqual(provider.batch_calls, 0)
        self.assertEqual(result.source, SOURCE_OFFLINE)

    def test_unconfigured_ai_never_calls_out(self):
        """没配 Key 就不该尝试联网 —— 走到网上再失败是浪费用户时间。"""
        self.settings.ai.api_key = ""
        provider = FakeAIProvider()
        service = JudgeService(self.settings, ai_provider=provider)
        self.assertEqual(service.judge(self.word, "氛气").source, SOURCE_OFFLINE)
        self.assertEqual(provider.batch_calls, 0)

    def test_budget_cap_stops_further_calls(self):
        """预算护栏:超出上限后自动降级为纯离线。"""
        self.settings.study.max_api_calls_per_session = 2
        provider = FakeAIProvider()
        service = JudgeService(self.settings, ai_provider=provider)

        for index in range(5):
            service.judge(make_word(word_id="w_%d" % index), "氛气")

        self.assertEqual(provider.batch_calls, 2, "不该超过预算上限")
        self.assertEqual(service.api_calls_made, 2)

    def test_budget_zero_means_unlimited(self):
        self.settings.study.max_api_calls_per_session = 0
        provider = FakeAIProvider()
        service = JudgeService(self.settings, ai_provider=provider)
        for index in range(3):
            service.judge(make_word(word_id="w_%d" % index), "氛气")
        self.assertEqual(provider.batch_calls, 3)

    def test_network_failure_falls_back_to_offline(self):
        """断网时必须静默降级,而且结果仍要可用。"""
        service = JudgeService(self.settings, ai_provider=BrokenAIProvider())
        result = service.judge(self.word, "氛气")
        self.assertEqual(result.source, SOURCE_OFFLINE)
        self.assertEqual(result.grade, Grade.FUZZY, "应回退到本地判定")

    def test_no_provider_at_all_is_fine(self):
        """纯离线运行(从没配过 AI)是默认状态,必须完全可用。"""
        service = JudgeService(self.settings, ai_provider=None)
        self.assertEqual(service.judge(self.word, "大气层").grade, Grade.CORRECT)
        self.assertEqual(service.stats()["api_calls"], 0)

    def test_stats_reports_savings(self):
        provider = FakeAIProvider()
        service = JudgeService(self.settings, ai_provider=provider)
        service.judge(self.word, "大气层")
        service.judge(self.word, "氛气")
        service.judge(self.word, "氛气")
        stats = service.stats()
        self.assertEqual(stats["api_calls"], 1)
        self.assertEqual(stats["cache_hits"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
