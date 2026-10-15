# -*- coding: utf-8 -*-
"""学习模式:看单词表,一组一组往下过。

    顶部:  ← 返回                          标记  隐藏老师
    左侧:  一屏单词(组合内的词一起出现,**放得下就滚**)
    底部:            〔上一组〕〔下一组〕〔跳过本组〕〔结束学习〕

自评按钮取消了 —— 用户看释义本来就不需要"自评",那是把判分的工作推给人。
现在**翻页本身就是表态**:下一组 = 这组记住了,上一组 = 回头看一眼,
跳过本组 = 先不看它,标记 = 这组按记住了处理 + 把最后一个词设成书签。

**为什么不留对话框?** 让位给单词表。老师仍然在场景里站着(除非你把她藏起来),
点她照样能进对话页 —— 只是她不再占用这一页的版面。

版面细节(为什么底部按钮行必须**先于**单词表声明、为什么按钮分成两条)
见本文件 _build_panel 的注释,以及 说明.md 的 v1.6 / v1.7 / v1.10 三节。
"""

import tkinter as tk
from typing import List

from core import tally as tally_module
from core.models import Grade, Word
from core.packs import PACK_TYPE_VOCAB

from .. import study_actions as actions
from ..layout import FULL_PANEL_BOX, STUDY_PANEL_BOX
from ..session import SessionPlan, group_pages
from .. import study_title
from ..study_bar import StudyNavBar, StudyToolbar
from ..study_flow import finish
from ..widgets import panel_palette
from ..word_list import WordList
from .base import View

# 「取消标记」也做成同一个按钮:再按一次同一组就是取消 ——
# 和词包编辑页「标记此处」的行为保持一致(那里也是再按一次取消)。


