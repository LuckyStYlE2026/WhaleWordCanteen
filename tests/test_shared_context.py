# -*- coding: utf-8 -*-
"""三个 AI 任务共用一个角色和一段记忆(用户 2026-10-17 的要求)。

用户的原话是"这样前面所有的对话都会一样,全部缓存命中"。所以要守的其实是
两件事:

1. **同一个角色**:判分不再挂着写死的"你是单词判分助手",诊断不再挂着
   "你是一位语言学习教练" —— 那会让用户在和一个角色说话时突然被另一个人
   判分/点评("对话非常割裂")。
2. **同一段前缀**:三个任务发出去的 messages 里,system 和历史的字节完全
   一致,只有最后那一条不同。前缀缓存才有意义。

顺带守住两件容易悄悄坏掉的事:人设要**现读**(切了立刻生效),
历史只留**人话**(不塞 JSON)。
"""

import json
import unittest
from datetime import datetime

from core import ai_client
from core.ai_client import _build_messages, diagnose_task_message
from core.ai_client import judge_task_message
from core.ai_context import KEEP_AFTER_TRIM, Conversation
from core.interfaces import AIProvider, JudgeItem, JudgeResult, Turn
from core.models import Grade, SOURCE_AI
from core.reply_format import strip_tag
from core.transcript import to_markdown, to_payload


class SharedPrefixTest(unittest.TestCase):
    """三个任务的 messages 前缀必须逐字节一致。"""

    PERSONA = "你是 DeepSeek 鲸鱼娘,背单词游戏里的语言教师。"
    HISTORY = [Turn("user", "spect 是什么意思?"),
               Turn("assistant", "[happy] 看的意思。")]

    def _prefix(self, task_message: str):
        """取"除最后一条之外"的全部内容 —— 那就是缓存前缀。"""
        messages = _build_messages(self.PERSONA, self.HISTORY, task_message)
        return json.dumps(messages[:-1], ensure_ascii=False)

    def test_all_three_tasks_share_the_same_prefix(self):
        judge = self._prefix(judge_task_message(
            [JudgeItem("w1", "bank", "银行", "银行")]))
        chat = self._prefix("retrospect 怎么用?")
        diagnose = self._prefix(diagnose_task_message({"total": 5}))
        self.assertEqual(judge, chat, "判分和对话的前缀不一致,缓存白搭")
        self.assertEqual(chat, diagnose, "诊断和对话的前缀不一致,缓存白搭")

    def test_the_persona_is_the_only_system_message(self):
        """system 里**只有人设** —— 不能再出现第二个身份。"""
        messages = _build_messages(self.PERSONA, self.HISTORY, "任务")
        self.assertEqual(messages[0], {"role": "system", "content": self.PERSONA})

    def test_the_task_instruction_never_reaches_the_system_prompt(self):
        """任务约定放最后一条,不放 system。

        放 system 就等于每个任务一个前缀,缓存全废;而且用户翻记录时
        会看到一串内部指令。
        """
        messages = _build_messages(self.PERSONA, self.HISTORY,
                                   judge_task_message(
                                       [JudgeItem("w1", "bank", "银行", "银行")]))
        self.assertEqual(len(messages), 1 + len(self.HISTORY) + 1)
        self.assertIn("JSON", messages[-1]["content"])
        self.assertNotIn("JSON", messages[0]["content"])

    def test_an_empty_persona_still_gets_a_neutral_system(self):
        """人设为空时给中性兜底,而不是留空 ——

        空 system 会让模型自己挑一个身份,那正是要避免的割裂。
        """
        messages = _build_messages("", [], "任务")
        self.assertEqual(messages[0]["role"], "system")
        self.assertTrue(messages[0]["content"])


