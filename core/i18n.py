# -*- coding: utf-8 -*-
"""界面文案表(中文优先,英文其次)。

**第一版的范围**:只覆盖导航、通用按钮和少量提示。
台词(角色说的话)在 lines.py,统计诊断文案在 stats.py ——
那两处各自处理自己的语言,不经过这里。把它们都塞进一张大表会让
"改一句台词"变成"在三个文件里找键名",反而更难维护。

取不到键时**返回键本身**而不是抛异常:界面上显示一句 "menu_start"
比整个窗口打不开要好得多,而且一眼就能看出是漏了翻译。
"""

from typing import Dict

DEFAULT_LANGUAGE = "zh-CN"
LANGUAGES = ("zh-CN", "en")

LANGUAGE_NAMES = {
    "zh-CN": "简体中文",
    "en": "English",
}

_ZH: Dict[str, str] = {
    # 主导航
    "app_title": "鲸鱼单词食堂",
    "menu_start": "开始",
    "menu_start_hint": "学习新词、复习到期的词、开始考试",
    "menu_wordset": "单词设置",
    "menu_wordset_hint": "导入词表、创建单词、导出备份",
    "menu_curve": "记忆曲线",
    "menu_curve_hint": "查看掌握情况与复习计划",
    "menu_ai": "AI 选择",
    "menu_ai_hint": "更换 AI 形象与人设,配置大模型",
    "menu_settings": "设置",
    "menu_settings_hint": "界面、学习参数与数据目录",

    # 通用按钮
    "ok": "确定",
    "cancel": "取消",
    "back": "返回",
    "save": "保存",
    "close": "关闭",
    "next": "下一个",
    "restart": "重新开始",
    "empty": "这里还什么都没有",

    # 学习 / 考试
    "study": "学习",
    "exam": "考试",
    "submit": "提交",
    "your_answer": "你的答案",
    "ask_teacher": "问老师",
    "progress": "进度",

    # 单词设置
    "import_words": "导入词表",
    "export_words": "导出词表",
    "new_word": "新增单词",
    "edit_word": "编辑",
    "delete_word": "删除",

    # 记忆曲线
    "mastered": "已掌握",
    "learning": "在学",
    "untouched": "未学习",
    "due_today": "今日到期",
    "mistakes": "易错词",
    "next_seven_days": "未来七天复习量",

    # 设置
    "language": "界面语言",
    "fullscreen": "全屏",
    "daily_due_limit": "每日复习上限",
    "force_semantic_match": "强制语义匹配(只用本地词表对照,不调用 API)",
    "api_enabled": "启用大模型",
    "api_base_url": "接口地址",
    "api_model": "模型名",
    "api_key": "密钥",
    "api_key_hint": "密钥只保存在本机 save/settings.json,不会上传到任何地方",
}

_EN: Dict[str, str] = {
    "app_title": "WhaleWordCanteen",
    "menu_start": "Start",
    "menu_start_hint": "Learn new words, review due ones, take an exam",
    "menu_wordset": "Word Sets",
    "menu_wordset_hint": "Import, create and export word lists",
    "menu_curve": "Memory Curve",
    "menu_curve_hint": "Mastery summary and review schedule",
    "menu_ai": "AI Teacher",
    "menu_ai_hint": "Change character, persona and model settings",
    "menu_settings": "Settings",
    "menu_settings_hint": "Language, study parameters and data folder",

    "ok": "OK",
    "cancel": "Cancel",
    "back": "Back",
    "save": "Save",
    "close": "Close",
    "next": "Next",
    "restart": "Restart",
    "empty": "Nothing here yet",

    "study": "Study",
    "exam": "Exam",
    "submit": "Submit",
    "your_answer": "Your answer",
    "ask_teacher": "Ask the teacher",
    "progress": "Progress",

    "import_words": "Import",
    "export_words": "Export",
    "new_word": "New word",
    "edit_word": "Edit",
    "delete_word": "Delete",

    "mastered": "Mastered",
    "learning": "Learning",
    "untouched": "New",
    "due_today": "Due today",
    "mistakes": "Tricky words",
    "next_seven_days": "Upcoming reviews",

    "language": "Language",
    "fullscreen": "Fullscreen",
    "daily_due_limit": "Daily review limit",
    "force_semantic_match": "Force local matching (never calls the API)",
    "api_enabled": "Enable model",
    "api_base_url": "Base URL",
    "api_model": "Model",
    "api_key": "API key",
    "api_key_hint": "The key stays in save/settings.json on this machine only",
}

TABLES = {"zh-CN": _ZH, "en": _EN}

# 当前语言。做成模块级状态是因为界面里到处都在取文案,
# 让每个控件都传一遍语言参数会污染所有函数签名。
# 这是个单机单用户的软件,全局状态在这里是合理的。
_current = DEFAULT_LANGUAGE


def set_language(language: str) -> None:
    """切换界面语言。不认识的语言一律回退到默认语言,不报错。"""
    global _current
    _current = language if language in TABLES else DEFAULT_LANGUAGE


def translate(key: str, **kwargs) -> str:
    """取一条文案。取不到就原样返回键名 —— 见模块开头的说明。"""
    table = TABLES.get(_current, _ZH)
    text = table.get(key) or _ZH.get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            # 占位符对不上时宁可显示原文,也不要抛异常把界面带崩
            return text
    return text
