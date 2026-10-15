# -*- coding: utf-8 -*-
"""对话页:点右边的老师进来的那一页。

这一页刻意只有两样东西:**老师**和**对话框**。没有标题栏、没有状态条、
没有别的面板 —— 也就是"其它 UI 暂时隐藏"。

几个行为上的决定:

* **老师站到窗口中间**(别处她站右边),而且**不缩小** —— 这一页她是主角。
* **输入框只有连上大模型才可用。** 没配 API 时它是禁用的,并说明为什么 ——
  一个能打字却永远没回应的输入框,比一个灰掉的输入框更让人困惑。
  这条说明放在**对话框里**(当成老师的台词),不放顶部横条,
  免得又多出一块 UI。
* **返回回到进来时的那一页。** 从学习页点老师进来的就回学习页,
  不把你扔回主菜单。

对话框这一层完全复用(ui/scene.py 的 Dialogue),所以"老师说的话永远
清晰、透明度只作用在板上"这些行为在这一页自动成立。
"""

import tkinter as tk

from core.interfaces import EMOTION_NORMAL, EMOTION_THINKING

from ..layout import (CHAT_CHARACTER_ANCHOR_X, CHAT_CHARACTER_ANCHOR_Y,
                      CHAT_CHARACTER_SCALE)
from ..panels import DialogueLog
from ..scene import Dialogue
from ..widgets import ghost_button, panel_palette, primary_button, theme_color
from .base import View

# 老师在这一页的开场白。分三种情况:"接着聊"、"没配 API"、"从别处被点进来"。
OPENING_ONLINE = "想聊点什么?词怎么记、句子怎么用,都可以问我。"
OPENING_OFFLINE = ("现在是离线模式,我只会说台词库里的话。"
                   "在「设置 → 配置 API」里填好密钥,这里就能真的聊起来。")
# 从别的页面点老师进来时先说这一句,再进对话页。
OPENING_TEASED = "看我干什么,背单词啊。"