class StudyView(View):
    """学习模式。版面细节见本文件开头。"""

    use_scene = True
    # 这一页**没有对话框**(用户要求:对话框去掉,地方让给单词表)。明确写出来,
    # 而不是靠"恰好还没人给它设对话" —— 收尾流程按这个标志判断要不要说告别语
    # (见 ui/study_flow.finish),所以它必须是真的。
    scene_dialogue = False
    # 内容区的比例。场景合成器会在这里画一块底板,控件摆在同一个 box 里 ——
    # 两边读同一个常量,所以"隐藏老师"时改的也只有这一处。
    panel_box = STUDY_PANEL_BOX

    def build(self) -> None:
        self.plan = SessionPlan()
        self.pages: List[List[Word]] = []
        self.page_index = 0
        self.tally = tally_module.empty()
        self.graded: List[Word] = []      # 这一场真正评过的词(结果包只收这些)
        self.finished = False             # 一场只结算一次,防止重复建词包
        self.teacher_visible = True
        self.progress_to = 0

        self.panel = self.overlay(relx=STUDY_PANEL_BOX[0], rely=STUDY_PANEL_BOX[1],
                                  relwidth=STUDY_PANEL_BOX[2],
                                  relheight=STUDY_PANEL_BOX[3])
        self._build_panel()

    # ---- 界面骨架 --------------------------------------------------------

    def _build_panel(self) -> None:
        # 单词表坐在"底"上:底板是画进场景图的那一层(可以换图、可以调透明度),
        # 下面这些控件用**算出来的同一套底色与字色**,看起来就贴在图上。
        self.palette = panel_palette(self.app)
        surface = self.palette["surface"]
        self.panel.configure(bg=surface)

        # ⚠️ **pack 的顺序就是"谁先拿到空间"的顺序**,这里排得很讲究,别随手改。
        #
        # 一个组合里可能有十几个词(数量由用户导入的词表定),单词表因此是
        # **可滚动的**,而它必须排在按钮行**之后**才拿到"剩下的空间" ——
        # 反过来写的话,单词表先按内容撑满,底部那排按钮就没有位置了:
        # 用户看到的是「下一组」被压到面板底下、点不着(实测报过这个)。
        # 所以:固定的元素(工具栏、标题、底部按钮)先声明,可伸缩的单词表最后。
        self.toolbar = StudyToolbar(
            self.panel, self.theme, on_back=self.on_back, on_mark=self.on_mark,
            on_toggle_teacher=self.on_toggle_teacher)
        self.toolbar.pack(side="top", fill="x", pady=(0, 6))

        title_row = tk.Frame(self.panel, bg=surface)
        title_row.pack(side="top", fill="x")
        self.page_title = tk.Label(
            title_row, text="", bg=surface, fg=self.palette["accent"],
            font=("Microsoft YaHei UI", 12, "bold"), anchor="w")
        self.page_title.pack(side="left")
        self.progress_label = tk.Label(
            title_row, text="", bg=surface, fg=self.palette["dim"],
            font=("Microsoft YaHei UI", 9), anchor="e")
        self.progress_label.pack(side="right")

        # 底部:翻页与收尾居中。**先于单词表声明**,这样它永远拿得到高度
        self.nav = StudyNavBar(
            self.panel, self.theme, on_previous=self.on_previous,
            on_next=self.on_next, on_skip=self.on_skip, on_finish=self.on_finish)
        self.nav.pack(side="bottom", fill="x", pady=(8, 0))

        # 单词表最后声明:它吃掉剩下的全部空间,放不下就自己滚
        self.word_list = WordList(self.panel, self.palette, self.theme)
        self.word_list.pack(side="top", fill="both", expand=True, pady=(4, 0))

    # ---- 生命周期 --------------------------------------------------------

    def on_enter(self, plan: SessionPlan = None, **kwargs) -> None:
        if plan is None or not plan.words:
            self.app.back_to_menu()
            return

        self.plan = plan
        # 一屏几个词由设置决定(默认 5)。**同一个组合也要切片** ——
        # 组合是导入词表时给的,可能是课本的一个单元,也可能被人当成
        # "整本书"打成一组;不做上限的话一屏会塞进上百张卡片。
        self.pages = group_pages(plan.words,
                                 self.app.settings.study.page_size)
        self.page_index = 0
        self.tally = tally_module.empty()
        self.graded = []
        self.finished = False
        self.teacher_visible = True
        # 从计划给的起点接着数,而不是从 0 —— 用户选了"从第 347 个开始",
        # 这一场结束时进度就该落在 347 之后,而不是被打回第一课。
        self.progress_to = plan.start_index

        # 新一场学习清空对话历史 —— 上一场的内容留着只会白花输入 token
        self.app.chat.reset()
        self._show_page()

    # ---- 展示 ------------------------------------------------------------

    def _show_page(self) -> None:
        if self.page_index >= len(self.pages):
            self._finish_session()
            return

        words = self.pages[self.page_index]
        self.word_list.render(words)
        self.page_title.configure(text=self._page_title(words))
        self.progress_label.configure(text=self._progress_text())
        self.toolbar.set_mark_enabled(self.plan.pack is not None)
        self.toolbar.set_teacher_visible(self.teacher_visible)

    def _page_title(self, words: List[Word]) -> str:
        """这一屏的标题(怎么写见 ui/study_title.py)。

        ★ 的位置和词包编辑页里"序号列显示 ★"是同一个约定的延伸:
        用户看到 ★ 就知道"下次从这里接着学"落在哪。
        """
        return study_title.page_title(
            words, self.pages, self.page_index,
            self.app.settings.study.page_size,
            mark_position=actions.mark_position(self.plan, words))

    def _progress_text(self) -> str:
        text = "第 %d / %d 屏 · %s" % (self.page_index + 1, len(self.pages),
                                       self.plan.title or "临时会话")
        if self.tally[Grade.CORRECT.value]:
            text += " · 已记住 %d 个" % self.tally[Grade.CORRECT.value]
        return text

    # 这一页**没有 say()**,因为没有对话框 —— 收尾时的告别语由
    # ui/study_flow.finish 按 scene_dialogue 判断要不要说(见那里的说明)。
    # 这里刻意不留一个"什么都不做"的同名方法:那是为了骗过调用方而存在的
    # 代码,读的人会以为"这一页真的会说点什么"。

    # ---- 翻页与评价 ------------------------------------------------------

    def on_next(self) -> None:
        """下一组 = 这一组我记住了。

        这是这一版的主要动作:用户看完这一组,按它表示"记住了",
        于是按 CORRECT 记分并推进度。之所以敢把"记住了"和"翻页"合成一个,
        是因为这一页展示的是**释义本身** —— 看过了就是看过了,
        再要求用户额外交代一句"我记住了"没有信息量。
        """
        self._grade_current(Grade.CORRECT)
        self.page_index += 1
        self._show_page()

    def _grade_current(self, grade: Grade) -> None:
        """给这一屏的词记分、推进度(四步的顺序和口径在 ui/study_actions)。"""
        actions.grade_page(self.app, self.plan, self, self.pages[self.page_index],
                           grade)

    def on_previous(self) -> None:
        """上一组 = 回去看一眼。**不改任何状态。**

        和「下一组」不对称是故意的:回头看不该被记成"我记住了"。
        """
        if self.page_index == 0:
            return
        self.page_index -= 1
        self._show_page()

    def on_skip(self) -> None:
        """跳过本组。不改任何状态 —— 跳过就是"我还没准备好评价它"。"""
        self.page_index += 1
        self._show_page()

    def on_mark(self) -> None:
        """标记:这一组按"记住了"处理,并把最后一个词设成书签。

        和词包编辑页的「标记此处」是同一个书签(`pack.progress.bookmark`),
        所以两边是联动的:这里按一下,去编辑页能看到 ★;在编辑页标了,
        回到这一页标题上就有 ★。

        再按一次同一组就是取消标记(和编辑页的行为一致)。
        """
        pack = self.plan.pack
        if pack is None or pack.pack_type != PACK_TYPE_VOCAB:
            # 结果包和跨来源会话没有"第几个"这个坐标,标记无从谈起
            return

        words = self.pages[self.page_index]
        position = actions.mark_position(self.plan, words)      # 已经是 1 起的显示值

        if position > 0:
            # 第二次按 = 取消(只摘书签,不撤销已记下的学习状态)
            actions.toggle_bookmark(self.app, self.plan, words)
            self._show_page()
            return

        self._grade_current(Grade.CORRECT)
        # 书签落在这一组**最后一个词**上 —— 也就是"下次从它后面接着学"
        actions.toggle_bookmark(self.app, self.plan, words)
        actions.commit_progress(self.app, self.plan, self.progress_to)
        self._show_page()

    def on_toggle_teacher(self) -> None:
        """隐藏 / 显示老师。

        隐藏时单词表**铺满整个窗口** —— 这条是给"看老师会分心"的人准备的。
        老师藏起来之后仍然可以点(不,她根本不在画面上了),所以按钮文字
        必须变成「显示老师」,否则用户会以为按钮失灵。
        """
        self.teacher_visible = not self.teacher_visible
        self._apply_panel_box()
        if self.teacher_visible:
            self.scene.show_character()
        else:
            self.scene.hide_character()
        self.toolbar.set_teacher_visible(self.teacher_visible)

    def _apply_panel_box(self) -> None:
        """按"老师显不显示"把内容区摆成对应的大小。

        面板位置、场景里那块底板的位置必须**一起**改 —— 它们读的是同一个
        box(见 ui/layout.py 的 box_rect),分头改一定会错位。
        """
        box = STUDY_PANEL_BOX if self.teacher_visible else FULL_PANEL_BOX
        self.panel.place(relx=box[0], rely=box[1], relwidth=box[2], relheight=box[3])
        self.scene.set_frame_box(box)

    def on_finish(self) -> None:
        self._finish_session(early=True)

    def on_back(self) -> None:
        """返回 = 结束这一场,但回挑词包那一页,不一步跳回主菜单。

        它和「结束学习」只有落点不同:两条路都落结果包、都推进度 ——
        "丢弃这一场"已经无从谈起,不落包只会让人觉得白学了。
        """
        self._finish_session(early=True, dest="study_pick")

    def on_escape(self) -> bool:
        """Esc 在学习页是"返回上一级",不是退出全屏(分发见 ui/app.py)。"""
        self.on_back()
        return True

    # ---- 进度 ------------------------------------------------------------

    def _commit_current_page(self) -> bool:
        """收尾前把当前这一屏也记下来(为什么见 ui/study_actions 的同名函数)。"""
        return actions.commit_current_page(self.app, self.plan, self,
                                          self.pages, self.page_index)

    def _finish_session(self, early: bool = False, dest: str = "") -> None:
        """结束这一场。dest 为空 = 回主菜单,传页面名 = 回那一页。

        收尾前先把当前那一屏记下来(见 _commit_current_page),再写进度、
        交给收尾流程落包。graded 一起交过去 —— 结果包只收**真正评过**的词。
        一个词都没评的时候收尾会自己跳过落包,所以这里不必拦人:
        用户按「结束学习」就是想结束(见 ui/study_flow.finish)。
        """
        if self.finished:
            return
        self.finished = True

        self._commit_current_page()
        actions.commit_progress(self.app, self.plan, self.progress_to)
        finish(self, self.plan, self.tally, early=early, dest=dest,
               graded=self.graded)
