# -*- coding: utf-8 -*-
"""AI 选择:左边挑形象,右边挑人设。

规格把这两件事分得很清楚,界面也就照着分左右两块:
  形象 = 立绘图片,一个形象可以有多种情绪的表情。
  人设 = 一段文字,是发给模型的提示词。
两者互相独立,同一个形象可以配不同人设。

**这一页不导入图片。** 图片直接放进 assets/ai/<目录名>/ 就行,
界面负责把"该放哪儿、该叫什么名字"明明白白地写出来。
让用户在一个对话框里选文件、再拷来拷去,比直接告诉他路径更容易出错。
"""

import tkinter as tk

from core.characters import AiCharacter, Persona
from core.paths import image_dir

from ..dialogs import PersonaEditor, confirm, info
from ..prompts import ask_text
from ..forms import flat_button, section_title
from ..grids import CharacterGrid
from ..lists import SelectableTextList
from ..widgets import theme_color
from .base import View

EMOTION_HINT = ("把立绘放进 %s/ai/<目录名>/ 里,文件名用情绪名:"
                "normal / happy / sad / confused / thinking / surprised(.png)。\n"
                "只有 normal 也能用 —— 别的情绪会自动退到它。")


class AiSelectView(View):
    """AI 形象与人设。"""

    title_text = "AI 选择"
    subtitle_text = "挑一位老师,以及决定用不用大模型"

    def build(self) -> None:
        self.header(self)
        body = tk.Frame(self, bg=theme_color(self.theme, "background"))
        body.pack(fill="both", expand=True, padx=24, pady=(0, 16))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self._build_characters(body)
        self._build_personas(body)
        self.refresh()

    # ---- 左:形象 ---------------------------------------------------------

    def _build_characters(self, parent: tk.Misc) -> None:
        panel = tk.Frame(parent, bg=theme_color(self.theme, "panel"),
                         highlightthickness=1,
                         highlightbackground=theme_color(self.theme, "panel_light"))
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        section_title(panel, self.theme, "AI 形象",
                      EMOTION_HINT % image_dir())

        self.character_list = CharacterGrid(panel, self.theme,
                                            on_select=self.on_pick_character)
        self.character_list.pack(fill="both", expand=True, padx=10, pady=8)

        bar = tk.Frame(panel, bg=theme_color(self.theme, "panel"))
        bar.pack(fill="x", padx=12, pady=(0, 12))
        flat_button(bar, self.theme, "新建形象", self.on_new_character).pack(side="left")
        flat_button(bar, self.theme, "编辑", self.on_edit_character).pack(side="left",
                                                                      padx=6)
        flat_button(bar, self.theme, "删除", self.on_delete_character).pack(side="left")

    # ---- 右:人设 ---------------------------------------------------------

    def _build_personas(self, parent: tk.Misc) -> None:
        panel = tk.Frame(parent, bg=theme_color(self.theme, "panel"),
                         highlightthickness=1,
                         highlightbackground=theme_color(self.theme, "panel_light"))
        panel.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        section_title(panel, self.theme, "AI 人设",
                      "人设是一段文本,决定老师怎么说话。它和形象可以自由组合。")

        self.persona_list = SelectableTextList(panel, self.theme,
                                               on_select=self.on_pick_persona)
        self.persona_list.pack(fill="both", expand=True, padx=10, pady=8)

        bar = tk.Frame(panel, bg=theme_color(self.theme, "panel"))
        bar.pack(fill="x", padx=12, pady=(0, 12))
        flat_button(bar, self.theme, "新建人设", self.on_new_persona).pack(side="left")
        flat_button(bar, self.theme, "编辑", self.on_edit_persona).pack(side="left",
                                                                    padx=6)
        flat_button(bar, self.theme, "删除", self.on_delete_persona).pack(side="left")

    # ---- 数据 ------------------------------------------------------------

    def refresh(self) -> None:
        library = self.app.characters

        # 选中项默认停在"正在生效的那个"。用户进来直接点「编辑」时,
        # 期望编辑的是眼前高亮的那个,而不是列表第一项
        self._selected_character = (getattr(self, "_selected_character", "")
                                    or library.current_character().id)
        self._selected_persona = (getattr(self, "_selected_persona", "")
                                  or library.current_persona().id)

        self.character_list.fill([
            (character.id, character.name, character.description,
             self._thumb_path(character))
            for character in library.characters
        ])

        self.persona_list.fill(
            [(persona.id, persona.name, persona.prompt) for persona in library.personas],
            selected=self._selected_persona)

    def _thumb_path(self, character: AiCharacter):
        """缩略图用 normal 那张。没有就让 load_image 去渲染占位框。"""
        relative = character.image_path("normal")
        if (image_dir() / relative).exists():
            return relative
        return None

    # ---- 形象操作 --------------------------------------------------------

    def on_pick_character(self, character_id: str) -> None:
        self._selected_character = character_id

    def _current_character_id(self) -> str:
        # 列表里点了就用点的那个,没点过就用正在生效的那个 ——
        # 用户进来直接点"编辑",期望编辑的是眼前高亮的那个
        picked = getattr(self, "_selected_character", "")
        if not picked:
            picked = self.app.characters.current_character().id
        return picked

    def on_new_character(self) -> None:
        name = ask_text(self, self.theme, "新建形象", "给这位老师起个名字:")
        if not name:
            return
        directory = ask_text(self, self.theme, "新建形象",
                             "图片放在哪个目录名下?(assets/ai/…)\n"
                             "留空就用名字本身,填英文更稳妥。",
                             initial=name)
        if directory is None:
            return

        character = AiCharacter(id="char_%d" % (len(self.app.characters.characters) + 1),
                                name=name, directory=directory.strip() or name,
                                description="")
        self.app.characters.characters.append(character)
        self.app.characters.selected_character = character.id
        self._save()
        info(self, "新建形象",
             "已经建好了。把立绘放进:\n%s\n\n文件名用 normal.png / happy.png 这样。"
             % (image_dir() / "ai" / character.folder))

    def on_edit_character(self) -> None:
        character = self.app.characters.find_character(self._current_character_id())
        if character is None:
            info(self, "编辑形象", "先选中一位老师。")
            return

        name = ask_text(self, self.theme, "编辑形象", "名字:", character.name)
        if name is None:
            return
        description = ask_text(self, self.theme, "编辑形象", "一句话说明:",
                               character.description)
        if description is None:
            return
        directory = ask_text(self, self.theme, "编辑形象",
                             "图片目录名(相对 assets/ai/):", character.folder)
        if directory is None:
            return

        character.name = name or character.name
        character.description = description
        character.directory = directory.strip() or character.folder
        self._save()

    def on_delete_character(self) -> None:
        character = self.app.characters.find_character(self._current_character_id())
        if character is None:
            info(self, "删除形象", "先选中一位老师。")
            return
        if len(self.app.characters.characters) <= 1:
            info(self, "删除形象", "至少要留一位老师。")
            return
        if not confirm(self, "删除形象",
                       "确定删除「%s」吗?\n\n只是从列表里去掉,图片文件不会动。"
                       % character.name):
            return

        self.app.characters.characters = [
            c for c in self.app.characters.characters if c.id != character.id]
        self.app.characters.ensure_defaults()
        self._save()

    # ---- 人设操作 --------------------------------------------------------

    def on_pick_persona(self, persona_id: str) -> None:
        self._selected_persona = persona_id
        self.app.characters.selected_persona = persona_id
        self._save()

    def _current_persona_id(self) -> str:
        picked = getattr(self, "_selected_persona", "")
        if not picked:
            picked = self.app.characters.current_persona().id
        return picked

    def on_new_persona(self) -> None:
        editor = PersonaEditor(self, self.theme, "新建人设")
        self.wait_window(editor)
        if not editor.result:
            return
        name, prompt = editor.result
        persona = Persona(id="persona_%d" % (len(self.app.characters.personas) + 1),
                          name=name, prompt=prompt)
        self.app.characters.personas.append(persona)
        self.app.characters.selected_persona = persona.id
        self._save()

    def on_edit_persona(self) -> None:
        persona = self.app.characters.find_persona(self._current_persona_id())
        if persona is None:
            info(self, "编辑人设", "先选中一段人设。")
            return
        editor = PersonaEditor(self, self.theme, "编辑人设", persona.name, persona.prompt)
        self.wait_window(editor)
        if not editor.result:
            return
        name, prompt = editor.result
        persona.name = name
        persona.prompt = prompt
        self._save()

    def on_delete_persona(self) -> None:
        persona = self.app.characters.find_persona(self._current_persona_id())
        if persona is None:
            info(self, "删除人设", "先选中一段人设。")
            return
        if len(self.app.characters.personas) <= 1:
            info(self, "删除人设", "至少要留一段人设。")
            return
        if not confirm(self, "删除人设", "确定删除「%s」吗?" % persona.name):
            return

        self.app.characters.personas = [
            p for p in self.app.characters.personas if p.id != persona.id]
        self.app.characters.ensure_defaults()
        self._save()

    # ---- 保存 ------------------------------------------------------------

    def _save(self) -> None:
        """存盘并重建对话服务。

        人设改了要立刻生效,否则用户改完提示词回到学习页,发现老师
        说话还是老样子 —— 那会让人以为改动丢了。重建一次很便宜,
        而且注册表里的 API 后端是懒构造的,不会因为重建就发请求。
        """
        self.app.save_all()
        self.app.rebuild_ai()
        self.refresh()