class JudgeTaskMessageTest(unittest.TestCase):
    """判分那一条消息:先人话,再 JSON,最后输出约定。"""

    ITEM = JudgeItem(word_id="w1", word="atmosphere",
                     translation="n. 大气层", answer="大气层")

    def test_it_leads_with_plain_language(self):
        """先人话再 JSON —— 历史里全是对话,突然丢一坨 JSON 会让模型

        在"聊天"和"做题"之间反复切换语气。
        """
        body = judge_task_message([self.ITEM])
        self.assertTrue(body.startswith("atmosphere的意思是?鱼片答:大气层"))

    def test_the_json_part_carries_the_id_so_verdicts_stay_parseable(self):
        body = judge_task_message([self.ITEM])
        payload = [line for line in body.splitlines() if line.startswith("[")]
        self.assertTrue(payload, "没有机器可读的那一段,回值就对不上 id 了")
        parsed = json.loads(payload[0])
        self.assertEqual(parsed[0]["id"], "w1")

    def test_the_output_contract_says_json_only(self):
        body = judge_task_message([self.ITEM])
        self.assertIn("只输出一个 JSON 数组", body)


class DiagnoseTaskMessageTest(unittest.TestCase):
    """诊断那一条消息:数字说成人话。"""

    def test_counts_become_a_sentence(self):
        body = diagnose_task_message({"pack": "10-17 学习词包", "total": 20,
                                      "known": 12, "fuzzy": 5, "new": 3,
                                      "due_today": 4})
        self.assertIn("10-17 学习词包", body)
        self.assertIn("20 个词", body)
        self.assertIn("记住 12", body)
        self.assertIn("有点模糊 5", body)
        self.assertIn("今天另有 4 个词到期该复习", body)

    def test_it_does_not_dump_raw_json(self):
        """不直接丢 JSON —— 那样评语会变回分析报告的口气,人设就断了。"""
        body = diagnose_task_message({"total": 20, "known": 12})
        self.assertNotIn("{", body)
        self.assertNotIn('"total"', body)

    def test_a_bare_summary_does_not_crash(self):
        body = diagnose_task_message({})
        self.assertIn("共碰了 0 个词".replace("共碰了", "一共碰了"), body)


class ConversationTest(unittest.TestCase):
    """共用上下文:人设现读、历史只留人话、裁剪不滑窗。"""

    def test_the_persona_is_read_every_time(self):
        """**这是"切了人设立刻生效"的关键。**

        早先 ChatService 在启动时把人设拷一份,于是切人设要重启才生效。
        """
        who = {"name": "鲸鱼娘"}
        conversation = Conversation(persona_provider=lambda: "你是%s。" % who["name"])
        self.assertIn("鲸鱼娘", conversation.persona())
        who["name"] = "猫娘"
        self.assertIn("猫娘", conversation.persona())

    def test_a_broken_persona_provider_does_not_crash_the_chat(self):
        def explode():
            raise RuntimeError("人设读不出来")
        self.assertEqual(Conversation(persona_provider=explode).persona(), "")

    def test_remember_skips_empty_halves(self):
        """空的半句不该进历史 —— 有些接口见到空消息会直接报错。"""
        conversation = Conversation()
        conversation.remember("你好", "")
        self.assertEqual(len(conversation), 1)
        conversation.remember("", "在")
        self.assertEqual(len(conversation), 2)

    def test_trimming_is_sticky_not_sliding(self):
        """裁剪要"裁一次撑很多轮",不能每轮滑一格。

        滑动窗口会让前缀每轮都变 —— 前缀缓存要求前面那段逐字节相同,
        每轮都滑等于每轮都全部重算,比留长一点贵得多。
        """
        conversation = Conversation()
        limit = ai_client.MAX_HISTORY_MESSAGES
        for i in range(limit + 5):
            conversation.remember("问题%d" % i, "回答%d" % i)
        trimmed = len(conversation)
        self.assertLessEqual(trimmed, limit)
        # 再记几轮:不应该每记一轮就掉一轮(那是滑动)
        conversation.remember("再来一个", "好")
        self.assertGreater(len(conversation), trimmed,
                           "每轮都在滑窗 —— 前缀会一直变,缓存命中不了")

    def test_clear_empties_everything(self):
        conversation = Conversation()
        conversation.remember("a", "b")
        conversation.clear()
        self.assertEqual(len(conversation), 0)