class ChatView(View):
    """和老师自由对话。"""

    use_scene = True
    title_text = "和老师聊聊"

    # 老师横向站到窗口正中,纵向底边仍贴着对话框上沿;大小不缩。
    # on_character_click = None:已经在对话页里了,点她不该再开一页。
    character_anchor = (CHAT_CHARACTER_ANCHOR_X, CHAT_CHARACTER_ANCHOR_Y)
    character_scale = CHAT_CHARACTER_SCALE
    character_centre_x = True
    on_character_click = None

    def build(self) -> None:
        self.thinking = False
        self.log_visible = False
        self.source_name = ""

        # 对话框的位置是算出来的,输入框要摆进去就得在窗口尺寸变化后重算
        self.bind("<Configure>", lambda _e: self._place_controls())
        self._build_controls()

    # ---- 输入行 ----------------------------------------------------------

    def _build_controls(self) -> None:
        """对话框里那一行:输入框 + 发送 + 对话记录 + 返回。"""
        self.controls = tk.Frame(self, bg=theme_color(self.theme, "background"))

        self.answer_var = tk.StringVar()
        self.entry = tk.Entry(
            self.controls, textvariable=self.answer_var, width=52,
            bg=theme_color(self.theme, "background"),
            fg=theme_color(self.theme, "text"),
            insertbackground=theme_color(self.theme, "text"),
            relief="flat", bd=0, highlightthickness=1,
            highlightbackground=theme_color(self.theme, "panel_light"),
            highlightcolor=theme_color(self.theme, "accent"),
            font=("Microsoft YaHei UI", 13))
        self.entry.pack(side="left", ipady=6)
        self.entry.bind("<Return>", lambda _e: self.on_send())

        self.send_button = primary_button(self.controls, "发送", self.on_send,
                                          self.theme)
        self.send_button.pack(side="left", padx=8)
        self.log_button = ghost_button(self.controls, "对话记录", self.on_toggle_log,
                                       self.theme)
        self.log_button.pack(side="left")
        ghost_button(self.controls, "← 返回", self.on_back,
                     self.theme).pack(side="left", padx=8)

    def _place_controls(self) -> None:
        # 对话框还没布局好时 winfo 宽度是 1,摆了会出屏;等重画后再摆。
        if self.scene.winfo_width() <= 1:
            # 记下 id:控件销毁时要把这个还没到期的重试撤掉,
            # 否则 Tk 会打 `invalid command name "..._place_controls"`
            self._pending_place = self.after(120, self._place_controls)
            return
        left, _top, right, bottom = self.scene.dialog_area()
        self.controls.place(x=(left + right) // 2, y=bottom - 16, anchor="s")

    # ---- 对话记录(默认不建、点了才建) ----------------------------------

    def _build_log(self) -> tk.Frame:
        """建对话记录面板。

        **懒加载**:默认就建的话它会在页面上占一块地方,而这一页要的正是
        "只有老师和对话框"。所以等用户真的点了「对话记录」再建,
        放在对话框上方那条带子里。
        """
        palette = panel_palette(self.app)
        holder = tk.Frame(self, bg=palette["surface"], highlightthickness=1,
                          highlightbackground=palette["card_border"])
        self.log = DialogueLog(holder, self.theme, height=8,
                               surface=palette["surface"],
                               text_color=palette["text"])
        self.log.pack(fill="both", expand=True)
        return holder

    def _append_log(self, speaker: str, message: str) -> None:
        """往记录里记一笔。记录还没建就先不记 —— 用户没在看它。"""
        if self.log_visible:
            self.log.append(speaker, message)

    def on_toggle_log(self) -> None:
        if self.log_visible:
            self.log_holder.place_forget()
            self.log_visible = False
            self.log_button.configure(text="对话记录")
        else:
            if not hasattr(self, "log_holder"):
                self.log_holder = self._build_log()
            self.log_holder.place(relx=0.06, rely=0.05, relwidth=0.88, relheight=0.42)
            self.log_visible = True
            self.log_button.configure(text="收起记录")

    # ---- 生命周期 --------------------------------------------------------

    def on_enter(self, source: str = "", **kwargs) -> None:
        """source = "从哪一页点进来的",只用来决定开场白说哪句。

        (返回不用它 —— 返回走的是 App.pop_view(),那一页还在内存里。
        留着 source 是因为"从学习页进来"和"从主菜单进来"该说的话不同。)
        """
        self.source_name = source
        online = self.app.chat.is_online
        self._set_input_enabled(online)
        if online:
            self.entry.focus_set()

        # 从别处点老师进来 → 先调侃一句;直接从菜单进来说正经开场白。
        # 没配 API 时把"为什么输入框是灰的"说在对话框里,而不是另起一块 UI。
        if source and source != "menu":
            opening = OPENING_TEASED
        else:
            opening = OPENING_ONLINE if online else OPENING_OFFLINE
        self.say(EMOTION_NORMAL, opening)
        # 立刻画出来,不等那 120ms 的防抖 —— 用户点了老师就该马上有反应
        self.scene.redraw()

    def _set_input_enabled(self, enabled: bool) -> None:
        self.entry.configure(state="normal" if enabled else "disabled")
        self.send_button.configure(state="normal" if enabled else "disabled")

    def say(self, emotion: str, line: str) -> None:
        image = self.app.character_image(emotion)
        self.scene.set_character(image)
        self.scene.set_dialogue(Dialogue(speaker=self.app.current_character.name,
                                         text=line, character=image,
                                         background=self.app.background_image()))

    # ---- 交互 ------------------------------------------------------------

    def on_send(self) -> None:
        """把输入框里的话发给老师。

        它和「问老师」是同一类:**用户主动发起**。所以同样受离线判断与
        失败回退保护 —— chat.ask 自己会处理(离线走本地台词,出错也退回
        本地台词),界面永远不崩。
        """
        if self.thinking or not self.app.chat.is_online:
            return
        question = self.answer_var.get().strip()
        if not question:
            self.say(EMOTION_NORMAL, "想问什么?写在下面那一行里。")
            return

        self.answer_var.set("")
        self._append_log("", question)
        self.thinking = True
        self._set_input_enabled(False)
        self.say(EMOTION_THINKING, "让我想想……")
        # 先把"我在想"画出来再发请求,否则界面会卡住不动,像死了一样
        self.after(60, lambda: self._deliver(question))

    def _deliver(self, question: str) -> None:
        reply = self.app.chat.ask(question)
        self.thinking = False
        self._set_input_enabled(self.app.chat.is_online)
        if not reply:
            # 兜底台词也是台词,不能因为它是空的就把这一轮丢掉
            self.say(EMOTION_NORMAL, "……我一时想不出该说什么。")
            return
        # ⚠️ 用 reply.emotion 而不是写死 EMOTION_NORMAL —— 模型可以在回复
        # 开头写 [happy] 之类来选表情(见 core/reply_format.py)。
        # 写死的话那个标记就白写了,立绘永远一个表情。
        self.say(reply.emotion, reply.text)
        self._append_log(self.app.current_character.name, reply.text)
        if self.app.chat.is_online:
            self.entry.focus_set()

    def on_back(self) -> None:
        """回到**进来时那一页,而且是原样**。

        用的是 App.pop_view():进来时那一页是**被藏起来**的,不是被销毁的,
        所以回来时学习进度、页码、成绩单都还在。

        > 早先这里是 `app.show(source)`。那有两个毛病:一是学习页需要 plan
        > 参数,重放不了就只能回主菜单(用户实测就是这个现象);二是就算
        > 参数能重放,学习页的进度也会清零,等于学到一半被踢回第一屏。

        没有可回的(比如直接在菜单点老师进来)就回主菜单。
        对话历史**不清空**:回到这一页是想接着说,不是重开一段;
        清空发生在每次学习/考试开始时(app.chat.reset())。
        """
        if not self.app.pop_view():
            self.app.back_to_menu()

    def on_escape(self) -> bool:
        """Esc 在这一页是"回去",不是退出全屏(分发见 ui/app.py)。"""
        self.on_back()
        return True
