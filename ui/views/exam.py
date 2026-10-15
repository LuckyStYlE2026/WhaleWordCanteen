# -*- coding: utf-8 -*-
"""考试模式:一次一个词,不给释义,用户打字回答。

界面和学习模式共用同一套场景合成,区别只有两处:词卡不显示释义,
对话框里多了一个真正用来答题的输入框。

**输入框必须是真正的 tk.Entry。** 这是选 Tkinter 做界面的主要原因 ——
答案是中文,而中文要用输入法。画在图片上的字是没法用输入法输入的,
把输入框做成图片再自己处理按键,等于把输入法整个丢掉。

判分走 core.judge.JudgeService:默认纯离线比字面,落在歧义带且
用户允许时才会升级到 API。升级与否由 core 决定,界面不管 ——
界面里出现"要不要调 API"的判断就说明规则漏上来了。
"""

import tkinter as tk
from typing import Optional

from core.interfaces import EMOTION_NORMAL
from core.lines import is_question
from core.quiz import ExamSession

from ..dialogs import info
from ..layout import EXAM_PANEL_BOX
from ..exam_log import ExamLog
from ..scene import Dialogue
from .. import exam_flow
from ..session import SessionPlan
from ..widgets import (ghost_button, panel_palette, primary_button, theme_color)
from .base import View


