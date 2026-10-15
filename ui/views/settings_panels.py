# -*- coding: utf-8 -*-
"""设置页的各个分区。

**为什么和 SettingsView 分开:** 这一页有五个分区、二十多个控件,合起来
四百行 —— 而其中真正"有逻辑"的只有一处:保存时把控件里的值写回设置、
读设置时把值填回控件。分区本身只是"把哪些控件摆在一起、每句说明怎么写",
是**内容**,不是流程。

分开之后这个文件回答"设置里有哪些选项",settings_view.py 回答
"这些选项什么时候读、什么时候写、改动什么时候生效"。
"""

import tkinter as tk
from typing import List

from core.characters import emotions_list
from core.config import (CHARACTER_SCALE_MAX, CHARACTER_SCALE_MIN,
                         DIALOG_OPACITY_MAX, DIALOG_OPACITY_MIN,
                         PANEL_OPACITY_MAX, PANEL_OPACITY_MIN, RESULT_PACK_ASK,
                         RESULT_PACK_MERGE, RESULT_PACK_NONE, RESULT_PACK_SEPARATE)
from core.i18n import LANGUAGE_NAMES
from core.paths import data_root, image_dir, save_dir

from ..forms import (LabeledCheck, LabeledChoice, LabeledEntry, LabeledScale,
                     hint_label)
from ..widgets import ghost_button, theme_color

# 分辨率候选。不做"任意尺寸"是因为窗口尺寸直接影响字体排布和
# 对话框的比例,而 4:3 和 21:9 下同一套比例的效果差得很远。
RESOLUTIONS = [
    ("1280 × 720(推荐)", "1280,720"),
    ("1366 × 768", "1366,768"),
    ("1440 × 900", "1440,900"),
    ("1600 × 900", "1600,900"),
    ("1920 × 1080", "1920,1080"),
    ("1024 × 640", "1024,640"),
]

THEME_CHOICES = [("深色(夜)", "default"), ("浅色(日)", "light")]

# 底板图允许的扩展名。放在 assets/ui/ 里、又不是背景图本身的,都能选。
PANEL_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")

# 这几个名字是"场景背景",不是底板图,列表里要排除掉,免得用户选错
BACKGROUND_NAMES = ("background.png", "bg.png", "background.jpg", "background.jpeg")


def panel_choices() -> List[str]:
    """扫 assets/ui/,列出可以当底板的图片(相对 assets/ 的路径)。

    用**扫目录**而不是写死一个列表:用户往文件夹里丢一张新图,重进设置页
    就能在列表里看到它 —— 不用改代码,也不用重启。
    读不到目录就返回空列表(那时列表里只剩「默认(一层白)」)。
    """
    folder = image_dir() / "ui"
    try:
        names = sorted(item.name for item in folder.iterdir() if item.is_file())
    except OSError:
        return []
    return ["ui/%s" % name for name in names
            if name.lower().endswith(PANEL_IMAGE_SUFFIXES)
            and name.lower() not in BACKGROUND_NAMES]


def build_graphics(view, parent: tk.Misc) -> None:
    """图形:分辨率、全屏、主题。"""
    panel = view.section(parent, "图形", "窗口多大、要不要全屏、白天用还是晚上用。")
    current = "%d,%d" % (view.app.settings.ui.width, view.app.settings.ui.height)
    view.resolution = LabeledChoice(panel, view.theme, "分辨率", RESOLUTIONS, current)
    view.fullscreen = LabeledCheck(panel, view.theme, "全屏", "按 F11 也能随时切换。",
                                   view.app.settings.ui.fullscreen)
    view.theme_choice = LabeledChoice(panel, view.theme, "主题", THEME_CHOICES,
                                      view.app.settings.ui.theme)


