# -*- coding: utf-8 -*-
"""L1 台词层测试:情绪规则、不重复取词、提问识别。

这三件事合起来决定了一件事:**绝大多数对话不花钱**。
情绪由本地规则定(不调模型),台词从本地库里取(不调模型),
只有用户明确提问才进入自由对话 —— 所以提问识别的判据必须保守,
宁可漏判也不能把普通答案误判成提问。
"""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.interfaces import (                              # noqa: E402
    EMOTION_CONFUSED,
    EMOTION_HAPPY,
    EMOTION_NORMAL,
    EMOTION_SAD,
    EMOTION_SURPRISED,
    EMOTION_THINKING,
)
from core.lines import (                                   # noqa: E402
    TOPIC_EMPTY,
    TOPIC_GREETING,
    TOPIC_SESSION_END,
    LineSelector,
    default_linepack,
    emotion_for,
    is_question,
)
from core.interfaces import JudgeResult                                # noqa: E402
from core.models import Grade, Mastery, Word, WordState                # noqa: E402


def make_word(mastery=Mastery.FUZZY):
    return Word(id="w_1", spelling_key="bank", word="bank", translation="银行",
                state=WordState(mastery=mastery))


def make_result(grade, score=1.0):
    return JudgeResult(grade=grade, score=score, feedback="")


class TestEmotionRules(unittest.TestCase):

    def test_correct_makes_her_happy(self):
        self.assertEqual(
            emotion_for(make_result(Grade.CORRECT), make_word(), "银行"), EMOTION_HAPPY)

    def test_fuzzy_makes_her_think(self):
        self.assertEqual(
            emotion_for(make_result(Grade.FUZZY), make_word(), "河"), EMOTION_THINKING)

    def test_wrong_makes_her_sad(self):
        self.assertEqual(
            emotion_for(make_result(Grade.WRONG), make_word(), "完全无关"), EMOTION_SAD)

    def test_empty_answer_is_confusion_not_sadness(self):
        """什么都没输入不是"答错",不该给一张难过的脸。"""
        emotion = emotion_for(make_result(Grade.WRONG, 0.0), make_word(), "   ")
        self.assertEqual(emotion, EMOTION_CONFUSED)

    def test_forgetting_a_mastered_word_gets_surprise(self):
        """这个词以前会背的,现在忘了 —— 值得表现出惊讶。

        对应的时序是:判分之后 state 已经推进过,原本 KNOWN 的词答错后
        会变成 RELEARN。所以这里读的是**新**状态。
        """
        word = make_word(mastery=Mastery.RELEARN)
        emotion = emotion_for(make_result(Grade.WRONG), word, "错的")
        self.assertEqual(emotion, EMOTION_SURPRISED)

    def test_wrong_word_without_a_word_object_still_works(self):
        self.assertEqual(
            emotion_for(make_result(Grade.WRONG), None, "错的"), EMOTION_SAD)


