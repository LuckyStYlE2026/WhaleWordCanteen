# -*- coding: utf-8 -*-
"""设置:图形、界面底板、判分方式、API、语言、数据位置。

**这一页最需要解释的是"强制语义匹配"。** 规格里的命名是反的:
开着它意味着"只跟本地词表对照"(省钱、不联网),
关掉它才允许在歧义的时候问大模型。名字听起来像"开了才智能",
所以那里的说明文字比别的选项都长 —— 让用户看懂,比让选项好看重要。

保存按钮是显式的:所有改动都攒到点保存那一刻才落盘。
自动保存会让"我改了一半想反悔"变得没法操作,而这个页面全是选项,
反悔是很常见的事。

**分区本身不在这里** —— 有哪些选项、每句说明怎么写,在
settings_panels.py。这里管的是"什么时候读、什么时候写、改动何时生效"。
"""

import os
import tkinter as tk

from core.i18n import set_language
from core.paths import image_dir, save_dir

from ..dialogs import info, warn
from ..forms import section_title
from ..panels import ScrollFrame
from ..widgets import ghost_button, primary_button, theme_color
from . import settings_panels
from .base import View


class SettingsView(View):
    """设置页。"""

    title_text = "设置"
    subtitle_text = "图形、界面底板、判分方式、API 密钥、语言"

    def build(self) -> None:
        self.header(self)

        self.scroller = ScrollFrame(self, self.theme)
        self.scroller.pack(fill="both", expand=True, padx=24, pady=(0, 8))
        body = self.scroller.body

        settings_panels.build_graphics(self, body)
        settings_panels.build_scene(self, body)
        settings_panels.build_matching(self, body)
        settings_panels.build_api(self, body)
        settings_panels.build_language(self, body)
        settings_panels.build_paths(self, body)
        self._build_footer()

        self.reload()

    # ---- 给分区用的两个工具(它们在另一个模块里调用) --------------------

    def _build_footer(self) -> None:
        bar = tk.Frame(self, bg=theme_color(self.theme, "background"))
        bar.pack(fill="x", padx=24, pady=(0, 16))

        primary_button(bar, "保存设置", self.on_save, self.theme).pack(side="right")
        ghost_button(bar, "放弃修改", self.reload, self.theme).pack(side="right", padx=8)

    def section(self, parent: tk.Misc, title: str, hint: str) -> tk.Frame:
        """一个分区的标题 + 面板容器。分区构建器往里面摆控件。"""
        section_title(parent, self.theme, title, hint)
        panel = tk.Frame(parent, bg=theme_color(self.theme, "panel"),
                         highlightthickness=1,
                         highlightbackground=theme_color(self.theme, "panel_light"))
        panel.pack(fill="x")
        return panel

    def open_material_folder(self) -> None:
        """把 assets/ui/ 打开给用户,省得他自己找路径。

        打不开(没有资源管理器、权限不足)不是错误:那个路径就在下面,
        用户自己走一趟就行。所以这里退回一个说明弹窗,而不是报错。
        """
        folder = image_dir() / "ui"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(folder))          # noqa: S606 —— Windows 专用
        except (OSError, AttributeError):
            info(self, "素材文件夹", "请手动打开这个文件夹:\n%s" % folder)

    # ---- 读写 ------------------------------------------------------------

    def reload(self) -> None:
        """把设置里的值重新填进控件。放弃修改也走它。"""
        settings = self.app.settings
        self.resolution.set("%d,%d" % (settings.ui.width, settings.ui.height))
        self.fullscreen.set(settings.ui.fullscreen)
        self.theme_choice.set(settings.ui.theme)
        self.character_scale.set(settings.ui.character_scale)
        self.panel_image.set(settings.ui.panel_image)
        self.panel_opacity.set(settings.ui.panel_opacity)
        self.dialog_opacity.set(settings.ui.dialog_opacity)
        self.force_match.set(settings.study.force_semantic_match)
        self.daily_limit.set(str(settings.study.daily_due_limit))
        self.exam_size.set(str(settings.study.exam_size))
        self.batch_size.set(str(settings.study.batch_size))
        self.page_size.set(str(settings.study.page_size))
        self.api_budget.set(str(settings.study.max_api_calls_per_session))
        self.result_pack.set(settings.study.result_pack_mode)

        self.ai_enabled.set(settings.ai.enabled)
        self.api_base.set(settings.ai.base_url)
        self.api_model.set(settings.ai.model)
        self.api_key.set(settings.ai.api_key)
        self.language.set(settings.ui.language)

        settings_panels.refresh_emotion_hint(self)

    def on_save(self) -> None:
        settings = self.app.settings
        try:
            width, height = [int(part) for part in self.resolution.get().split(",")]
            daily_limit = max(0, int(self.daily_limit.get() or 0))
            exam_size = max(1, int(self.exam_size.get() or 20))
            batch_size = max(0, int(self.batch_size.get() or 0))
            # 每屏至少 1 个。填 0 会让学习页一屏都不显示,那不是"不限",
            # 那是坏掉了 —— 所以下限是 1(和 batch_size 的 0 = 不限 不同)。
            page_size = max(1, int(self.page_size.get() or 5))
            budget = max(0, int(self.api_budget.get() or 0))
        except ValueError:
            warn(self, "保存失败", "数字格式不对。分辨率和几个上限都只能填整数。")
            return

        settings.ui.width, settings.ui.height = width, height
        settings.ui.fullscreen = self.fullscreen.get()
        settings.ui.language = self.language.get()
        settings.ui.character_scale = self.character_scale.get()
        settings.ui.panel_image = self.panel_image.get()
        settings.ui.panel_opacity = self.panel_opacity.get()
        settings.ui.dialog_opacity = self.dialog_opacity.get()

        settings.study.force_semantic_match = self.force_match.get()
        settings.study.daily_due_limit = daily_limit
        settings.study.exam_size = exam_size
        settings.study.batch_size = batch_size
        settings.study.page_size = page_size
        settings.study.max_api_calls_per_session = budget
        settings.study.result_pack_mode = self.result_pack.get()

        settings.ai.enabled = self.ai_enabled.get()
        settings.ai.base_url = self.api_base.get()
        settings.ai.model = self.api_model.get()
        settings.ai.api_key = self.api_key.get()

        set_language(settings.ui.language)
        self.app.save_settings()
        self.app.rebuild_ai()

        # 图形和主题是能立刻看见的,那就立刻让它生效 ——
        # 让用户"保存了却看不出变化"是最容易引起怀疑的一种反馈
        self.app.apply_geometry()

        # 先把改动报告给用户看,再换主题 —— 换主题会重建当前板块,
        # 也就是把这个对象销毁掉,之后就没人能弹窗了
        changed_theme = self.theme_choice.get() != self.app.theme.name
        self._report()
        if changed_theme:
            self.app.apply_theme(self.theme_choice.get())

    def _report(self) -> None:
        if self.app.settings.ai.is_configured:
            ai_state = "大模型已启用,判分时会在拿不准的地方向它确认。"
        elif self.app.settings.ai.enabled:
            ai_state = "启用了大模型,但 base_url / 模型名 / 密钥没填全,现在仍是离线。"
        else:
            ai_state = "现在是纯离线模式(不联网、不花钱)。"

        info(self, "设置已保存",
             "已存入:\n%s\n\n%s\n\n强制语义匹配:%s\n"
             % (save_dir() / "settings.json", ai_state,
                "开启(只用本地词表)" if self.app.settings.study.force_semantic_match
                else "关闭(允许问大模型)"))
