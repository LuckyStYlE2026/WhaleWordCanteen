# -*- coding: utf-8 -*-
"""板块的公共基类。

每个板块都是"占满整个窗口的一页"。它们共享三件事:跟着主题走、
（有的）铺一层场景背景、顶部有个返回按钮。把这三件事放在基类里,
是因为五页各写一遍就意味着改一次配色要改五个文件。

生命周期只有两步,刻意分成两个方法而不是塞进 __init__:

  __init__   造控件。此时还不知道这一页是"给谁看的"。
  on_enter   App 调它,把参数喂进来(比如"显示哪个词包")。
            没有参数的页面不需要实现它。

这样分开的好处是:板块构造完就能立刻显示骨架,数据晚一步到也不怕 ——
将来从磁盘读大词库时,这一步的差别就是"点了立刻有反应"和"点了卡一下"。
"""

import tkinter as tk
from typing import Optional

from core.interfaces import EMOTION_NORMAL
from core.lines import TOPIC_CHAT_OPEN

from ..gal_scene import GalScene
from ..scene import Dialogue
from ..widgets import ghost_button, scene_options, theme_color

# 台词包里取不到时用的兜底。写死一份是刻意的:插件换掉整套台词包
# (或者语言包还没翻到这一条)时,点老师至少还能得到一句人话。
DEFAULT_TEASE = "看我干什么,背单词啊。"