def build_scene(view, parent: tk.Misc) -> None:
    """界面底板与立绘。

    底板以前是不透明的深色,背景基本看不见。现在它是一张**图层**:
    默认一层白,也可以换成用户自己的图片,透明度可调。
    """
    panel = view.section(
        parent, "界面底板与立绘",
        "主界面左侧那块底、学习页的单词框,都可以换成你自己的图片。")
    settings = view.app.settings.ui

    view.panel_image = LabeledChoice(
        panel, view.theme, "底板图片",
        [("默认(一层白)", "")] + [(name, name) for name in panel_choices()],
        settings.panel_image)
    row = tk.Frame(panel, bg=theme_color(view.theme, "panel"))
    row.pack(fill="x", padx=18, pady=(0, 4))
    ghost_button(row, "把图片放到 assets/ui/", view.open_material_folder,
                 view.theme).pack(side="left")
    tk.Label(row, text="放好后点「放弃修改」再进来,就能在列表里看到",
             bg=theme_color(view.theme, "panel"),
             fg=theme_color(view.theme, "text_dim"), anchor="w",
             font=("Microsoft YaHei UI", 9)).pack(side="left", padx=10)

    view.panel_opacity = LabeledScale(
        panel, view.theme, "底板透明度", PANEL_OPACITY_MIN, PANEL_OPACITY_MAX,
        settings.panel_opacity,
        hint="最低 0.50 —— 再透下去底上的字就读不清了")
    view.dialog_opacity = LabeledScale(
        panel, view.theme, "对话框透明度", DIALOG_OPACITY_MIN, DIALOG_OPACITY_MAX,
        settings.dialog_opacity, hint="老师说话那一块;文字永远不受影响")
    view.character_scale = LabeledScale(
        panel, view.theme, "老师大小", CHARACTER_SCALE_MIN, CHARACTER_SCALE_MAX,
        settings.character_scale, hint="调小会让老师往右上角退,给背景让位")


def build_matching(view, parent: tk.Misc) -> None:
    """判分方式与学习上限。"""
    panel = view.section(parent, "判分方式", "")
    hint_label(panel, view.theme,
               "「强制语义匹配」这个名字是反的,所以请照着下面读:\n"
               "  勾上 = 只和你导入的词表做字面对照(不联网、不花钱,但近义词会被判错)\n"
               "  不勾 = 拿不准的时候去问大模型(要配 API、要花钱,但能认近义表达)\n"
               "没配 API 时,这一项无论怎么选都只走本地对照。", wrap=680)
    view.force_match = LabeledCheck(
        panel, view.theme, "强制语义匹配(勾上 = 只用本地词表)", "",
        view.app.settings.study.force_semantic_match)

    view.daily_limit = LabeledEntry(panel, view.theme, "每日复习上限", width=8,
                                    hint="0 表示不限")
    view.exam_size = LabeledEntry(
        panel, view.theme, "随机加题上限", width=8,
        hint="只用于随机考试里「随机加入考试词包」那一项:一次最多混进几个。"
             "考试题量本身**不受这里影响** —— 勾了什么就考完什么")
    view.batch_size = LabeledEntry(
        panel, view.theme, "每次学习数量", width=8,
        hint="学一个词表包时一次带多少个词;0 表示不限,一次学完整包")
    view.page_size = LabeledEntry(
        panel, view.theme, "每屏显示词数", width=8,
        hint="学习页一屏放几个词。同一个组合也会按这个数切开 ——"
             "组合有 13 个词、这里填 5,就是 5 + 5 + 3 三屏")
    view.api_budget = LabeledEntry(
        panel, view.theme, "API 调用上限", width=8,
        hint="每场学习最多花几次请求;超出后自动变回离线判分")

    view.result_pack = LabeledChoice(
        panel, view.theme, "结果包",
        [("每次都问", RESULT_PACK_ASK),
         ("合并进当天", RESULT_PACK_MERGE),
         ("每次单独存", RESULT_PACK_SEPARATE),
         ("不生成", RESULT_PACK_NONE)],
        view.app.settings.study.result_pack_mode)
    hint_label(panel, view.theme,
               "结果包是「学完一场自动攒出来的词包」。一天学好几场的话,"
               "「合并进当天」会把它们并进同一个包,词包列表不会越堆越长;"
               "选「每次都问」则在每场结束时问一句。", wrap=680)


