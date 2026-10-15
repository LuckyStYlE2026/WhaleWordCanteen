# -*- coding: utf-8 -*-
"""大模型接入层测试。**全程不联网** —— 用一个假的 requests 顶替掉。

要守住的三条约定(见 ai_client.py 开头):
  · 输出长度按用途分级,输出 token 才是账单的大头
  · 静态提示词排在最前,变量排在最后(命中前缀缓存的前提)
  · 失败绝不抛到界面上,而是回退到本地台词
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ai_client, storage                          # noqa: E402
from core.ai_client import AIError, ApiProvider, NullAIProvider   # noqa: E402
from core.chat import ChatService                            # noqa: E402
from core.config import AiSettings                           # noqa: E402
from core.interfaces import AIProvider as Provider           # noqa: E402
from core.interfaces import JudgeItem, Turn                  # noqa: E402
from core.models import Grade                                # noqa: E402


def settings(**overrides):
    values = dict(enabled=True, base_url="https://example.test/v1",
                  model="some-model", api_key="sk-test", timeout_seconds=5)
    values.update(overrides)
    return AiSettings(**values)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("没有 JSON")
        return self._payload


class FakeRequests:
    """顶替 requests 模块。记录每一次请求,方便断言发出去的到底是什么。"""

    def __init__(self, content="", status_code=200, raises=None):
        self.status_code = status_code
        self.raises = raises
        self.text = content
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json,
                           "headers": headers, "timeout": timeout})
        if self.raises is not None:
            raise self.raises
        payload = {"choices": [{"message": {"content": self.text}}]}
        return FakeResponse(self.status_code, payload, self.text)

    @property
    def last_payload(self):
        return self.calls[-1]["json"]

    @property
    def last_messages(self):
        return self.last_payload["messages"]


class TempDataDirTestCase(unittest.TestCase):
    """把存档目录指到临时目录,免得测试污染真实存档。"""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="remember_ai_"))
        self._previous = os.environ.get("REMEMBER_DATA_DIR")
        os.environ["REMEMBER_DATA_DIR"] = str(self.temp_dir)
        self._real_requests = ai_client.requests

    def tearDown(self):
        ai_client.requests = self._real_requests
        if self._previous is None:
            os.environ.pop("REMEMBER_DATA_DIR", None)
        else:
            os.environ["REMEMBER_DATA_DIR"] = self._previous
        shutil.rmtree(self.temp_dir, ignore_errors=True)


# --------------------------------------------------------------------------
# 空后端
# --------------------------------------------------------------------------

class TestNullProvider(unittest.TestCase):

    def test_returns_empty_everything(self):
        """它存在的意义是让内核永远有一个可用的 AIProvider,
        这样界面不必到处写 if provider is not None。"""
        provider = NullAIProvider()
        self.assertEqual(provider.judge_batch([JudgeItem("w_1", "a", "b", "c")]), [])
        self.assertEqual(provider.chat("人设", [], "你好"), "")
        self.assertEqual(provider.diagnose({}), "")


# --------------------------------------------------------------------------
# 请求构造
# --------------------------------------------------------------------------

class TestEndpoint(TempDataDirTestCase):

    def test_appends_the_path(self):
        self.assertEqual(ApiProvider(settings())._endpoint(),
                         "https://example.test/v1/chat/completions")

    def test_trailing_slash_is_tolerated(self):
        """让用户去猜"该不该带斜杠"是很糟糕的体验。"""
        self.assertEqual(ApiProvider(settings(base_url="https://example.test/v1/"))._endpoint(),
                         "https://example.test/v1/chat/completions")

    def test_already_complete_url_is_not_doubled(self):
        provider = ApiProvider(settings(base_url="https://example.test/v1/chat/completions"))
        self.assertEqual(provider._endpoint(),
                         "https://example.test/v1/chat/completions")

    def test_empty_base_url_raises(self):
        with self.assertRaises(AIError):
            ApiProvider(settings(base_url=""))._endpoint()


class TestFailureModes(TempDataDirTestCase):
    """每一种失败都要变成一句人话,而不是一个原始异常。"""

    def test_missing_requests_library(self):
        ai_client.requests = None
        with self.assertRaises(AIError):
            ApiProvider(settings()).chat("人设", [], "你好")

    def test_missing_model(self):
        ai_client.requests = FakeRequests()
        with self.assertRaises(AIError):
            ApiProvider(settings(model="")).chat("人设", [], "你好")

    def test_missing_key(self):
        ai_client.requests = FakeRequests()
        with self.assertRaises(AIError):
            ApiProvider(settings(api_key="")).chat("人设", [], "你好")

    def test_network_error_is_wrapped(self):
        ai_client.requests = FakeRequests(raises=OSError("connection reset"))
        with self.assertRaises(AIError):
            ApiProvider(settings()).chat("人设", [], "你好")

    def test_http_error_mentions_the_status_code(self):
        ai_client.requests = FakeRequests(status_code=401, content="bad key")
        with self.assertRaises(AIError) as caught:
            ApiProvider(settings()).chat("人设", [], "你好")
        self.assertIn("401", str(caught.exception))

    def test_unexpected_response_shape(self):
        class Weird(FakeRequests):
            def post(self, url, json=None, headers=None, timeout=None):
                return FakeResponse(200, {"unexpected": True})
        ai_client.requests = Weird()
        with self.assertRaises(AIError):
            ApiProvider(settings()).chat("人设", [], "你好")


class TestRequestShaping(TempDataDirTestCase):

    def setUp(self):
        super().setUp()
        # 判分请求会被解析,所以假响应得长得像一份判分结果
        self.requests = FakeRequests(content='[{"w": "w_1", "v": 1}]')
        ai_client.requests = self.requests
        self.provider = ApiProvider(settings())

    def test_authorization_header_is_bearer(self):
        self.provider.chat("人设", [], "你好")
        self.assertEqual(self.requests.calls[-1]["headers"]["Authorization"],
                         "Bearer sk-test")

    def test_timeout_comes_from_settings(self):
        self.provider.chat("人设", [], "你好")
        self.assertEqual(self.requests.calls[-1]["timeout"], 5)

    def test_judge_prompt_is_static_so_the_prefix_cache_can_hit(self):
        """判分请求的 system 提示词必须逐字节相同 —— 这是命中缓存的前提。"""
        self.provider.judge_batch([JudgeItem("w_1", "bank", "银行", "银行")])
        first = self.requests.last_messages[0]["content"]
        self.provider.judge_batch([JudgeItem("w_2", "key", "钥匙", "钥匙")])
        self.assertEqual(first, self.requests.last_messages[0]["content"])

    def test_static_part_comes_first_and_variables_last(self):
        self.provider.judge_batch([JudgeItem("w_1", "bank", "银行", "银行")])
        messages = self.requests.last_messages
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("w_1", messages[-1]["content"])

    def test_judge_temperature_is_zero(self):
        """判分要的是稳定,不是创意。"""
        self.provider.judge_batch([JudgeItem("w_1", "bank", "银行", "银行")])
        self.assertEqual(self.requests.last_payload["temperature"], 0.0)

    def test_streaming_is_off(self):
        self.provider.chat("人设", [], "你好")
        self.assertFalse(self.requests.last_payload["stream"])


class TestTokenTiers(TempDataDirTestCase):
    """输出 token 是账单的大头 —— 分级额度就是最直接的刹车。"""

    def setUp(self):
        super().setUp()
        self.requests = FakeRequests(content='[{"w": "w_1", "v": 1}]')
        ai_client.requests = self.requests
        self.provider = ApiProvider(settings())

    def test_judging_one_word_uses_the_small_tier(self):
        self.provider.judge_batch([JudgeItem("w_1", "bank", "银行", "银行")])
        self.assertEqual(self.requests.last_payload["max_tokens"],
                         ai_client.MAX_TOKENS_JUDGE)

    def test_batch_budget_grows_with_the_batch(self):
        items = [JudgeItem("w_%d" % i, "a", "b", "c") for i in range(10)]
        self.provider.judge_batch(items)
        self.assertGreater(self.requests.last_payload["max_tokens"],
                           ai_client.MAX_TOKENS_JUDGE)

    def test_batch_budget_is_capped(self):
        items = [JudgeItem("w_%d" % i, "a", "b", "c") for i in range(500)]
        self.provider.judge_batch(items)
        self.assertEqual(self.requests.last_payload["max_tokens"],
                         ai_client.MAX_TOKENS_JUDGE_CEILING)

    def test_chat_uses_the_middle_tier(self):
        self.provider.chat("人设", [], "你好")
        self.assertEqual(self.requests.last_payload["max_tokens"],
                         ai_client.MAX_TOKENS_CHAT)

    def test_diagnose_uses_the_largest_tier(self):
        self.provider.diagnose({"total": 10})
        self.assertEqual(self.requests.last_payload["max_tokens"],
                         ai_client.MAX_TOKENS_DIAGNOSE)

    def test_diagnose_request_carries_counts_not_word_details(self):
        """诊断只带**汇总人数**,不带单词明细。

        数字现在还**说成人话**了(用户 2026-10-17:直接丢 JSON 会让评语
        突然变成分析报告的口气,和用户选的人设割裂),所以这里断言的是
        "人数出现在句子里",而不是某个 JSON 字段名。
        """
        self.provider.diagnose({"total": 10, "known": 3, "fuzzy": 2})
        body = self.requests.last_messages[-1]["content"]
        self.assertIn("10 个词", body)
        self.assertIn("记住 3", body)
        self.assertNotIn("w_1", body)


# --------------------------------------------------------------------------
# 判分结果解析
# --------------------------------------------------------------------------

class TestVerdictParsing(TempDataDirTestCase):

    def parse(self, content, items=None):
        self.requests = FakeRequests(content=content)
        ai_client.requests = self.requests
        items = items or [JudgeItem("w_1", "bank", "银行", "银行")]
        return ApiProvider(settings()).judge_batch(items)

    def test_plain_json_array(self):
        results = self.parse('[{"w": "w_1", "v": 1}]')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].grade, Grade.CORRECT)

    def test_markdown_fenced_json(self):
        """模型经常把 JSON 包在代码块里,不能因此判定失败。"""
        results = self.parse('```json\n[{"w": "w_1", "v": -1}]\n```')
        self.assertEqual(results[0].grade, Grade.WRONG)

    def test_json_with_surrounding_prose(self):
        results = self.parse('好的,结果如下:\n[{"w": "w_1", "v": 0}]\n希望有帮助。')
        self.assertEqual(results[0].grade, Grade.FUZZY)

    def test_all_three_verdicts(self):
        results = self.parse('[{"w": "a", "v": 1}, {"w": "b", "v": 0}, {"w": "c", "v": -1}]',
                             [JudgeItem("a", "x", "y", "z"), JudgeItem("b", "x", "y", "z"),
                              JudgeItem("c", "x", "y", "z")])
        self.assertEqual([r.grade for r in results],
                         [Grade.CORRECT, Grade.FUZZY, Grade.WRONG])

    def test_unknown_verdict_values_are_skipped_not_fatal(self):
        """模型给了个没见过的取值,跳过这一项就好,不该整体作废。"""
        results = self.parse('[{"w": "a", "v": 1}, {"w": "b", "v": 99}]',
                             [JudgeItem("a", "x", "y", "z"), JudgeItem("b", "x", "y", "z")])
        self.assertEqual(len(results), 1)

    def test_garbage_raises_a_readable_error(self):
        with self.assertRaises(AIError):
            self.parse('我不太确定该怎么回答你。')

    def test_empty_item_list_short_circuits(self):
        """一个词都没有就不该发请求 —— 白花钱。"""
        self.requests = FakeRequests()
        ai_client.requests = self.requests
        self.assertEqual(ApiProvider(settings()).judge_batch([]), [])
        self.assertEqual(self.requests.calls, [])

    def test_source_is_marked_as_ai(self):
        results = self.parse('[{"w": "w_1", "v": 1}]')
        self.assertEqual(results[0].source, "ai")


class TestChatHistory(TempDataDirTestCase):

    def setUp(self):
        super().setUp()
        self.requests = FakeRequests(content="这是回复。")
        ai_client.requests = self.requests
        self.provider = ApiProvider(settings())

    def test_history_is_trimmed_to_the_recent_window(self):
        """再往前的内容对当前回答没帮助,却要按输入 token 付钱。

        上限从 6 提到了 40(用户 2026-10-17:判分现在也进历史,一场 20 题
        的考试光判分就 20 轮,6 条会让前缀一直往前滑)。所以这里要造得
        比 40 更长才验得到裁剪。
        """
        limit = ai_client.MAX_HISTORY_MESSAGES
        history = [Turn(role="user" if i % 2 else "assistant",
                        content="第 %d 条" % i)
                   for i in range(limit + 20)]
        self.provider.chat("人设", history, "现在的问题")
        messages = self.requests.last_messages
        # 最后一条是这一次的新消息,前面最多带 limit 条历史
        self.assertLessEqual(len(messages), 1 + limit + 1)
        self.assertNotIn("第 0 条", json.dumps(messages, ensure_ascii=False))

    def test_persona_is_the_system_prompt(self):
        self.provider.chat("你是一位严格的老师。", [], "你好")
        self.assertEqual(self.requests.last_messages[0]["content"], "你是一位严格的老师。")

    def test_empty_persona_still_produces_a_system_prompt(self):
        self.provider.chat("", [], "你好")
        self.assertEqual(self.requests.last_messages[0]["role"], "system")

    def test_unknown_roles_are_downgraded_to_user(self):
        """存档里出现乱七八糟的 role 时,不能原样发给接口。"""
        self.provider.chat("人设", [Turn(role="机器人", content="嗯")], "你好")
        self.assertEqual(self.requests.last_messages[1]["role"], "user")


# --------------------------------------------------------------------------
# 对话调度:永不抛异常
# --------------------------------------------------------------------------

class TestChatService(TempDataDirTestCase):

    def fallback(self, topic, emotion):
        return "本地兜底: %s:%s" % (topic, emotion)

    @staticmethod
    def exploding(error):
        """造一个"在线但一定会失败"的后端。

        必须继承 ApiProvider 而不是 NullAIProvider —— 否则 is_online 会是
        False,ask() 根本不会走到调用后端那一步,这条错误路径就测不到了。
        """
        class Exploding(ApiProvider):
            def chat(self, persona, history, user_message):
                raise error
        return Exploding(settings())

    def test_offline_service_uses_local_lines(self):
        service = ChatService(NullAIProvider(), fallback=self.fallback)
        self.assertFalse(service.is_online)
        reply = service.ask("这是什么?")
        self.assertEqual(reply.text, "本地兜底: ask:thinking")
        # 离线的情绪由**本地规则**给,不走回复解析
        self.assertEqual(reply.emotion, "thinking")

    def test_no_provider_at_all_is_fine(self):
        service = ChatService(None, fallback=self.fallback)
        self.assertFalse(service.is_online)
        self.assertTrue(service.ask("这是什么?"))

    def test_blank_question_returns_nothing(self):
        service = ChatService(NullAIProvider(), fallback=self.fallback)
        reply = service.ask("   ")
        self.assertFalse(reply, "空回复要能被当假值用")
        self.assertEqual(reply.text, "")

    def test_provider_failure_falls_back_instead_of_raising(self):
        """这是最重要的一条:接口挂了,界面也不能崩。"""
        service = ChatService(self.exploding(AIError("接口挂了")), fallback=self.fallback)
        reply = service.ask("这是什么?")
        self.assertEqual(reply.text, "本地兜底: ask:confused")
        self.assertEqual(reply.emotion, "confused")
        self.assertIn("接口挂了", service.last_error)

    def test_unexpected_exception_is_also_caught(self):
        """插件里抛出的意外异常同样不能带崩对话。"""
        service = ChatService(self.exploding(ZeroDivisionError("插件式的事故")),
                              fallback=self.fallback)
        self.assertEqual(service.ask("这是什么?").text, "本地兜底: ask:confused")

    def test_failure_is_written_to_the_log(self):
        ChatService(self.exploding(AIError("接口挂了")),
                    fallback=self.fallback).ask("这是什么?")

        log = storage.logs_dir() / "errors.log"
        self.assertTrue(log.exists())
        self.assertIn("接口挂了", log.read_text(encoding="utf-8"))

    def test_missing_fallback_returns_empty_not_crash(self):
        service = ChatService(NullAIProvider())
        self.assertEqual(service.ask("这是什么?").text, "")

    def test_successful_exchange_is_remembered(self):
        self.requests = FakeRequests(content="这是回复。")
        ai_client.requests = self.requests
        service = ChatService(ApiProvider(settings()), fallback=self.fallback)
        self.assertTrue(service.is_online)
        self.assertEqual(service.ask("你好").text, "这是回复。")
        self.assertEqual(len(service.history), 2)

    def test_an_emotion_tag_in_the_reply_is_split_out(self):
        """**端到端**:模型按格式回了 [happy],服务层要拆成情绪 + 正文。

        界面拿 .emotion 去选立绘、拿 .text 去填对话框(见
        ui/views/chat._deliver)。这里锁的是"这两样真的分开了"。
        """
        self.requests = FakeRequests(content="[happy] 不错嘛,鱼片。")
        ai_client.requests = self.requests
        service = ChatService(ApiProvider(settings()), fallback=self.fallback)
        reply = service.ask("我答对了吗?")
        self.assertEqual(reply.emotion, "happy")
        self.assertEqual(reply.text, "不错嘛,鱼片。")
        self.assertNotIn("[happy]", reply.text, "标记不能被显示出来")

    def test_the_raw_reply_goes_into_history_so_the_model_keeps_the_habit(self):
        """历史里存**原样**(带标记),不是净化后的正文。

        只喂模型净化后的文字,它会渐渐忘掉"开头要写情绪"这个约定。
        """
        self.requests = FakeRequests(content="[happy] 好。")
        ai_client.requests = self.requests
        service = ChatService(ApiProvider(settings()), fallback=self.fallback)
        service.ask("我答对了吗?")
        self.assertEqual(service.history[-1].content, "[happy] 好。")

    def test_memory_stays_bounded(self):
        self.requests = FakeRequests(content="回复")
        ai_client.requests = self.requests
        service = ChatService(ApiProvider(settings()), fallback=self.fallback)
        for i in range(20):
            service.ask("第 %d 个问题" % i)
        self.assertLessEqual(len(service.history), ai_client.MAX_HISTORY_MESSAGES)

    def test_reset_clears_the_conversation(self):
        self.requests = FakeRequests(content="回复")
        ai_client.requests = self.requests
        service = ChatService(ApiProvider(settings()), fallback=self.fallback)
        service.ask("你好")
        service.reset()
        self.assertEqual(service.history, [])

    def test_diagnose_falls_back_to_the_offline_text(self):
        service = ChatService(NullAIProvider(), fallback=self.fallback)
        self.assertEqual(service.diagnose({"total": 1}, offline_text="离线评语"), "离线评语")

    def test_diagnose_failure_also_falls_back(self):
        class Exploding(ApiProvider):
            def diagnose(self, summary):
                raise AIError("挂了")
        service = ChatService(Exploding(settings()), fallback=self.fallback)
        self.assertEqual(service.diagnose({"total": 1}, offline_text="离线评语"), "离线评语")

    def test_plugin_provider_counts_as_online(self):
        """判据是"不是空后端",不是"是 ApiProvider" ——
        否则插件写的后端会被无声地跳过。"""
        self.assertTrue(ChatService(CustomProvider()).is_online)
        self.assertFalse(ChatService(NullAIProvider()).is_online)


class CustomProvider(Provider):
    """模拟插件提供的第三方后端。

    它**不继承** NullAIProvider —— 这正是重点:判断"在线与否"的判据
    必须是"不是空后端",而不是"是内置的 ApiProvider"。
    """

    def judge_batch(self, items):
        return []

    def chat(self, persona, history, user_message):
        return "插件说的话"

    def diagnose(self, summary):
        return ""


if __name__ == "__main__":
    unittest.main(verbosity=2)
