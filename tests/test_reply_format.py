# -*- coding: utf-8 -*-
"""AI 回复的格式解析,以及内置形象 / 人设的升级。

这些测试守两件事:

1. **游戏能把 AI 回复读懂。** 模型会在回复开头写 `[happy]` 之类的情绪标记,
   游戏要拆出情绪(选立绘)和正文(显示)。拆错的代价不对称:
   正文是给用户看的,所以**认不出来时必须一个字都不改**。
2. **改名 / 换人设要真的到用户眼前。** 内置项是存进存档的
   (save/characters.json),只改代码的话老存档读出来还是旧的 ——
   但又不能无脑覆盖,那会吃掉用户自己编辑过的人设。
"""

import unittest

from core.characters import (AiCharacter, CharacterLibrary, Persona,
                             default_character, default_persona)
from core.interfaces import ALL_EMOTIONS, EMOTION_HAPPY, EMOTION_NORMAL
from core.reply_format import FORMAT_HINT, parse_reply, strip_tag


class ReplyParsingTest(unittest.TestCase):
    """`[情绪] 正文` 的拆法。"""

    def test_a_known_tag_is_split_off(self):
        emotion, text = parse_reply("[happy] 不错嘛,鱼片。")
        self.assertEqual(emotion, EMOTION_HAPPY)
        self.assertEqual(text, "不错嘛,鱼片。")

    def test_no_tag_means_normal_and_text_untouched(self):
        emotion, text = parse_reply("这个词是回顾的意思。")
        self.assertEqual(emotion, EMOTION_NORMAL)
        self.assertEqual(text, "这个词是回顾的意思。")

    def test_every_whitelisted_emotion_is_understood(self):
        """白名单里的每个情绪都要认 —— 加新情绪时忘了改解析就抓到了。"""
        for emotion in ALL_EMOTIONS:
            got, text = parse_reply("[%s] 好。" % emotion)
            self.assertEqual(got, emotion, "认不出 [%s]" % emotion)
            self.assertEqual(text, "好。")

    def test_case_and_extra_spaces_are_tolerated(self):
        """模型常写大写、常多打空格。这两种都该认,而不是整句显示出来。"""
        self.assertEqual(parse_reply("[HAPPY] 好。")[0], EMOTION_HAPPY)
        self.assertEqual(parse_reply("[ happy ] 好。")[0], EMOTION_HAPPY)
        self.assertEqual(parse_reply("  [happy]好。")[0], EMOTION_HAPPY)

    def test_full_width_brackets_are_tolerated(self):
        """中文输入法打出来的是全角括号,模型也常这么写。"""
        self.assertEqual(parse_reply("【happy】好。")[0], EMOTION_HAPPY)

    def test_an_unknown_tag_is_kept_as_text(self):
        """**最重要的一条**:认不出来时一个字都不能改。

        宁可立绘不换(少个表情),也不能把用户要看的话删掉 ——
        那是内容出错,比少个表情严重得多。
        """
        emotion, text = parse_reply("[生气] 我不是胖。")
        self.assertEqual(emotion, EMOTION_NORMAL)
        self.assertEqual(text, "[生气] 我不是胖。", "认不出的标记被吃掉了")

    def test_a_bracket_inside_the_sentence_is_not_a_command(self):
        """正文中间的方括号是正常内容(固定搭配之类),不能当指令摘掉。"""
        emotion, text = parse_reply("这个词的搭配是 [make a decision]。")
        self.assertEqual(emotion, EMOTION_NORMAL)
        self.assertIn("[make a decision]", text)

    def test_an_empty_reply_is_safe(self):
        self.assertEqual(parse_reply(""), (EMOTION_NORMAL, ""))
        self.assertEqual(parse_reply("   "), (EMOTION_NORMAL, ""))
        self.assertEqual(parse_reply(None)[1], "")

    def test_a_tag_with_nothing_after_it_does_not_crash(self):
        emotion, text = parse_reply("[happy]")
        self.assertEqual(emotion, EMOTION_HAPPY)
        self.assertEqual(text, "")

    def test_strip_tag_only_wants_the_text(self):
        self.assertEqual(strip_tag("[sad] 唉。"), "唉。")

    def test_the_hint_lists_every_emotion(self):
        """给模型看的说明必须把可用情绪列全,否则它只会用 normal。"""
        for emotion in ALL_EMOTIONS:
            self.assertIn(emotion, FORMAT_HINT)


