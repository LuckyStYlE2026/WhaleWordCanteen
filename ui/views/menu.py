# -*- coding: utf-8 -*-
"""主菜单。五个卡片,对应规格里的五个板块。

这是唯一一页不显示"返回"的界面 —— 它没有上一级可返回。

卡片上的说明文字不是装饰:五个板块的名字(尤其"记忆曲线")
对第一次打开的人并不自解释,一句话说明能省掉一次点错。
"""

import tkinter as tk

from core.stats import summarize
from ..layout import MENU_PANEL_BOX
from ..widgets import Card, ghost_button, panel_palette
from .base import View

# 卡片文案:(显示名, 一句话说明, 目标板块)
# 目标名就是注册表里的板块名 —— 加一页只需要往这个表里加一行。
CARDS = [
    ("开始", "按记忆曲线复习今天该看的词", "start"),
    ("单词设置", "导入、创建、编辑、导出你的词表", "wordset"),
    ("记忆曲线", "看看掌握度和遗忘曲线的走势", "curve"),
    ("AI 选择", "挑一位老师,以及用不用大模型", "ai_select"),
    ("设置", "分辨率、语言、主题与数据位置", "settings"),
]


class MenuView(View):
    """主菜单。

    这一页**只要立绘、不要对话框** —— 它是"站在门口等你选"的一页,
    没有人在说话。所以底部那条对话框不该出现在这里。

    它不自己清对话框,而是把"我只要背景和立绘"记在 `scene_dialogue` 上
    (见 ui/views/base.py):立绘和对话框是两件独立的事,分清楚之后
    "点老师聊完回来,对话框还在"这类问题就不会再有。
    """

    use_scene = True
    panel_box = MENU_PANEL_BOX
    scene_dialogue = False

    def build(self) -> None:
        # 立绘站在右侧,所以内容只占左边一半多一点;右边留给"人"
        content = self.overlay(relx=MENU_PANEL_BOX[0], rely=MENU_PANEL_BOX[1],
                               relwidth=MENU_PANEL_BOX[2],
                               relheight=MENU_PANEL_BOX[3])
        # 整块内容都坐在"底"上:底板是画进场景图的那一层(能换图、能调透明度),
        # 这里的底色和字色是**算出来**的同一套,所以控件看起来就贴在图上。
        # 底板是白的就用深色字,底板被调透了就用浅色字 —— 整块一起决定。
        palette = panel_palette(self.app)
        surface = palette["surface"]
        content.configure(bg=surface)

        title_box = tk.Frame(content, bg=surface)
        title_box.pack(fill="x", pady=(0, 2))
        tk.Label(title_box, text="鲸鱼单词食堂",
                 bg=surface, fg=palette["text"],
                 font=("Microsoft YaHei UI", 26, "bold"), anchor="w").pack(anchor="w")
        tk.Label(title_box, text="今天也和老师一起背几个词吧",
                 bg=surface, fg=palette["dim"],
                 font=("Microsoft YaHei UI", 11), anchor="w").pack(anchor="w")

        self.progress_label = tk.Label(
            content, text="", bg=surface, fg=palette["accent"],
            font=("Microsoft YaHei UI", 11), anchor="w", justify="left")
        # 这几处间距是量出来的:五张卡片 + 标题 + 进度 + 退出按钮必须装进
        # 面板高度里,否则最后声明的 footer 会被 pack 压扁 ——
        # 「退出」曾经只剩 6px 高,用户看到的是半个字点不着(见 _build_footer)。
        self.progress_label.pack(fill="x", pady=(6, 10))

        for title, subtitle, target in CARDS:
            self._add_card(content, title, subtitle, target)

        self._build_footer(content, surface)
        self.refresh()

    def _add_card(self, parent: tk.Misc, title: str, subtitle: str,
                  target: str) -> None:
        card = Card(parent, self.theme, title, subtitle,
                    command=lambda name=target: self.app.show(name))
        card.pack(fill="x", pady=3)

    def _build_footer(self, parent: tk.Misc, surface: str) -> None:
        """页脚:那个「退出」按钮。

        它是这一页**最后一个**被 pack 的东西,所以面板高度不够时它第一个被
        压扁 —— 而且压扁之后文字只露出上半截,看起来像"图片没加载完"。
        所以这里给它一个**不允许被压缩**的最小高度(见下面的 height 参数),
        宁可让别的元素少一点空隙。
        """
        footer = tk.Frame(parent, bg=surface, height=38)
        footer.pack(fill="x", pady=(10, 0))
        footer.pack_propagate(False)

        # 退出做成可点的按钮,而不是印一行"Ctrl+Q 退出"的快捷键提示 ——
        # 提示只有记得住快捷键的人用得上,按钮谁都会点。
        # 走 app.on_close,它负责先存档再关窗,不是直接退出进程。
        #
        # 按钮撑满这一行(而不是只包住两个字):点得到的面积大一点,
        # 而且和上面的卡片同宽,看起来是一条完整的页脚而不是半截。
        button = ghost_button(footer, "退出", self.app.on_close, self.theme)
        button.pack(fill="both", expand=True)
        # 行高**按按钮真正需要的高度算**,不是写一个数。
        # 写 38 的时候按钮需要 41(字号 11 + 上下各 6 的 padding + 描边),
        # 于是它又被压掉 3px —— 和当初"只剩 6px"是同一个毛病,只是轻。
        # pack_propagate(False) 之后这一行不再随内容长高,所以必须算准。
        footer.configure(height=button.winfo_reqheight())

    # ---- 数据 ------------------------------------------------------------

    def refresh(self) -> None:
        """把"今天该复习多少词"显示在标题下面。

        放在主菜单而不是只在记忆曲线页,是因为这才是用户每天打开软件
        唯一真正关心的数字 —— 藏起来等于没做。
        """
        today = self.app.today()
        summary = summarize(self.app.words, today)
        if summary.total == 0:
            text = "词库还是空的,先去「单词设置」导入一份词表"
        elif summary.due_today:
            text = "今天有 %d 个词该复习了" % summary.due_today
        else:
            text = "今天的复习任务已经完成,共 %d 个词" % summary.total
        self.progress_label.configure(text=text)
