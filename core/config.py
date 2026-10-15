# -*- coding: utf-8 -*-
"""用户设置的数据模型与默认值。

本模块只描述设置"长什么样"和"默认是什么",**不做任何文件读写** ——
读写在 storage.py,它是唯一碰 save/ 目录的模块。

合并策略很重要:读设置时,缺失的字段一律用默认值补齐,而不是报错或忽略。
这样老版本的 settings.json 在新版本里依然能读,
新加的设置项也能自动获得默认值 —— 用户不需要手动改文件。
"""

from dataclasses import dataclass, field, replace
from typing import Any, Dict

# 设置文件的结构版本。将来做不兼容的改动时靠它分流。
SETTINGS_VERSION = 1

# 「学完这一场,结果包怎么处理」。存的是这几个字符串,不是 0/1/2 ——
# 存档要给人看,`"result_pack_mode": "merge"` 比 `: 1` 好读得多。
RESULT_PACK_ASK = "ask"            # 每次学完都问一句(默认)
RESULT_PACK_MERGE = "merge"        # 并进今天已有的那个学习结果包
RESULT_PACK_SEPARATE = "separate"  # 单独存一个新词包(1.2 及以前的行为)
RESULT_PACK_NONE = "none"          # 不生成词包


# 立绘的大小与位置。取值是**相对窗口的比例**,不是像素 —— 换个分辨率之后
# 构图应该保持原样,而不是让人在 1920 下重新调一遍。
#
# 位置给的是立绘**右下角**的落点(见 ui/scene.py 的 character_rect)。
# 默认 (0.995, 0.67):立绘贴在右上,底边正好停在对话框上沿(0.67 就是
# 框上沿所在的高度),所以脸和上半身完全露出来,也不会和对话框右下角
# 那排按钮叠在一起。调小 y 会让立绘往下坐、被对话框挡住。
CHARACTER_SCALE_MIN, CHARACTER_SCALE_MAX = 0.6, 1.4
CHARACTER_ANCHOR_X_MIN, CHARACTER_ANCHOR_X_MAX = 0.5, 1.0
CHARACTER_ANCHOR_Y_MIN, CHARACTER_ANCHOR_Y_MAX = 0.5, 1.0

# 内容底板(主界面左侧那一块、学习页的单词框那一块)的透明度。
#
# 底板是一张**图层**:默认是一层白,也可以换成你自己放进 assets/ui/ 的图片。
# 它盖在背景和立绘上面,所以"改透明度"改的是这张图有多透。
#
# ⚠️ 下限为什么是 0.5 而不是 0:底板上面坐的是**真控件**,它们的字色只能是
# 一套固定的。白底压到五成以下会变成一块中间灰,那时浅色字和深色字都只有
# 1:1 到 2:1 —— 不是"不够好看",而是根本读不出来。与其让滑块能拉到读不清
# 的地方,不如在这里就挡住。这条下限是单元测试逐档验对比度时逼出来的。
PANEL_OPACITY_MIN, PANEL_OPACITY_MAX = 0.5, 1.0
PANEL_OPACITY_DEFAULT = 0.80

# 对话框的透明度。它和内容底板是两个地方(一个是"老师说话",一个是"单词"),
# 而且对话框的文字是画在图里的、永远清晰,所以它可以比底板透得多。
DIALOG_OPACITY_MIN, DIALOG_OPACITY_MAX = 0.3, 1.0