def build_api(view, parent: tk.Misc) -> None:
    """API 配置。"""
    panel = view.section(
        parent, "配置 API",
        "填了才能用大模型。任何一项没填,软件就是纯离线的,功能一样完整。")
    hint_label(panel, view.theme,
               "base_url 是 OpenAI 兼容的接口地址,例如 "
               "https://api.deepseek.com/v1 或 http://localhost:11434/v1。\n"
               "密钥只存在你自己电脑的 save/settings.json 里,不会上传到任何地方 ——"
               "这个软件除了你填的这个地址,不连接任何网络。", wrap=680)

    settings = view.app.settings.ai
    view.ai_enabled = LabeledCheck(panel, view.theme, "启用大模型",
                                   "关掉之后即使填了地址也不会发请求。",
                                   settings.enabled)
    view.api_base = LabeledEntry(panel, view.theme, "base_url", width=44)
    view.api_model = LabeledEntry(panel, view.theme, "模型名", width=24,
                                  hint="例如 deepseek-chat")
    view.api_key = LabeledEntry(panel, view.theme, "API 密钥", width=44, show="*")


def build_language(view, parent: tk.Misc) -> None:
    """界面语言。"""
    panel = view.section(
        parent, "语言",
        "这一项影响的是界面文字。真正学什么语言由你的词表决定 ——"
        "词表里写的是英语就学英语,写的是法语就学法语。")
    view.language = LabeledChoice(
        panel, view.theme, "界面语言",
        [(name, code) for code, name in LANGUAGE_NAMES.items()],
        view.app.settings.ui.language)
    hint_label(panel, view.theme,
               "第一版的界面文字只有中文一份,选英文也只影响少数提示语。"
               "这是实话,不想让你对着一个看起来能选、实际没变化的选项发懵。",
               wrap=680)


def build_paths(view, parent: tk.Misc) -> None:
    """数据与素材的路径,以及立绘情绪名的提示。"""
    panel = view.section(parent, "数据与素材", "你的东西都在这些文件夹里。")
    for title, path, description in (
        ("存档", save_dir(), "词库、设置、词包、日志都在这里。备份就是复制这个文件夹。"),
        ("素材", image_dir(), "立绘、背景和界面底板放这里。"),
        ("程序目录", data_root(), "save 和 assets 都在它下面。"),
    ):
        row = tk.Frame(panel, bg=theme_color(view.theme, "panel"))
        row.pack(fill="x", padx=18, pady=4)
        tk.Label(row, text=title, bg=theme_color(view.theme, "panel"),
                 fg=theme_color(view.theme, "text"), width=10, anchor="w",
                 font=("Microsoft YaHei UI", 10)).pack(side="left")
        tk.Label(row, text=str(path), bg=theme_color(view.theme, "panel"),
                 fg=theme_color(view.theme, "accent"), anchor="w",
                 font=("Microsoft YaHei UI", 10)).pack(side="left")
        tk.Label(row, text=description, bg=theme_color(view.theme, "panel"),
                 fg=theme_color(view.theme, "text_dim"), anchor="w",
                 font=("Microsoft YaHei UI", 9)).pack(side="left", padx=10)

    view.emotion_hint = tk.Label(
        panel, text="", bg=theme_color(view.theme, "panel"),
        fg=theme_color(view.theme, "text_dim"), anchor="w", justify="left",
        wraplength=680, font=("Microsoft YaHei UI", 9))
    view.emotion_hint.pack(fill="x", padx=18, pady=(8, 14))


def refresh_emotion_hint(view) -> None:
    view.emotion_hint.configure(text="立绘文件名用这些情绪名:%s"
                                     % " / ".join(emotions_list()))