class View(tk.Frame):
    """所有板块的基类。子类实现 build()。"""

    # 子类按需覆写。use_scene 打开后会铺一层背景画布 ——
    # 内容压在它上面,所以内容区必须是浅色不透明的,否则会糊成一片。
    use_scene = False
    title_text = ""
    subtitle_text = ""

    # 有内容区的页面覆写它:(relx, rely, relwidth, relheight)。
    # 这一份比例同时决定"场景里那块半透明的板画在哪"和"控件摆在哪",
    # 两边读的是同一个数(见 ui/layout.py 的 box_rect)。
    panel_box = None

    # 这一页的场景要不要画**对话框**。
    #
    # 立绘和对话框是两件独立的事(ui/scene.py 开头就是这么写的),但页面
    # 需要能表态"我只要背景和立绘"。默认 True = 保留对话框;**只有主菜单
    # 设成 False** —— 它是"站在门口等你选"的一页,没有人在说话。
    #
    # 为什么需要这个开关:以前主菜单没表态,于是"点老师聊完 → 返回主菜单"
    # 时,场景里留着对话页最后那句话,主菜单底部就多出一条对话框,
    # 而且再也不会消失 —— 它看起来像 bug(它就是)。
    scene_dialogue = True

    def __init__(self, app) -> None:
        super().__init__(app.container, bg=theme_color(app.theme, "background"))
        self.app = app
        self.theme = app.theme
        self.scene: Optional[GalScene] = None

        if self.use_scene:
            self.scene = GalScene(self, app, self.theme, app.background_image(),
                                  app.character_image(), frame_box=self.panel_box,
                                  options=scene_options(app),
                                  on_character_click=self.on_character_click,
                                  character_anchor=self.character_anchor,
                                  character_scale=self.character_scale,
                                  character_centred=self.character_centred,
                                  character_centre_x=self.character_centre_x)
            if not self.scene_dialogue:
                self.scene.set_dialogue(None)
            self.scene.pack(fill="both", expand=True)

        # 离开这一页时把场景拆掉。Tk 在销毁 Frame 时**不会自动销毁 Canvas 上的
        # 图片项**,而照片缓存(ui/photos.py)又持着强引用 —— 每切一页就留下
        # 一张全屏位图,那是实打实的内存。绑在这里一次性管住所有页面。
        self.bind("<Destroy>", self._on_destroy)

        self.build()

    def _on_destroy(self, event) -> None:
        """只在**自己**被销毁时动手 —— 子控件销毁也会触发同一个事件。"""
        if event.widget is not self:
            return
        self._cancel_pending_callback()
        if self.scene is not None:
            self.scene.destroy()
            self.scene = None

    def _cancel_pending_callback(self) -> None:
        """撤掉还没到期的 `after` 回调。

        页面里有些动作是"等控件布局好再做"的(比如把按钮摆进对话框底边:
        控件还没布局时 winfo 宽度是 1,那时摆会出界),做法是 `after(120, ...)`
        重试一次。切页 / 关窗如果正好落在那 120ms 里,回调醒来时控件已经没了,
        Tk 会往 stderr 打 `invalid command name "..._place_controls"` ——
        看起来像程序出错,而且会把测试输出里真正的失败淹掉。
        """
        pending = getattr(self, "_pending_place", None)
        if pending is None:
            return
        self._pending_place = None
        try:
            self.after_cancel(pending)
        except tk.TclError:
            pass                          # 解释器已经在拆了,撤不掉也无所谓

    # ---- 子类实现 --------------------------------------------------------

    def on_character_click(self) -> None:
        """点画面上那位老师时做什么。

        默认是"老师说一句,然后进对话页",所以放在基类里:

        * **说什么由这里决定,不是由对话页决定** —— 对话页不知道自己是被
          从哪儿打开的,而"背到一半点老师"和"站在主菜单点老师"该说的话
          不一样。
        * 台词走本地台词库(**零成本**),取不到就退回一句写死的兜底,
          绝不会因为台词表缺一条就什么都不显示。

        对话页自己把这一项覆写成 None —— 那一页点她不该再开一页。
        """
        self._tease_before_chat()
        # push_view 而不是 show:把当前页**藏起来**再进对话页,
        # 返回时原样摆回去 —— 学习到第几屏、成绩单全都还在。
        # 用 show 会重建上一页,而重建的学习页没有 plan,只能回主菜单。
        self.app.push_view("chat")

    def _tease_before_chat(self) -> None:
        """在别的页面上点老师时,让她先说一句。

        "看我干什么,背单词啊"—— 台词取自本地台词包(话题 TOPIC_CHAT_OPEN),
        没有则用写死的兜底。它不花一分钱 Token。

        ⚠️ **这一页不要对话框的时候就别说。** 主菜单把 scene_dialogue 设成
        False(它是"站在门口等你选"的一页),要是这里照样往场景上写一句,
        那句话既看不见(没有框),又会**留在场景里** —— 用户返回主菜单时
        底部会多出一条对话框,而且再也不会消失。用户实测报的就是这个。
        """
        if self.scene is None or not self.scene_dialogue:
            return
        line = self.app.speaker.line(TOPIC_CHAT_OPEN, EMOTION_NORMAL) or DEFAULT_TEASE
        character = self.app.character_image()
        # 直接把这一句画到对话框上:切页会发生在这之后,用户能瞥见它。
        self.scene.set_character(character)
        self.scene.set_dialogue(Dialogue(speaker=self.app.current_character.name,
                                         text=line, character=character,
                                         background=self.app.background_image()))
        # 立刻重画一次,否则那句话会被 120ms 的防抖吞掉
        self.scene.redraw()

    # 对话页用这几个把它自己从"点一下开一页"里摘出去,并且让她站到中间
    character_anchor = None
    character_scale = None
    character_centred = None
    character_centre_x = None

    def build(self) -> None:
        """造控件。子类必须实现。"""

    def on_enter(self, **kwargs) -> None:
        """进入本页时被 App 调用。需要参数的页面覆写它。"""

    def on_escape(self) -> bool:
        """按 Esc 时先问这一页要不要自己处理。返回 True = 我处理了,App 别再管。

        为什么要绕这么一圈?因为 Tk 的按键是**顺着焦点控件的 bindtags
        冒泡**的,而那条链上只有「控件 → 控件类 → 顶层窗口 → all」——
        页(Frame)不在链上。所以在页上 bind("<Escape>") 对页里的输入框
        敲的键完全无效,而在顶层窗口上再 bind 一次会把 App 那条**替换**掉,
        从此再也退不出全屏。钩子 + App 分发是唯一不打架的做法。

        默认 False:绝大多数页面按 Esc 就是"退出全屏"(App 的兜底行为)。
        """
        return False

    # ---- 给子类用的工具 --------------------------------------------------

    def overlay(self, **place_options) -> tk.Frame:
        """在场景背景之上铺一块内容区。

        用 place 而不是 pack,是为了让内容只占屏幕的一部分 ——
        主菜单右边要留出立绘的位置,左边放卡片。
        """
        frame = tk.Frame(self, bg=theme_color(self.theme, "background"))
        frame.place(**place_options)
        return frame

    def leave(self, dest: str = "") -> None:
        """收尾之后去哪。dest 为空就是回主菜单。

        「返回上一级」这件事有两处要用(学习/考试页结算完回挑词页、
        挑词页本身回一级页),写两遍迟早会漂移。dest 直接就是注册名。
        """
        if dest:
            self.app.show(dest)
        else:
            self.app.back_to_menu()

    def header(self, parent: tk.Misc, title: str = "", subtitle: str = "",
               back: bool = True, on_back=None) -> tk.Frame:
        """页面顶栏:返回按钮 + 标题 + 一行说明。

        on_back 给"返回不等于回主菜单"的页面用 —— 二级页要回它的一级页,
        而不是一步跳回主菜单。默认 None 就是回主菜单,老页面不受影响。
        """
        bar = tk.Frame(parent, bg=theme_color(self.theme, "background"))
        bar.pack(fill="x", padx=24, pady=(18, 10))

        if back:
            ghost_button(bar, "← 返回", on_back or self.app.back_to_menu,
                         self.theme).pack(side="left")

        text_box = tk.Frame(bar, bg=theme_color(self.theme, "background"))
        text_box.pack(side="left", padx=16)
        tk.Label(text_box, text=title or self.title_text,
                 bg=theme_color(self.theme, "background"),
                 fg=theme_color(self.theme, "text"),
                 font=("Microsoft YaHei UI", 20, "bold"), anchor="w").pack(anchor="w")
        if subtitle or self.subtitle_text:
            tk.Label(text_box, text=subtitle or self.subtitle_text,
                     bg=theme_color(self.theme, "background"),
                     fg=theme_color(self.theme, "text_dim"),
                     font=("Microsoft YaHei UI", 10), anchor="w").pack(anchor="w")
        return bar

    def panel(self, parent: tk.Misc, **pack_options) -> tk.Frame:
        """一块带边框的面板。表单、列表都装在它里面。"""
        frame = tk.Frame(parent, bg=theme_color(self.theme, "panel"),
                         highlightthickness=1,
                         highlightbackground=theme_color(self.theme, "panel_light"))
        if pack_options:
            frame.pack(**pack_options)
        return frame