class TestLineSelector(unittest.TestCase):

    def setUp(self):
        # 固定种子,测试才能稳定复现
        self.selector = LineSelector(default_linepack("zh-CN"), random.Random(7))

    def test_never_repeats_until_the_group_is_exhausted(self):
        """连着抽 200 次,不该出现任何一次"上一句和这一句一模一样"。

        这是"排队抽"相对 random.choice 的全部意义 ——
        一组台词只有四五条,纯随机的话复读感会非常明显。
        """
        previous = None
        for _ in range(200):
            line = self.selector.line(Grade.CORRECT.value, EMOTION_HAPPY)
            self.assertTrue(line)
            self.assertNotEqual(line, previous, "台词连续重复了")
            previous = line

    def test_uses_every_variant_before_repeating(self):
        group = default_linepack("zh-CN").lines["correct:happy"]
        seen = {self.selector.line(Grade.CORRECT.value, EMOTION_HAPPY)
                for _ in range(len(group))}
        self.assertEqual(len(seen), len(group), "一轮之内应该把每条都用过")

    def test_falls_back_to_a_generic_line(self):
        """只有 wrong:sad、没有 wrong:confused 时,应该退到 wrong:normal 或 *:normal。"""
        line = self.selector.line(Grade.WRONG.value, EMOTION_CONFUSED)
        self.assertTrue(line)

    def test_unknown_topic_falls_back_to_the_catch_all(self):
        self.assertEqual(self.selector.line("完全不存在的话题", EMOTION_NORMAL),
                         "嗯,我在这儿。")

    def test_react_uses_the_empty_topic_for_a_blank_answer(self):
        """空输入不该骂用户答错,该催他输入。"""
        emotion, line = self.selector.react(make_word(), make_result(Grade.WRONG, 0.0), "")
        self.assertEqual(emotion, EMOTION_CONFUSED)
        self.assertTrue(line)

    def test_react_returns_both_the_face_and_the_words(self):
        emotion, line = self.selector.react(make_word(), make_result(Grade.CORRECT), "银行")
        self.assertEqual(emotion, EMOTION_HAPPY)
        self.assertTrue(line)

    def test_farewell_tone_follows_the_score(self):
        good = LineSelector(default_linepack("zh-CN"), random.Random(1)).farewell(9, 10)
        bad = LineSelector(default_linepack("zh-CN"), random.Random(1)).farewell(1, 10)
        self.assertEqual(good[0], EMOTION_HAPPY)
        self.assertEqual(bad[0], EMOTION_SAD)

    def test_farewell_with_an_empty_session_does_not_crash(self):
        emotion, line = self.selector.farewell(0, 0)
        self.assertEqual(emotion, EMOTION_NORMAL)
        self.assertTrue(line)

    def test_greeting_returns_an_emotion_and_a_line(self):
        emotion, line = self.selector.greet()
        self.assertTrue(emotion)
        self.assertTrue(line)


class TestLinePackContents(unittest.TestCase):

    def test_chinese_pack_has_a_catch_all(self):
        """没有兜底台词的话,任何没预料到的情况都会让老师一言不发。"""
        self.assertTrue(default_linepack("zh-CN").lines.get("*:normal"))

    def test_english_pack_exists_so_the_language_switch_is_not_a_lie(self):
        pack = default_linepack("en")
        self.assertEqual(pack.language, "en")
        self.assertTrue(pack.lookup(Grade.CORRECT.value, EMOTION_HAPPY))

    def test_unknown_language_falls_back_to_chinese(self):
        """宁可给中文,也不要给一份空台词导致老师完全不说话。"""
        self.assertEqual(default_linepack("fr").language, "zh-CN")

    def test_topics_have_lines(self):
        pack = default_linepack("zh-CN")
        for topic, emotion in ((TOPIC_GREETING, EMOTION_NORMAL),
                               (TOPIC_SESSION_END, EMOTION_NORMAL),
                               (TOPIC_EMPTY, EMOTION_CONFUSED)):
            self.assertTrue(pack.lookup(topic, emotion), "缺少 %s 的台词" % topic)


class TestQuestionDetection(unittest.TestCase):
    """判据必须保守:**默认打字是答题**。

    误判的代价是不对称的 —— 漏判只是让用户把问题换个说法再打一遍
    (考试页已经**没有**「问老师」按钮了,提问入口就是输入框本身),
    误判则会让答题框变成烧钱的聊天窗口。
    """

    def test_question_mark_marks_a_question(self):
        self.assertTrue(is_question("这个词怎么用?"))
        self.assertTrue(is_question("这个词怎么用？"))

    def test_question_words_at_the_start(self):
        self.assertTrue(is_question("请问这两个词有什么区别"))
        self.assertTrue(is_question("为什么这里用过去式"))
        self.assertTrue(is_question("什么是虚拟语气"))

    def test_plain_answers_are_not_questions(self):
        for answer in ("银行", "n. 银行", "河岸; 银行", "大气层, 大气圈"):
            self.assertFalse(is_question(answer), "不该把 %r 当成提问" % answer)

    def test_empty_text_is_not_a_question(self):
        self.assertFalse(is_question(""))
        self.assertFalse(is_question("   "))
        self.assertFalse(is_question(None))

    def test_a_question_word_in_the_middle_is_still_an_answer(self):
        """只有出现在开头才算 —— "怎么"出现在释义中间是巧合,不是提问。"""
        self.assertFalse(is_question("银行,银行的英文怎么拼我记得是 bank"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
