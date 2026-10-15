# -*- coding: utf-8 -*-
"""形象九宫格:左边缩略图,右边名字与说明。

从 lists.py 拆出来的直接原因是那个文件要加"分组标题"之后顶到 300 行,
而这一块和那几个列表本来就不是一回事 —— 它是**带图的**,
要用 load_image 兜底缺图,另外几个是纯文字的。放在一起读的时候
要不停切换心智模型,这正是当初 tables.py 拆出去的同一条理由。
"""

import tkinter as tk
from typing import Callable, List, Optional, Tuple

from .theme import Theme, load_image, to_photo
from .widgets import theme_color


class CharacterGrid(tk.Frame):
    """形象列表。

    缩略图用 load_image,缺图时会渲染成占位框 ——
    所以用户还没放素材时看到的是"这里该放一张什么图"的提示,
    而不是一片空白。
    """

    THUMB = (96, 128)

    def __init__(self, master: tk.Misc, theme: Theme,
                 on_select: Optional[Callable[[str], None]] = None) -> None:
        super().__init__(master, bg=theme_color(theme, "background"))
        from .panels import ScrollFrame

        self.theme = theme
        self.on_select = on_select
        self.scroller = ScrollFrame(self, theme)
        self.scroller.pack(fill="both", expand=True)

    def fill(self, items: List[Tuple[str, str, str, Optional[str]]]) -> None:
        """items 的形式是 [(id, 名字, 说明, 缩略图路径), ...]。"""
        for child in self.scroller.body.winfo_children():
            child.destroy()

        for item_id, name, description, image_path in items:
            self._add_row(item_id, name, description, image_path)

    def _add_row(self, item_id: str, name: str, description: str,
                 image_path: Optional[str]) -> None:
        row = tk.Frame(self.scroller.body, bg=theme_color(self.theme, "panel"),
                       cursor="hand2")
        row.pack(fill="x", pady=3)

        image = load_image(image_path, self.THUMB, self.theme)
        # master=row:图片必须挂在**本控件所在的** Tk 解释器上(见 theme.to_photo)
        photo = to_photo(image, "char:%s" % item_id, master=row)
        thumb = tk.Label(row, image=photo, bg=theme_color(self.theme, "panel"))
        thumb.pack(side="left", padx=8, pady=8)

        text_box = tk.Frame(row, bg=theme_color(self.theme, "panel"))
        text_box.pack(side="left", fill="both", expand=True, padx=6)
        tk.Label(text_box, text=name, bg=theme_color(self.theme, "panel"),
                 fg=theme_color(self.theme, "text"),
                 font=("Microsoft YaHei UI", 12, "bold"), anchor="w").pack(anchor="w")
        tk.Label(text_box, text=description or "(没有说明)",
                 bg=theme_color(self.theme, "panel"),
                 fg=theme_color(self.theme, "text_dim"), anchor="w",
                 justify="left", wraplength=420,
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w")

        if self.on_select is not None:
            # 整行都要能点。逐个控件绑是必须的 —— Tk 的事件不会
            # 从子控件冒泡到父容器,只绑 row 的话点名字是没反应的
            targets = [row, thumb, text_box] + list(text_box.winfo_children())
            for widget in targets:
                widget.bind("<Button-1>", lambda _e, i=item_id: self.on_select(i))
                widget.configure(cursor="hand2")