class JudgeRemembersTest(unittest.TestCase):
    """判分也要把自己那一轮记进共用历史。"""

    class Recorder(AIProvider):
        name = "recorder"

        def __init__(self):
            self.persona = None
            self.history = None

        def judge_batch(self, items, persona="", history=None):
            self.persona = persona
            self.history = list(history or [])
            return [JudgeResult(Grade.CORRECT, 1.0, SOURCE_AI, "") for _ in items]

        def chat(self, persona, history, user_message):
            return ""

        def diagnose(self, summary, persona="", history=None):
            return ""

    def _service(self, conversation):
        from core.config import Settings
        from core.judge import JudgeService
        provider = self.Recorder()
        settings = Settings()
        # 关掉"强制语义匹配"并放开预算,好让升级那一步真的发生
        settings.study.force_semantic_match = False
        settings.study.max_api_calls_per_session = 0
        settings.ai.enabled = True          # is_configured 要件之一,少它就不升级
        settings.ai.api_key = "k"
        settings.ai.base_url = "http://x"
        settings.ai.model = "m"
        service = JudgeService(settings, provider, {}, conversation)
        return service, provider

    def test_it_sends_the_persona_and_the_shared_history(self):
        conversation = Conversation(persona_provider=lambda: "你是鲸鱼娘。")
        conversation.remember("spect 是什么意思?", "看的意思。")
        from core.models import Word
        service, provider = self._service(conversation)
        word = Word(id="w1", spelling_key="bank", word="bank", translation="银行")
        service.judge(word, "银")             # 实测 0.67,正好落在歧义带
        self.assertEqual(provider.persona, "你是鲸鱼娘。")
        self.assertTrue(any("spect" in turn.content for turn in provider.history),
                        "判分没拿到共用历史")

    def test_the_human_turn_is_recorded_but_not_the_json(self):
        """历史里**只留人话** —— 那坨 JSON 不该出现在对话记录里。"""
        conversation = Conversation()
        from core.models import Word
        service, _provider = self._service(conversation)
        word = Word(id="w1", spelling_key="bank", word="bank", translation="银行")
        service.judge(word, "银")            # 歧义带 -> 会升级到 AI
        blob = json.dumps([{"r": t.role, "c": t.content}
                           for t in conversation.turns], ensure_ascii=False)
        self.assertIn("bank", blob, "这一题没被记进历史")
        self.assertNotIn('"v"', blob, "机器数据的 JSON 混进历史了")
        self.assertNotIn("word_id", blob)


class TranscriptTest(unittest.TestCase):
    """存下来的对话记录。"""

    TURNS = [Turn("user", "spect 是什么意思?"),
             Turn("assistant", "[happy] 看的意思。"),
             Turn("user", "哦哦")]

    def test_the_readable_copy_drops_emotion_tags(self):
        """`[happy]` 是给机器看的指令,用户读记录时看到只会莫名其妙。

        原始文本(带标记)在 .json 里完整保留。
        """
        markdown = to_markdown(self.TURNS, "deepseek", "语言教师·deepseek")
        self.assertNotIn("[happy]", markdown)
        self.assertIn("看的意思。", markdown)

    def test_the_backup_keeps_the_raw_text(self):
        payload = to_payload(self.TURNS, "deepseek", "语言教师·deepseek")
        self.assertEqual(payload["turns"][1]["content"], "[happy] 看的意思。")
        self.assertEqual(payload["character"], "deepseek")
        self.assertEqual(payload["persona"], "语言教师·deepseek")

    def test_the_header_records_which_persona_was_used(self):
        """同一段对话在不同人设下读起来是两回事 ——

        用户过几个月回来翻,唯一能告诉他"当时那个傲娇老师是哪个设定"
        的就是这几行。
        """
        markdown = to_markdown(self.TURNS, "deepseek", "语言教师·deepseek",
                               datetime(2026, 10, 17, 21, 30))
        self.assertIn("语言教师·deepseek", markdown)
        self.assertIn("2026-10-17 21:30", markdown)

    def test_the_speaker_name_is_not_repeated_for_consecutive_lines(self):
        markdown = to_markdown([Turn("assistant", "一。"),
                                Turn("assistant", "二。")], "deepseek")
        self.assertEqual(markdown.count("**deepseek:**"), 1)

    def test_a_tag_only_reply_does_not_leave_a_blank_line(self):
        """模型偶尔只回一个 `[happy]` —— 记录里不该留一条空的。"""
        markdown = to_markdown([Turn("assistant", "[happy]"), Turn("user", "哦")],
                               "deepseek")
        self.assertNotIn("**deepseek:**", markdown)
        self.assertIn("哦", markdown)


if __name__ == "__main__":
    unittest.main()
