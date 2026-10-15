# -*- coding: utf-8 -*-
"""找素材文件:背景图和立绘。

**为什么要单独一个模块。** 这两件事的共同点是"**文件到底在不在**":

* core 层只负责**算路径**(见 core.characters.AiCharacter.image_path),
  它刻意不碰文件系统 —— 那让 characters 能在不接触磁盘的情况下测。
* 但"有没有这张图"是用户素材决定的事实,只有界面层知道。

于是判断落在这里,而且带上回退规则:

* 背景图依次试几个常见文件名 —— 要求用户必须命名成某个特定名字,
  是那种"文档里写了但没人看"的规矩。
* 立绘**找不到某个情绪就退回 normal** —— 大多数用户只画一张正面立绘,
  那样至少还有个人站在那儿,而不是一个灰框。
"""

from typing import Optional

from core.paths import image_dir

# 背景图的候选文件名。第一个存在的就用它。
BACKGROUND_NAMES = ("ui/background.png", "ui/bg.png", "ui/background.jpg")


def background_image() -> Optional[str]:
    """找一个能用的背景图。都没有就返回 None,由渲染器用渐变兜底。"""
    for name in BACKGROUND_NAMES:
        if (image_dir() / name).exists():
            return name
    return None


def character_image(character, emotion: str,
                    normal: str = "normal") -> Optional[str]:
    """当前形象某情绪的立绘路径,**找不到就退到 normal**。

    character 为 None(没有形象)时返回 None,调用方会渲染占位框。
    """
    if character is None:
        return None
    for candidate in (emotion, normal):
        relative = character.image_path(candidate)
        if (image_dir() / relative).exists():
            return relative
    # 一个都没有:退回期望路径,让 load_image 画一个"该放这儿"的占位框
    return character.image_path(emotion)