class DefaultPersonaTest(unittest.TestCase):
    """新默认人设:名字、内容、格式规范。"""

    def test_the_name_is_the_new_one(self):
        self.assertEqual(default_persona().name, "语言教师·deepseek")

    def test_it_carries_the_format_rules(self):
        """人设里必须带回复格式规范 —— 否则模型不知道能写 [情绪]。

        这一条是"游戏要能读懂回复"的前提:规范不在提示词里,
        模型就没有理由按那个格式回答,解析器再对也没东西可拆。
        """
        self.assertIn(FORMAT_HINT, default_persona().prompt)

    def test_the_format_rules_come_last(self):
        """格式规范要拼在人设**后面**。

        理由:前缀缓存要求"前面那段逐字节不变",而格式规范会随代码升级
        (情绪白名单可能变)。易变的放末尾,人设那段才能长期命中缓存。
        """
        prompt = default_persona().prompt
        self.assertTrue(prompt.endswith(FORMAT_HINT))
        self.assertLess(prompt.index("鲸鱼娘"), prompt.index(FORMAT_HINT))

    def test_it_keeps_the_character_brief(self):
        """人设里要有"最多两句话"这类硬约束。

        对话框只有 3~6 行,没有约束的话模型会写一大篇然后被截断。
        """
        prompt = default_persona().prompt
        self.assertIn("硬性要求", prompt)
        self.assertIn("两句话", prompt)

    def test_the_character_is_renamed_too(self):
        self.assertEqual(default_character().name, "deepseek")
        # id 是存档里的坐标,改名会让老存档选中的形象消失
        self.assertEqual(default_character().id, "default")


class UpgradeDefaultsTest(unittest.TestCase):
    """内置项升级:该换的换,该留的留。"""

    OLD_PROMPT = (
        "你是一位温柔、有耐心的语言老师,正在陪学生背单词。"
        "说话简短亲切,像朋友一样,每次不超过两句话。"
        "学生答对时给予真诚的肯定,答错时先鼓励再给出正确释义。"
        "不要长篇大论,不要列清单,不要用markdown格式。"
    )

    def _library_with(self, persona_prompt, persona_name="温柔的单词老师",
                      character_name="默认老师"):
        return CharacterLibrary(
            characters=[AiCharacter(id="default", name=character_name,
                                    directory="default")],
            personas=[Persona(id="default", name=persona_name,
                              prompt=persona_prompt)])

    def test_an_untouched_old_default_is_upgraded(self):
        """**这是升级能生效的关键。** 老存档里存的是旧人设,

        只改代码的话用户永远看不到新内容。
        """
        library = self._library_with(self.OLD_PROMPT)
        library.ensure_defaults()
        self.assertEqual(library.find_persona("default").name,
                         "语言教师·deepseek")
        self.assertIn("鲸鱼娘", library.find_persona("default").prompt)
        self.assertEqual(library.find_character("default").name, "deepseek")

    def test_a_user_edited_persona_is_never_overwritten(self):
        """用户可能改过内置人设 —— 那是他的东西,升级不能吃掉。"""
        mine = self.OLD_PROMPT + "另外请叫我老板。"
        library = self._library_with(mine, persona_name="我的人设",
                                     character_name="我的老师")
        library.ensure_defaults()
        found = library.find_persona("default")
        self.assertEqual(found.name, "我的人设")
        self.assertEqual(found.prompt, mine, "用户改过的人设被覆盖了")
        self.assertEqual(library.find_character("default").name, "我的老师")

    def test_a_custom_persona_with_another_id_is_untouched(self):
        """用户自己新建的人设(不是内置那个 id)完全不受影响。"""
        library = self._library_with(self.OLD_PROMPT)
        library.personas.append(Persona(id="mine", name="我的",
                                        prompt="你是猫娘。"))
        library.ensure_defaults()
        self.assertEqual(library.find_persona("mine").prompt, "你是猫娘。")

    def test_an_empty_library_gets_the_new_defaults(self):
        library = CharacterLibrary()
        library.ensure_defaults()
        self.assertEqual(library.find_persona("default").name,
                         "语言教师·deepseek")
        self.assertEqual(library.find_character("default").name, "deepseek")

    def test_upgrading_twice_is_harmless(self):
        """升级要是幂等的 —— 每次启动都会走一遍 ensure_defaults。"""
        library = self._library_with(self.OLD_PROMPT)
        library.ensure_defaults()
        first = library.find_persona("default").prompt
        library.ensure_defaults()
        self.assertEqual(library.find_persona("default").prompt, first)

    def test_the_selected_ids_still_resolve_after_upgrade(self):
        """升级只改内容,不能把选中项改丢 —— 那会让界面显示空白。"""
        library = self._library_with(self.OLD_PROMPT)
        library.ensure_defaults()
        self.assertEqual(library.current_persona().id, "default")
        self.assertEqual(library.current_character().id, "default")


if __name__ == "__main__":
    unittest.main()
