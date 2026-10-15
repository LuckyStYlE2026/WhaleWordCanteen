# -*- coding: utf-8 -*-
"""记忆曲线:遗忘曲线、未来到期柱状图、统计与诊断。

这一页的数据全部是**算出来的**,一个字段都不存 —— 因为存下来就有
"存档里的数字和实际单词对不上"的风险,而重新算一遍只要几毫秒。
这也是为什么关掉程序再打开,统计永远是准的。

右侧留了立绘的位置:规格要求"统计已经学会的单词数量,显示在 AI 形象边上,
配合'您已经学了 {} 单词了……'等烘托情绪的单词"。所以那行字放在立绘旁边,
而不是随便塞在某个角落。
"""

import tkinter as tk
from datetime import date

from core.exam_group import is_reviewable
from core.interfaces import EMOTION_NORMAL
from core.stats import (
    CURVE_DAYS,
    average_strength,
    build_diagnosis_payload,
    diagnosis_text,
    due_forecast,
    forgetting_curve,
    ladder_marks,
    pack_status_label,
    summarize,
    summary_for_pack,
)

from ..charts import DueBarChart, ForgettingCurveChart
from ..tables import PackTable
from ..theme import load_image, to_photo
from ..widgets import ghost_button, theme_color
from .base import View


class CurveView(View):
    """记忆曲线页。"""

    title_text = "记忆曲线"
    subtitle_text = "掌握情况、遗忘走势与未来几天的复习量"

    def build(self) -> None:
        self.diagnosis_text_cache = ""
        self.header(self)

        body = tk.Frame(self, bg=theme_color(self.theme, "background"))
        body.pack(fill="both", expand=True, padx=24, pady=(0, 16))

        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=3)
        body.rowconfigure(1, weight=2)
        body.rowconfigure(2, weight=0)

        self._build_left(body)
        self._build_right(body)
        self._build_bottom(body)
        self._build_packs(body)

        self.refresh()

    # ---- 左:曲线 ---------------------------------------------------------

    def _build_left(self, parent: tk.Misc) -> None:
        panel = self._panel(parent)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 10))

        tk.Label(panel, text="遗忘曲线", bg=theme_color(self.theme, "panel"),
                 fg=theme_color(self.theme, "text"),
                 font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w",
                                                               padx=14, pady=(12, 0))
        tk.Label(panel,
                 text="纵轴是「还记得的概率」,虚线是艾宾浩斯阶梯上该复习的日子。"
                      "每次复习都会把曲线拉回顶端。",
                 bg=theme_color(self.theme, "panel"),
                 fg=theme_color(self.theme, "text_dim"), justify="left",
                 wraplength=520,
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=14)

        self.curve_chart = ForgettingCurveChart(panel, self.theme)
        self.curve_chart.pack(fill="both", expand=True, padx=10, pady=10)

    # ---- 右:统计与诊断 ---------------------------------------------------

    def _build_right(self, parent: tk.Misc) -> None:
        panel = self._panel(parent)
        panel.grid(row=0, column=1, rowspan=2, sticky="nsew", pady=(0, 10))

        self.portrait = tk.Label(panel, bg=theme_color(self.theme, "panel"))
        self.portrait.pack(pady=(14, 6))

        self.progress_label = tk.Label(
            panel, text="", bg=theme_color(self.theme, "panel"),
            fg=theme_color(self.theme, "accent"),
            font=("Microsoft YaHei UI", 12, "bold"), wraplength=340,
            justify="left", anchor="w")
        self.progress_label.pack(fill="x", padx=14)

        self.stat_label = tk.Label(
            panel, text="", bg=theme_color(self.theme, "panel"),
            fg=theme_color(self.theme, "text"),
            font=("Microsoft YaHei UI", 10), wraplength=340,
            justify="left", anchor="w")
        self.stat_label.pack(fill="x", padx=14, pady=(10, 0))

        tk.Label(panel, text="老师的评语", bg=theme_color(self.theme, "panel"),
                 fg=theme_color(self.theme, "text_dim"),
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=14,
                                                      pady=(14, 2))

        self.diagnosis_label = tk.Label(
            panel, text="", bg=theme_color(self.theme, "panel"),
            fg=theme_color(self.theme, "text"),
            font=("Microsoft YaHei UI", 10), wraplength=340,
            justify="left", anchor="w")
        self.diagnosis_label.pack(fill="x", padx=14)

        ghost_button(panel, "让老师详细点评一次", self.on_diagnose,
                     self.theme).pack(anchor="w", padx=14, pady=14)

    # ---- 下:未来到期 -----------------------------------------------------

    def _build_bottom(self, parent: tk.Misc) -> None:
        panel = self._panel(parent)
        panel.grid(row=1, column=0, sticky="nsew", padx=(0, 10))

        tk.Label(panel, text="接下来几天要复习多少", bg=theme_color(self.theme, "panel"),
                 fg=theme_color(self.theme, "text"),
                 font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w",
                                                               padx=14, pady=(12, 0))
        self.forecast_chart = DueBarChart(panel, self.theme)
        self.forecast_chart.pack(fill="both", expand=True, padx=10, pady=10)

    def _build_packs(self, parent: tk.Misc) -> None:
        """词包一览:整页统计都是全库口径的,而用户真正要动手的是某一个包。

        "我 12 个包,哪个该先动?" —— 这一栏就是回答它。
        """
        panel = self._panel(parent)
        panel.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(10, 0))

        tk.Label(panel, text="词包一览", bg=theme_color(self.theme, "panel"),
                 fg=theme_color(self.theme, "text"),
                 font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w",
                                                               padx=14, pady=(12, 0))
        tk.Label(panel, text="每个词包现在是「该复习」「该重学」还是「还不着急」。"
                             "词包的增删改在「单词设置」里。",
                 bg=theme_color(self.theme, "panel"),
                 fg=theme_color(self.theme, "text_dim"),
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=14)

        self.pack_table = PackTable(panel, self.theme, height=6)
        self.pack_table.pack(fill="both", expand=True, padx=10, pady=10)

    def _panel(self, parent: tk.Misc) -> tk.Frame:
        return tk.Frame(parent, bg=theme_color(self.theme, "panel"),
                        highlightthickness=1,
                        highlightbackground=theme_color(self.theme, "panel_light"))

    # ---- 数据 ------------------------------------------------------------

    def refresh(self) -> None:
        today = self.app.today()
        summary = summarize(self.app.words, today)
        strength = average_strength(self.app.words)

        self.curve_chart.set_data(forgetting_curve(strength, CURVE_DAYS),
                                  ladder_marks(CURVE_DAYS), CURVE_DAYS)
        self.forecast_chart.set_data(due_forecast(self.app.words, today, CURVE_DAYS))

        # 规格里点名要的那句话。放在立绘旁边,所以字数要克制 ——
        # 太长会把立绘挤下去
        self.progress_label.configure(
            text="您已经学了 %d 个单词了。" % summary.total if summary.total
            else "还没有开始呢。")
        self.stat_label.configure(text=self._stat_text(summary, strength))
        self.diagnosis_text_cache = diagnosis_text(summary)
        self.diagnosis_label.configure(text=self.diagnosis_text_cache)

        self._fill_pack_table(today)
        self._render_portrait()

    def _fill_pack_table(self, today: date) -> None:
        """词包一览。

        考试结果包也列出来(用户要看"这份词表现在掌握了多少"),但状态栏
        写的是「考试结果」而不是到期日 —— 它**不参与记忆曲线**
        (见 core/exam_group.is_reviewable),按到期日显示会给人一种
        "它也该复习"的错觉,而那个复习是重复的。
        """
        rows = []
        for pack in self.app.packs:
            own = summary_for_pack(pack, self.app.words, today)
            status = (pack_status_label(pack, today, own) if is_reviewable(pack)
                      else "考试结果 · 不单独复习")
            rows.append((pack.id, (pack.title, "%d" % own.total,
                                   "%d" % own.known, "%d" % own.due_today,
                                   status)))
        self.pack_table.fill(rows)

    def _stat_text(self, summary, strength: float) -> str:
        if summary.total == 0:
            return "去「单词设置」导入一份词表,这里就会有内容了。"
        return (
            "已掌握 %d 个(%.0f%%) · 需要巩固 %d 个\n"
            "需要重学 %d 个 · 还没学过 %d 个\n"
            "易错词 %d 个 · 今天到期 %d 个\n"
            "平均记忆强度 %.1f 天"
            % (summary.known, summary.mastery_rate * 100, summary.fuzzy,
               summary.relearn, summary.new, summary.mistakes, summary.due_today,
               strength)
        )

    def _render_portrait(self) -> None:
        """把立绘缩小画在面板里。

        这里用离屏合成(而不是直接把 PNG 贴到 Label 上),理由和场景里一样:
        立绘是带 alpha 的 PNG,直接贴会带出一圈背景色。
        合成到跟面板同色的底上就干净了。
        """
        path = self.app.character_image(EMOTION_NORMAL)
        if path is None:
            return

        size = (180, 220)
        image = load_image(path, size, self.theme)
        canvas = self.theme.flat_image(size)
        canvas.alpha_composite(image)
        self.portrait.configure(
            image=to_photo(canvas, "curve:portrait", master=self.portrait))

    # ---- 诊断 ------------------------------------------------------------

    def on_diagnose(self) -> None:
        """让 AI 点评一次。

        这是三个受控触发点之外的**手动**入口 —— 用户主动点才发生,
        而且结果只显示不落盘。没配 API 时 chat.diagnose 会原样返回
        离线文案,不会报错,也不会让用户觉得按钮坏了。
        """
        today = self.app.today()
        summary = summarize(self.app.words, today)
        payload = build_diagnosis_payload(summary, "")
        text = self.app.chat.diagnose(payload, self.diagnosis_text_cache)
        self.diagnosis_label.configure(text=text)

        if not self.app.chat.is_online:
            self.diagnosis_label.configure(
                text="%s\n\n(现在是离线模式,评语来自本地规则。"
                     "在「设置」里配置 API 之后,老师就能针对你的情况说话了。)"
                     % self.diagnosis_text_cache)