class ExamView(View):
    """考试模式。"""

    use_scene = True
    panel_box = EXAM_PANEL_BOX

    def build(self) -> None:
        self.plan = SessionPlan()
        self.session: Optional[ExamSession] = None
        self.awaiting_next = False       # 刚判完分,等用户按"下一题"
        self.log_button: Optional[tk.Button] = None

        self.panel = self.overlay(relx=EXAM_PANEL_BOX[0], rely=EXAM_PANEL_BOX[1],
                                  relwidth=EXAM_PANEL_BOX[2],
                                  relheight=EXAM_PANEL_BOX[3])
        self._build_panel()
        # 先建记录面板再建答题区:答题区里那个开合按钮要能立刻按当前
        # 开合状态把自己的文字设对(见 _sync_log_button)。
        self.log = ExamLog(self, self.theme)
        self._build_controls()

        self.bind("<Configure>", lambda _e: self._place_controls())

    def on_toggle_log(self) -> None:
        """开合左边的「刚才发生了什么」面板。"""
        self.log.toggle()
        self._sync_log_button()

    def _sync_log_button(self) -> None:
        """让按钮文字跟上开合状态。"""
        if self.log_button is not None:
            self.log_button.configure(text=self.log.button_text())

    def _record(self, line: str, answer: str = "") -> None:
        """往历史面板里记一笔。

        **面板关着的时候也照记** —— 那是"默认隐藏"能成立的前提:拉出来
        就该看到完整历史,而不是只有打开之后的那几行。
        """
        if answer:
            self.log.append("", answer)
        self.log.append(self.app.current_character.name, line)

    # ---- 骨架 ------------------------------------------------------------

    def _build_panel(self) -> None:
        # 和学习页同一个约定:单词坐在画进场景图的那层"底"上,
        # 这些控件用算出来的同一套底色与字色。
        palette = panel_palette(self.app)
        surface = palette["surface"]
        self.panel.configure(bg=surface)

        self.progress_label = tk.Label(
            self.panel, text="", bg=surface, fg=palette["dim"],
            font=("Microsoft YaHei UI", 10), anchor="center")
        self.progress_label.pack(fill="x")

        self.word_label = tk.Label(
            self.panel, text="", bg=surface, fg=palette["text"],
            font=("Microsoft YaHei UI", 34, "bold"), anchor="center")
        self.word_label.pack(fill="both", expand=True)

        self.phonetic_label = tk.Label(
            self.panel, text="", bg=surface, fg=palette["dim"],
            font=("Microsoft YaHei UI", 12), anchor="center")
        self.phonetic_label.pack(fill="x", pady=(0, 10))

    def _build_controls(self) -> None:
        """对话框里的答题区:输入框 + 提交按钮。"""
        self.controls = tk.Frame(self, bg=theme_color(self.theme, "background"))

        self.answer_var = tk.StringVar()
        self.entry = tk.Entry(
            self.controls, textvariable=self.answer_var, width=30,
            bg=theme_color(self.theme, "background"),
            fg=theme_color(self.theme, "text"),
            insertbackground=theme_color(self.theme, "text"),
            relief="flat", bd=0, highlightthickness=1,
            highlightbackground=theme_color(self.theme, "panel_light"),
            highlightcolor=theme_color(self.theme, "accent"),
            font=("Microsoft YaHei UI", 13))
        self.entry.pack(side="left", ipady=6)
        self.entry.bind("<Return>", lambda _e: self.on_submit())

        self.action_button = primary_button(self.controls, "提交",
                                            self.on_submit, self.theme)
        self.action_button.pack(side="left", padx=8)
        # 「刚才发生了什么」:开合左边那块记录面板。
        #
        # ⚠️ **这里原来是「问老师」,已经拿掉了。** 考试时不该引导用户去问
        # 老师 —— 想聊天的人会直接点 AI 形象进对话页,那才是谈天的入口。
        # 去掉按钮**不影响**"把问题打进输入框"这条路:on_submit 里仍有
        # is_question 判断,真的在提问就转给 chat.ask,不消耗答题机会
        # (见 core/lines.is_question)。
        self.log_button = ghost_button(self.controls, "刚才发生了什么",
                                        self.on_toggle_log, self.theme)
        self.log_button.pack(side="left")
        ghost_button(self.controls, "结束", self.on_finish, self.theme).pack(side="left",
                                                                            padx=8)
        # 和学习页同一个约定:返回 = 结束这场(结果照常落盘),回挑词页
        ghost_button(self.controls, "← 返回", self.on_back,
                     self.theme).pack(side="left")
        self._sync_log_button()

    def _place_controls(self) -> None:
        # 对话框还没布局好时 winfo 宽度是 1,摆了会出屏;等重画后再摆。
        if self.scene.winfo_width() <= 1:
            # 记下 id:控件销毁时要把这个还没到期的重试撤掉,
            # 否则 Tk 会打 `invalid command name "..._place_controls"`
            self._pending_place = self.after(120, self._place_controls)
            return
        left, _top, right, bottom = self.scene.dialog_area()
        # 居中放在对话框底边,而不是锚右下:右下会让**输入框**向左溢出 ——
        # 输入框是这一排里最宽的那个,锚右下它会顶到左边的记录面板或出框。
        self.controls.place(x=(left + right) // 2, y=bottom - 16, anchor="s")

    # ---- 生命周期 --------------------------------------------------------

    def on_enter(self, plan: SessionPlan = None, **kwargs) -> None:
        if plan is None or not plan.words:
            self.app.back_to_menu()
            return

        self.plan = plan
        self.session = ExamSession(plan.words, self.app.judge, self.app.scheduler,
                                   self.app.today(), title=plan.title,
                                   order=plan.order)
        self.app.chat.reset()
        self.log.clear()
        # 每场考试都回到"记录面板收起来"的初始状态,免得上一场开着、
        # 这一场一进来就是展开的
        self.log.hide()
        self._sync_log_button()
        self._show_question()

    # ---- 出题 ------------------------------------------------------------

    def _show_question(self) -> None:
        word = self.session.current
        if word is None:
            self._finish_session()
            return

        self.awaiting_next = False
        self.action_button.configure(text="提交")
        self.answer_var.set("")
        self.entry.configure(state="normal")

        self.word_label.configure(text=word.word)
        self.phonetic_label.configure(text=word.phonetic or "")
        self.progress_label.configure(
            text="第 %d / %d 题 · 正确率 %.0f%%"
                 % (self.session.answered_count + 1, self.session.total,
                    self.session.score() * 100))

        self._say(EMOTION_NORMAL, "「%s」是什么意思?用中文说说看。" % word.word)
        self.entry.focus_set()

    def _say(self, emotion: str, line: str) -> None:
        self.scene.set_character(self.app.character_image(emotion))
        self.scene.set_dialogue(Dialogue(speaker=self.app.current_character.name,
                                         text=line,
                                         character=self.app.character_image(emotion),
                                         background=self.app.background_image()))

    # ---- 作答 ------------------------------------------------------------

    def on_submit(self) -> None:
        if self.session is None:
            return
        if self.awaiting_next:
            # 上一题已经判完了,这一次回车是"翻到下一题"
            self._show_question()
            return

        answer = self.answer_var.get().strip()
        if not answer:
            # 空输入不算答错,只是提醒一下 —— 不然用户误按回车就丢一分
            self._say(EMOTION_NORMAL, self.app.speaker.line("empty", EMOTION_NORMAL))
            return

        if is_question(answer):
            # 明显是在提问,不是在答题。转给老师,不消耗一次答题机会。
            # **没有「问老师」按钮了**(用户要求),但这条路要留着 ——
            # 它现在是考试页唯一的提问入口,而且不需要用户先理解按钮的用途:
            # 想问什么直接写出来就是了。
            self.on_ask()
            return

        word = self.session.current
        result = self.session.submit(answer)
        if result is None:
            return

        emotion, line = self.app.speaker.react(word, result, answer)
        self._say(emotion, line)
        self._record(line, answer)

        self.app.save_words()
        self.awaiting_next = True
        self.action_button.configure(text="下一题")
        # 判完之后禁掉输入框,免得用户继续对着上一题打字,以为没生效
        self.entry.configure(state="disabled")
        self.controls.focus_set()

    def on_ask(self) -> None:
        """提问。这是三个受控 API 触发点里的第二个 —— 只在用户明确要求时发生。

        只在**输入框里写了像问题的话**时被调用(见 on_submit 里的
        is_question)。页面上**没有「问老师」按钮了**(用户要求:考试时别
        引导用户找老师),所以这里的提示语不能再让用户"去点那个按钮" ——
        那会指向一个不存在的东西。改成指向**真的入口**:点画面上的老师
        (见 ui/views/base.on_character_click,她随后会进对话页)。
        """
        question = self.answer_var.get().strip()
        if not question:
            self._say(EMOTION_NORMAL,
                      "想问什么?写进下面的框里按回车;或者直接点我,我们聊。")
            return

        reply = self.app.chat.ask(question)
        self._record(reply.text or "……", question)
        if self.app.chat.is_online:
            # 用模型给的情绪(回复开头的 [happy] 之类),没写就是 normal
            self._say(reply.emotion, reply.text or "……我想不出该说什么。")
        else:
            # 没配 API 时说清楚为什么话这么少,而不是让用户以为程序坏了
            self._say(reply.emotion,
                      "%s\n\n(现在是离线模式,只能回答固定的话。"
                      "在「设置」里配置 API 之后,老师就能真的回答你了。)"
                      % (reply.text or "我暂时答不上来。"))

    # ---- 收尾 ------------------------------------------------------------

    def on_finish(self) -> None:
        self._finish_session()

    def on_back(self) -> None:
        """返回 = 结算这场考试,但回挑词包那一页。

        答题的结果照常落盘 —— 已经答过的题不该白答;回到挑词页还能接着
        挑别的包。和学习页的「返回」是同一个约定。
        """
        self._finish_session(dest="exam_pick")

    def on_escape(self) -> bool:
        """Esc 在考试页是"返回上一级",不是退出全屏(分发见 ui/app.py)。"""
        self.on_back()
        return True

    def _finish_session(self, dest: str = "") -> None:
        session = self.session
        if session is None:
            return
        # 先摘掉会话再结算:结算的最后会弹出对话框、切走页面,
        # 期间用户可能再点一次「结束」。不清空的话就会建出第二套包
        self.session = None
        if session.answered_count == 0:
            # 一题没答就退出:没有什么可结算的,也不必弹一个空总结
            self.leave(dest)
            return

        _parts, note = exam_flow.store_results(self.app, self.plan, session)
        info(self, "考试结束", exam_flow.farewell(session, note))
        self.leave(dest)