def clamp_setting(value: float, low: float, high: float) -> float:
    """把一个越界的设置夹回合法范围。

    越界值不该让程序出错 —— 存档可能被手工改过,老版本的字段范围也可能
    和现在不同。夹一次比弹一个"设置不对"的窗要友好得多。
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return low
    return max(low, min(high, number))


@dataclass
class UiSettings:
    """界面相关设置。"""

    language: str = "zh-CN"       # 界面语言,影响 i18n 取哪套文案
    width: int = 1280
    height: int = 720
    fullscreen: bool = False
    theme: str = "default"        # 主题名,对应 theme.py 里的一套配色

    # 立绘:大小倍数 + 右下角落点。见上面那组常量。
    # x 默认贴住右边界(0.995):按钮行在对话框右下角,立绘再往左一点
    # 就会和那排按钮叠在一起。y = 0.67 正好是对话框上沿的高度 ——
    # 立绘底边停在框上沿,脸和上半身完全露出来。
    character_scale: float = 1.0
    character_anchor_x: float = 0.995
    character_anchor_y: float = 0.67

    # 内容底板:主界面左侧那一块、学习/考试页的单词框那一块。
    # 默认是一层白(不带任何图片),这样"透明度"这个滑块的效果一眼可见。
    panel_image: str = ""
    panel_opacity: float = PANEL_OPACITY_DEFAULT

    # 对话框的不透明度。它和内容底板是两个地方 —— 一个是"老师说话的地方",
    # 一个是"单词所在的地方",想调成不一样是很自然的需求。
    dialog_opacity: float = 0.82


@dataclass
class StudySettings:
    """学习与考试的行为设置。"""

    # ⚠️ 规格里的用词容易误解,这里写清楚:
    #   强制语义匹配 = True   → 只用本地词表做字面比对(省 Token,不联网)
    #   强制语义匹配 = False  → 允许在"歧义带"调用大模型做语义判断
    # 名字听起来像"开了才智能",其实正好相反。界面上必须配一行说明。
    force_semantic_match: bool = True

    daily_due_limit: int = 50           # 每天最多推送多少复习词,0 表示不限
    exam_size: int = 20                 # 每场考试抽多少个词

    # 一个词表包可能有上千个词,一口气学完是不现实的。这一项决定
    # 「点开始学习后默认带多少个词」,0 表示不限(学到包尾)。
    # 起点弹窗里可以临时改这一次的数量,不改的永远是这一项。
    batch_size: int = 20

    # 学习页**一屏显示几个词**。同一个组合里的词也按这个数切开 ——
    # 用户 2026-10-15 的要求:"如果第一组有 100 词,那么不应该显示 100 词"。
    # 一个组合有 13 个词时:第 1 屏 5 个、第 2 屏 5 个、第 3 屏 3 个,
    # 第 4 次「下一组」才进入下一个组合。
    #
    # 为什么要有上限:组合是**用户导入词表时给的**,可能是课本的一个单元
    # (十几个词),也可能被人当成"整本书"打成一组。不做上限的话,
    # 一屏塞进上百张卡片,用户根本不知道从哪看起。
    page_size: int = 5

    # 学完一场之后结果包怎么处理,取值是上面那几个 RESULT_PACK_* 常量
    result_pack_mode: str = RESULT_PACK_ASK

    # 预算护栏:单场学习/考试最多发起几次 API 请求(含批量)。
    # 超出后自动降级为纯离线,并在界面上说明。宁可少说话,也不能悄悄烧钱。
    max_api_calls_per_session: int = 20


@dataclass
class AiSettings:
    """大模型接入设置。默认关闭 —— 软件开箱即用且完全离线。"""

    enabled: bool = False
    base_url: str = ""                  # OpenAI 兼容端点,例如 https://api.deepseek.com/v1
    model: str = ""
    api_key: str = ""
    timeout_seconds: int = 20

    @property
    def is_configured(self) -> bool:
        """是否真的可以发起请求。三个字段缺一不可。"""
        return bool(self.enabled and self.base_url and self.model and self.api_key)


@dataclass
class Settings:
    """全部设置的根对象。"""

    version: int = SETTINGS_VERSION
    ui: UiSettings = field(default_factory=UiSettings)
    study: StudySettings = field(default_factory=StudySettings)
    ai: AiSettings = field(default_factory=AiSettings)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "ui": {
                "language": self.ui.language,
                # 分辨率在 JSON 里存成 [宽, 高],读起来比两个散字段直观
                "resolution": [self.ui.width, self.ui.height],
                "fullscreen": self.ui.fullscreen,
                "theme": self.ui.theme,
                "character_scale": self.ui.character_scale,
                "character_anchor_x": self.ui.character_anchor_x,
                "character_anchor_y": self.ui.character_anchor_y,
                "panel_image": self.ui.panel_image,
                "panel_opacity": self.ui.panel_opacity,
                "dialog_opacity": self.ui.dialog_opacity,
            },
            "study": {
                "force_semantic_match": self.study.force_semantic_match,
                "daily_due_limit": self.study.daily_due_limit,
                "exam_size": self.study.exam_size,
                "max_api_calls_per_session": self.study.max_api_calls_per_session,
                "batch_size": self.study.batch_size,
                "page_size": self.study.page_size,
                "result_pack_mode": self.study.result_pack_mode,
            },
            "ai": {
                "enabled": self.ai.enabled,
                "base_url": self.ai.base_url,
                "model": self.ai.model,
                "api_key": self.ai.api_key,
                "timeout_s": self.ai.timeout_seconds,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Settings":
        """从字典还原,缺失字段用默认值补齐(向前兼容的关键)。"""
        default = cls()
        raw_ui = data.get("ui") or {}
        raw_study = data.get("study") or {}
        raw_ai = data.get("ai") or {}

        # 分辨率:兼容 [宽,高] 列表,也兼容 {width,height} 字典
        resolution = raw_ui.get("resolution")
        if isinstance(resolution, (list, tuple)) and len(resolution) == 2:
            width, height = int(resolution[0]), int(resolution[1])
        elif isinstance(resolution, dict):
            width = int(resolution.get("width", default.ui.width))
            height = int(resolution.get("height", default.ui.height))
        else:
            width, height = default.ui.width, default.ui.height

        return cls(
            version=int(data.get("version", SETTINGS_VERSION)),
            ui=UiSettings(
                language=raw_ui.get("language", default.ui.language),
                width=width,
                height=height,
                fullscreen=bool(raw_ui.get("fullscreen", default.ui.fullscreen)),
                theme=raw_ui.get("theme", default.ui.theme),
                # 这几个是比例/倍数,一律夹进合法范围 —— 存档里的越界值
                # 应该被"修正",而不是让立绘被摆到窗口外面去
                character_scale=clamp_setting(
                    raw_ui.get("character_scale", default.ui.character_scale),
                    CHARACTER_SCALE_MIN, CHARACTER_SCALE_MAX),
                character_anchor_x=clamp_setting(
                    raw_ui.get("character_anchor_x", default.ui.character_anchor_x),
                    CHARACTER_ANCHOR_X_MIN, CHARACTER_ANCHOR_X_MAX),
                character_anchor_y=clamp_setting(
                    raw_ui.get("character_anchor_y", default.ui.character_anchor_y),
                    CHARACTER_ANCHOR_Y_MIN, CHARACTER_ANCHOR_Y_MAX),
                dialog_opacity=clamp_setting(
                    raw_ui.get("dialog_opacity", default.ui.dialog_opacity),
                    DIALOG_OPACITY_MIN, DIALOG_OPACITY_MAX),
                panel_image=str(raw_ui.get("panel_image", default.ui.panel_image) or ""),
                panel_opacity=clamp_setting(
                    raw_ui.get("panel_opacity", default.ui.panel_opacity),
                    PANEL_OPACITY_MIN, PANEL_OPACITY_MAX),
            ),
            study=StudySettings(
                force_semantic_match=bool(
                    raw_study.get("force_semantic_match", default.study.force_semantic_match)
                ),
                daily_due_limit=int(
                    raw_study.get("daily_due_limit", default.study.daily_due_limit)
                ),
                exam_size=int(raw_study.get("exam_size", default.study.exam_size)),
                max_api_calls_per_session=int(
                    raw_study.get(
                        "max_api_calls_per_session", default.study.max_api_calls_per_session
                    )
                ),
                batch_size=int(raw_study.get("batch_size", default.study.batch_size)),
        page_size=int(raw_study.get("page_size", default.study.page_size)),
                result_pack_mode=raw_study.get(
                    "result_pack_mode", default.study.result_pack_mode
                ),
            ),
            ai=AiSettings(
                enabled=bool(raw_ai.get("enabled", default.ai.enabled)),
                base_url=raw_ai.get("base_url", default.ai.base_url),
                model=raw_ai.get("model", default.ai.model),
                api_key=raw_ai.get("api_key", default.ai.api_key),
                timeout_seconds=int(raw_ai.get("timeout_s", default.ai.timeout_seconds)),
            ),
        )


def default_settings_dict() -> Dict[str, Any]:
    """仓库里那份 settings.json 模板的内容(提交进版本库,不含任何密钥)。"""
    return Settings().to_dict()
