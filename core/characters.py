# -*- coding: utf-8 -*-
"""AI 形象与人设。

规格里把这两件事分得很清楚,代码里也照做:
  形象(AiCharacter) —— 立绘图片。同一个形象可以有多种情绪的表情。
  人设(Persona)     —— 一段文本,是发给大模型的提示词。

两者互相独立、可以自由组合:同一个形象能配不同人设。
这正好是规格里"一个形象可以组合不同的人设"的意思。

图片全部由用户自备,放在:
  assets/ai/<形象目录>/<情绪>.png
例如 assets/ai/default/happy.png。缺图时会由 ui 层渲染占位框,
所以这里只负责算路径,不负责检查文件是否存在。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .interfaces import ALL_EMOTIONS, EMOTION_NORMAL

# 图片放在这个子目录下(相对于 assets/)
AI_IMAGE_SUBDIR = "ai"

# --------------------------------------------------------------------------
# 内置项的"历史版本"记录
# --------------------------------------------------------------------------
#
# ⚠️ **别删这些常量。** 它们是判断"用户改过内置人设没有"的唯一证据:
# 内置项会连内容一起存进 save/characters.json,所以升级时只能靠
# "它是否还等于当初那份"来区分"没动过"和"用户自己改的"。
# 删掉它们,下次升级就只能二选一:要么不升级(用户看不到新内容),
# 要么无脑覆盖(吃掉用户的自定义)。两条都不能接受。
#
# 格式:加了新版本就把上一版的默认值追加上来,旧的**保留**。

# 第一版默认人设(温柔的单词老师)
_LEGACY_PERSONA_PROMPTS = (
    "你是一位温柔、有耐心的语言老师,正在陪学生背单词。"
    "说话简短亲切,像朋友一样,每次不超过两句话。"
    "学生答对时给予真诚的肯定,答错时先鼓励再给出正确释义。"
    "不要长篇大论,不要列清单,不要用markdown格式。",
)

# 第一版默认形象名(显示名从"默认老师"改成"deepseek")
_LEGACY_CHARACTER_NAMES = ("默认老师",)


@dataclass
class AiCharacter:
    """一个 AI 形象的立绘集合。"""

    id: str
    name: str
    directory: str = ""            # 相对 assets/ai/ 的目录名;留空则用 id
    description: str = ""

    @property
    def folder(self) -> str:
        return self.directory or self.id

    def image_path(self, emotion: str) -> str:
        """返回某情绪的图片路径,**相对于 assets/**。

        返回相对路径而不是绝对路径,是为了让存档能在不同电脑之间拷贝 ——
        写死 C:\\Users\\某人\\... 的话换台机器就全失效了。
        """
        return "%s/%s/%s.png" % (AI_IMAGE_SUBDIR, self.folder, emotion)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "directory": self.directory,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AiCharacter":
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            directory=data.get("directory", ""),
            description=data.get("description", ""),
        )


@dataclass
class Persona:
    """一段人设 = 一个发给大模型的提示词。"""

    id: str
    name: str
    prompt: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "prompt": self.prompt}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Persona":
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            prompt=data.get("prompt", ""),
        )


def default_character() -> AiCharacter:
    """内置的默认形象(DeepSeek 鲸鱼娘)。用户放进图片就能立刻看到效果。

    id 保持 `"default"` 不变 —— 它是**存档里的坐标**
    (save/characters.json 的 selected_character 指向它),改名会让老存档
    选中的形象凭空消失。要变的是显示名和说明。
    """
    return AiCharacter(
        id="default",
        name="deepseek",
        directory="default",
        description="默认形象:DeepSeek 鲸鱼娘。把你的立绘放进 "
                    "assets/ai/default/ 即可替换(normal.png 是必须的那张)。",
    )


def default_persona() -> Persona:
    """内置的默认人设:语言教师·DeepSeek 人设。

    正文在 core/persona_text.py(那一段很长,而且是"内容不是代码")。
    这里只负责拼上**回复格式规范**。

    ⚠️ 拼接顺序有讲究:人设正文在前、格式规范在后。
    格式规范要能跟着代码一起升级(比如以后情绪白名单变了),所以不能写死在
    人设正文里;但前缀缓存要求"前面那一段逐字节不变" —— 把易变的放在末尾,
    人设那段就还能长期命中缓存(见 core/ai_client.py 开头的说明)。
    """
    from .persona_text import DEEPSEEK_TEACHER_PROMPT
    from .reply_format import FORMAT_HINT

    return Persona(
        id="default",
        name="语言教师·deepseek",
        prompt="%s\n\n%s" % (DEEPSEEK_TEACHER_PROMPT, FORMAT_HINT),
    )


@dataclass
class CharacterLibrary:
    """形象与人设的合集,以及当前选中项。

    整体存成一个文件(save/characters.json),因为这些数据量很小,
    拆成多文件反而增加了读写的复杂度。
    """

    characters: List[AiCharacter] = field(default_factory=list)
    personas: List[Persona] = field(default_factory=list)
    selected_character: str = "default"
    selected_persona: str = "default"

    def ensure_defaults(self) -> None:
        """保证至少有一个形象和一个人设可用。

        首次运行、或者用户把文件删空了,界面也不该显示空白。
        同时会把**没被改过的**内置形象 / 人设升级到最新版(见 upgrade_defaults)。
        """
        if not self.characters:
            self.characters.append(default_character())
        if not self.personas:
            self.personas.append(default_persona())
        self.upgrade_defaults()
        if not self.find_character(self.selected_character):
            self.selected_character = self.characters[0].id
        if not self.find_persona(self.selected_persona):
            self.selected_persona = self.personas[0].id

    def upgrade_defaults(self) -> None:
        """把**原样未改**的内置形象 / 人设更新成当前版本。

        **为什么必须有这一步**:内置项是**存进存档**的(save/characters.json),
        所以改了 `default_persona()` 里的文字,老存档读出来还是旧的那份 ——
        用户在界面上看到的仍是旧人设,新写的内容一个字都到不了他眼前。

        **为什么不能无脑覆盖**:用户可能已经改过内置人设(界面允许编辑)。
        那属于用户的东西,不能被一次升级吃掉。

        所以判据是"**它还是当初那份吗**":只有当 id 对得上、而且内容与
        **上一版的默认值**逐字相同时才替换。用户动过一个字,就一律保留。
        记下这些历史默认值是为了这个 —— 别删,它们是"用户改过没有"的证据。
        """
        self._upgrade_persona("default", _LEGACY_PERSONA_PROMPTS, default_persona())
        self._upgrade_character("default", _LEGACY_CHARACTER_NAMES,
                                default_character())

    def _upgrade_persona(self, persona_id: str, legacy_prompts, fresh) -> None:
        found = self.find_persona(persona_id)
        if found is None:
            return
        if found.prompt.strip() not in legacy_prompts:
            return                     # 用户改过,或已经是新版 —— 都不动
        found.name = fresh.name
        found.prompt = fresh.prompt

    def _upgrade_character(self, character_id: str, legacy_names, fresh) -> None:
        found = self.find_character(character_id)
        if found is None:
            return
        if found.name.strip() not in legacy_names:
            return
        found.name = fresh.name
        found.description = fresh.description

    def find_character(self, character_id: str) -> Optional[AiCharacter]:
        for character in self.characters:
            if character.id == character_id:
                return character
        return None

    def find_persona(self, persona_id: str) -> Optional[Persona]:
        for persona in self.personas:
            if persona.id == persona_id:
                return persona
        return None

    def current_character(self) -> AiCharacter:
        self.ensure_defaults()
        found = self.find_character(self.selected_character)
        return found if found else default_character()

    def current_persona(self) -> Persona:
        self.ensure_defaults()
        found = self.find_persona(self.selected_persona)
        return found if found else default_persona()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "selected_character": self.selected_character,
            "selected_persona": self.selected_persona,
            "characters": [c.to_dict() for c in self.characters],
            "personas": [p.to_dict() for p in self.personas],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CharacterLibrary":
        """忠实还原,不做修复。

        修复交给 load_library()。解析和修复分开是有意为之:
        如果 from_dict 顺手补默认值,to_dict/from_dict 就不再是可逆的,
        调试时会看到"我明明存了空库,读出来却有默认形象"这种莫名其妙的景象。
        """
        return cls(
            characters=[AiCharacter.from_dict(c) for c in data.get("characters", [])],
            personas=[Persona.from_dict(p) for p in data.get("personas", [])],
            selected_character=data.get("selected_character", "default"),
            selected_persona=data.get("selected_persona", "default"),
        )


def load_library() -> CharacterLibrary:
    """从存档读形象与人设。没有存档或内容为空时,补上内置默认。"""
    from . import storage  # 局部 import,避免 storage <-> characters 循环依赖

    data = storage.load_characters_data()
    library = CharacterLibrary.from_dict(data) if isinstance(data, dict) else CharacterLibrary()
    library.ensure_defaults()
    return library


def save_library(library: CharacterLibrary) -> None:
    from . import storage

    storage.save_characters_data(library.to_dict())


def emotions_list() -> List[str]:
    """界面下拉框用的情绪选项。"""
    return list(ALL_EMOTIONS)


DEFAULT_EMOTION = EMOTION_NORMAL
