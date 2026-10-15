# -*- coding: utf-8 -*-
"""人工观察:AI 在回复开头写 [happy] 时,立绘会不会真的换掉。

## 为什么需要这个脚本

代码这条路是通的(回复开头的 `[情绪]` 会被拆出来去选立绘,见
core/reply_format.py),但**你光看是看不出来的** —— 因为:

    assets/ai/default/ 里只有 normal.png,其余 5 个情绪图全缺

而 ui/imagery.py 的规则是"找不到某情绪就**静默退回 normal**"
(那是有意的:大多数用户只画一张正面立绘,至少还有个人站着)。
于是 `[happy]` 被正确解析了,显示的却还是 normal —— 看着像没生效。

## 这个脚本做什么

1. 造一张**一眼能认出**的 happy.png(和 normal 完全不同的底色 + 大字 HAPPY),
   放进 assets/ai/default/ —— 这样"换没换"肉眼可辨;
2. 用一个假 AI 回复 `[happy] 我换了表情,你看到了吗?`,走**真实**的
   聊天发送路径(ui/views/chat.py 的 _deliver);
3. 最后告诉你:解析出的情绪是什么、实际取到的图片是哪个文件;
4. 关掉窗口后**把那张测试图删掉**,不留垃圾。

## 怎么用

    cd game
    python tools/observe_emotion_swap.py

然后看窗口里那位老师的立绘有没有变成那张写着 HAPPY 的图。

不需要填 API 密钥 —— 这个脚本自带假的后端。
"""

import os
import sys
import tkinter as tk
from pathlib import Path

# 让脚本能从 game/ 下直接跑(把 game/ 加进搜索路径)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.builtins import register_builtins            # noqa: E402
from core.interfaces import AIProvider, JudgeResult    # noqa: E402
from core.models import Grade, SOURCE_AI               # noqa: E402

EMOTION_UNDER_TEST = "happy"
REPLY = "[happy] 我换了表情,你看到了吗?"
TEST_IMAGE_SIZE = (512, 768)


def make_test_image(path: Path) -> None:
    """造一张一眼能认出的立绘。

    **必须和 normal 有明显区别**:底色用亮青绿、中间写大字 ——
    如果只画个灰框,你会分不清"换了"和"没换"。
    """
    from PIL import Image, ImageDraw

    image = Image.new("RGB", TEST_IMAGE_SIZE, (0, 170, 160))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, TEST_IMAGE_SIZE[0] - 1, TEST_IMAGE_SIZE[1] - 1],
                   outline=(255, 255, 255), width=8)
    draw.text((40, 300), "HAPPY", fill=(255, 255, 255))
    draw.text((40, 360), "(test image)", fill=(255, 255, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(path))


class FakeProvider(AIProvider):
    """假后端:不联网,固定回一句带情绪标记的话。

    必须是真的 AIProvider 子类(而不是 NullAIProvider)—— 否则
    `chat.is_online` 会是 False,聊天页根本不会走发请求那条路。
    """

    name = "fake-for-observation"

    def __init__(self):
        self.seen_persona = ""
        self.seen_history = []
        self.seen_message = ""

    def chat(self, persona, history, user_message):
        self.seen_persona = persona
        self.seen_history = list(history)
        self.seen_message = user_message
        return REPLY

    def judge_batch(self, items, persona="", history=None):
        return [JudgeResult(Grade.CORRECT, 1.0, SOURCE_AI, "")
                for _ in items]

    def diagnose(self, summary, persona="", history=None):
        return "[happy] 这一轮不错。"


def main() -> int:
    from core import paths
    from ui.app import App, register_builtin_views

    register_builtins()
    register_builtin_views()

    target = paths.image_dir() / "ai" / "default" / ("%s.png" % EMOTION_UNDER_TEST)
    existed_before = target.exists()

    print("=" * 66)
    print("观察目标:%s" % EMOTION_UNDER_TEST)
    print("立绘图位置:%s" % target)
    print("原本存在吗:%s" % ("是(不会覆盖,脚本会跳过造图)" if existed_before else "否"))
    print("=" * 66)

    if not existed_before:
        make_test_image(target)
        print("已临时造出一张测试图(青绿色底 + 大字 HAPPY)。")
    else:
        print("你已经有这张图,直接用它观察。脚本结束时**不会**删掉它。")

    app = App()
    app.deiconify()
    app.update()

    # 把后端换成假的,并且**在界面上打开聊天页** —— 走的是真实路径:
    # 用户点 AI 形象 -> 聊天页 -> on_send -> chat.ask -> _deliver -> say()
    provider = FakeProvider()
    app.ai_provider = provider
    app.chat.provider = provider

    app.show("menu")
    app.update()
    # 直接进聊天页(等价于用户点了画面上的老师)
    app.push_view("chat", source="menu")
    app.update()
    view = app.current_view

    print()
    print("-" * 66)
    print("窗口应该已经打开了。看那位老师的立绘:")
    print("  * 如果变成了青绿色底、写着 HAPPY 的图 -> [情绪] 替换**成功**")
    print("  * 如果还是原来那张                     -> 替换没生效")
    print("-" * 66)
    print()
    print("正在模拟发送:%r" % REPLY)
    print("(不需要你输入 —— 直接看画面)")

    # 直接调 _deliver,跳过输入框和 60ms 延时,但**后面那段显示逻辑
    # 是真的**:解析情绪 -> 取图 -> 画到场景上。
    view._deliver("你换张脸给我看看")

    # 让渲染跑完(Tk 要一次 update 才会把新图画出)
    app.update()
    app.update_idletasks()

    # ---- 核对事实,而不是只看画面 ----
    from core.reply_format import parse_reply
    emotion, text = parse_reply(REPLY)
    from ui import imagery
    resolved = imagery.character_image(app.current_character, emotion)
    expected = app.current_character.image_path(EMOTION_UNDER_TEST)

    print()
    print("=" * 66)
    print("结果核对")
    print("=" * 66)
    print("  模型原话          : %r" % REPLY)
    print("  解析出的情绪      : %s" % emotion)
    print("  显示的文字        : %s" % text)
    print("  实际取到的图片    : %s" % resolved)
    print("  期望的图片        : %s" % expected)
    ok = (resolved == expected)
    print("  结论              : %s" % ("图片替换成功 ✅" if ok else
                                       "退回了 normal(缺图时就会这样)❌"))
    if not ok:
        print()
        print("  为什么会退回:ui/imagery.py 里,找不到某个情绪的图就退到 normal。")
        print("  这是**有意的**(大多数字用户只画一张正面立绘),不是 bug。")
    print()
    print("关掉窗口继续(或按 Ctrl+C)。")

    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass

    if not existed_before and target.exists():
        try:
            os.remove(str(target))
            print("已删掉那张临时测试图。")
        except OSError as exc:
            print("临时测试图删不掉(%s),它在:%s" % (exc, target))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
