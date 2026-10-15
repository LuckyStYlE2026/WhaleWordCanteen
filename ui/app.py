# -*- coding: utf-8 -*-
"""应用外壳:根窗口、共享状态、板块切换。

这是整个程序里唯一持有"全局状态"的地方 —— 词库、设置、各项服务
都挂在 App 上,各板块通过 self.app 取用。做成这样而不是让每个板块
自己去读文件,有两个实际好处:数据永远只有一份(不会出现 A 页面改了
B 页面看不到),以及切换板块时不必反复读写磁盘。

板块之间通过 show(name, **kwargs) 跳转。板块自己不知道别的板块叫什么,
由 App 负责查表 —— 所以加一个新板块只需要注册一行。

界面的路由用的是 core 里的注册表(registration.views),而不是
在 App 里写一个 if-else —— 和内置功能注册进注册表的原则一致:
内置板块和插件板块走的是同一条路。
"""

import tkinter as tk
from datetime import date
from typing import Any, Dict, List, Optional

from core import storage
from core.ai_client import NullAIProvider
from core.builtins import AI_OPENAI_COMPATIBLE
from core.characters import CharacterLibrary, load_library, save_library
from core.ai_context import Conversation
from core.chat import ChatService
from core.config import Settings
from core.interfaces import AIProvider, EMOTION_NORMAL, LinePack, Scheduler
from core.judge import JudgeService
from core.lines import LineSelector
from core.models import Word
from core.packs import WordPack
from core.registry import registry
from core import transcript

from . import dialogs, icon, imagery, windowing
from .router import ViewRouter
from .panels import apply_ttk_style
from .theme import Theme, get_theme
from .widgets import theme_color

WINDOW_TITLE = "鲸鱼单词食堂 WhaleWordCanteen"


class App(tk.Tk):
    """根窗口 + 共享状态。"""

    def __init__(self) -> None:
        super().__init__()

        storage.bootstrap()
        self.settings: Settings = storage.load_settings()
        self.theme: Theme = get_theme(self.settings.ui.theme)

        self.words: Dict[str, Word] = storage.load_words()
        self.characters: CharacterLibrary = load_library()
        self._packs: Optional[List[WordPack]] = None

        self.scheduler: Scheduler = registry.get_scheduler()
        self.linepack: LinePack = registry.get_linepack()
        self.speaker = LineSelector(self.linepack)
        self._build_ai_services()

        self._configure_window()
        self._configure_ttk()

        self.container = tk.Frame(self, bg=theme_color(self.theme, "background"))
        self.container.pack(fill="both", expand=True)

        self.router = ViewRouter(self, self.container)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # 建完就把首页显示出来。窗口不该有"先空白一下再长出内容"的阶段 ——
        # 那段时间用户会以为程序卡住了。默认板块取注册表里第一个注册的,
        # 所以内核不必硬编码"启动进哪一页"。
        self.show(registry.views.default_name() or "menu")

    # ---- 当前板块 --------------------------------------------------------
    #
    # 界面层到处在读 app.current_view / app.current_view_name,所以这两个名字
    # 必须留着。真正持有它们的是路由器(见 ui/router.py),这里只是转发 ——
    # 做成属性而不是在切换时同步两份,就不会出现"两份不一致"。

    @property
    def current_view(self):
        return self.router.current

    @property
    def current_view_name(self) -> str:
        return self.router.current_name

    # ---- 窗口 ------------------------------------------------------------

    def _configure_window(self) -> None:
        self.title(WINDOW_TITLE)
        # 图标放在 window 配置这一块,和标题一起 —— 两者都是"这个窗口
        # 在系统里长什么样"。apply_icon **永不抛异常**:图标是装饰,
        # 缺文件或文件坏了都只是回到默认图标,不该拦着程序启动。
        icon.apply_icon(self)
        self.configure(bg=theme_color(self.theme, "background"))
        self.minsize(900, 600)
        width, height = self.settings.ui.width, self.settings.ui.height
        # 居中显示(见 ui/windowing.py);直接摆到 (0,0) 像没加载完
        self.geometry(windowing.screen_geometry(self, (width, height)))
        self.attributes("-fullscreen", bool(self.settings.ui.fullscreen))
        windowing.bind_fullscreen_toggle(self, self.toggle_fullscreen)
        # Esc 不直接绑 _exit_fullscreen,而是先问当前板块(见 _on_escape)。
        # 这个序列只能绑一次 —— 再绑会替换掉这一条,而页面上绑是没用的
        # (页不在焦点控件的 bindtags 链上)。
        self.bind("<Escape>", self._on_escape)
        # 刻意不绑 Ctrl+Q 之类的退出快捷键:退出是"会写盘"的正经动作,
        # 用一个能点的按钮比一个记不住的组合键清楚。主菜单上有「退出」按钮,
        # 全屏时没有标题栏也能从那里正常退出(先存档再关)。
        # 全屏下先按 Esc 退出全屏,标题栏的关闭按钮也就回来了。

    def _configure_ttk(self) -> None:
        """让 ttk 控件(表格、下拉框)也用上主题色。实现见 ui/panels.py。"""
        apply_ttk_style(self, self.theme)

    def toggle_fullscreen(self, _event=None) -> None:
        self.settings.ui.fullscreen = not self.settings.ui.fullscreen
        self.attributes("-fullscreen", self.settings.ui.fullscreen)

    def _on_escape(self, _event=None) -> None:
        """Esc 的分发口:先问当前板块要不要自己处理,没人接才退全屏。

        用 getattr 而不是直接调 self.current_view.on_escape():注册表允许
        插件注册不是 View 子类的板块,那种板块上不会有这个方法,直接调
        会把"按了一下 Esc"变成一次崩溃。
        """
        handler = getattr(self.current_view, "on_escape", None)
        if callable(handler) and handler():
            return
        self._exit_fullscreen()

    def _exit_fullscreen(self, _event=None) -> None:
        if self.settings.ui.fullscreen:
            self.settings.ui.fullscreen = False
            self.attributes("-fullscreen", False)

    # ---- 服务 ------------------------------------------------------------
    def _make_provider(self) -> AIProvider:
        """按设置造一个 AI 后端。没配好就是空后端,程序照常跑。"""
        if not self.settings.ai.is_configured:
            return NullAIProvider()
        try:
            return registry.get_ai_provider(AI_OPENAI_COMPATIBLE)
        except Exception as exc:              # 构造失败也不该拦住启动
            storage.log_error("构造 AI 后端失败,已退回离线: %s" % exc)
            return NullAIProvider()

    def _fallback_line(self, topic: str, emotion: str) -> str:
        """给对话服务的兜底台词来源。"""
        return self.speaker.line(topic, emotion)

    def _build_ai_services(self) -> None:
        """建 (或重建) 三个 AI 服务。

        ⚠️ **三件事共用同一个 Conversation**(用户 2026-10-17 的要求):
        判分、对话、诊断看到的是同一段人设和同一份历史,所以发给模型的前缀
        完全一致 —— 前缀缓存能一路复用,而用户从头到尾面对同一个人,
        不会出现"判分像个判分机、评语像个教练"的割裂。

        人设通过 persona_provider **现读**,不是在这里拷一份:用户切了人设
        要立刻生效,而不是等下次重启(早先就是拷贝,那个 bug 修掉了)。
        """
        self.ai_provider: AIProvider = self._make_provider()
        self.conversation = Conversation(persona_provider=self._persona_text)
        self.judge = JudgeService(self.settings, self.ai_provider,
                                  storage.load_ai_cache(), self.conversation)
        self.chat = ChatService(self.ai_provider,
                                conversation=self.conversation,
                                fallback=self._fallback_line)

    def _persona_text(self) -> str:
        """现在该用的人设正文。给 Conversation 在发请求前回调。

        每次调用都从 characters 现取,所以切换人设**下一次请求就生效**。
        """
        return self.current_persona.prompt

    def rebuild_ai(self) -> None:
        """设置改过之后重建 AI 相关的服务。

        刻意做成显式调用而不是自动监听 —— 什么时候该重建是明确的
        (用户点了保存),让它自己猜只会带来"什么时候生效"的困惑。

        ⚠️ 重建会**丢掉当前这段对话历史**(新 Conversation 是空的)。
        这是对的:换了接口或者换了模型,旧对话的语境不一定还成立;
        而且诊断缓存那边也会跟着重建。
        """
        self._build_ai_services()

    @property
    def current_character(self):
        return self.characters.current_character()

    @property
    def current_persona(self):
        return self.characters.current_persona()

    def background_image(self) -> Optional[str]:
        """默认背景图(找文件的事在 ui/imagery.py)。"""
        return imagery.background_image()

    def character_image(self, emotion: str = EMOTION_NORMAL) -> Optional[str]:
        """当前形象某情绪的立绘(找不到就退到 normal)。"""
        return imagery.character_image(self.current_character, emotion)

    # ---- 数据 ------------------------------------------------------------

    def today(self) -> date:
        """今天的日期。

        走一个方法而不是各处直接 date.today(),是为了将来能测 ——
        把系统日期调来调去是验证记忆曲线最烦人的一步。
        """
        return date.today()

    @property
    def packs(self) -> List[WordPack]:
        """全部词包。启动后从盘上读一次,之后内存里这份就是真相来源,
        改动经 save_packs 落盘。不给"重新从盘上读"的入口 —— 那会把
        别处刚改好、还没来得及存的东西整个冲掉(见 wordpack_editor._save)。"""
        if self._packs is None:
            self._packs = storage.list_packs()
        return self._packs

    def save_words(self) -> None:
        storage.save_words(self.words)

    def save_settings(self) -> None:
        storage.save_settings(self.settings)

    def save_packs(self) -> None:
        for pack in self.packs:
            storage.save_pack(pack)

    def save_all(self) -> None:
        """把该落的盘都落下来。

        只存真正会变的东西:词库、设置、词包、AI 缓存、形象库。
        刻意不存"统计""进度"之类的派生数据 —— 那些每次都能重新算出来,
        存下来只会多一份可能过期的副本。
        """
        self.save_words()
        self.save_settings()
        self.save_packs()
        storage.save_ai_cache(self.judge.cache)
        save_library(self.characters)

    def on_close(self) -> None:
        """关窗口:先问一句要不要留对话记录,再存档、关掉。

        ⚠️ **必须在 save_all/destroy 之前问** —— 最后会 destroy(),
        窗口都没了之后弹不出任何东西。所以顺序是"问 → 存档 → 关"。

        这条路径同时服务两个入口:窗口的关闭按钮,和主菜单那个「退出」
        (它调的就是这个 on_close,不是直接退出进程)。
        """
        try:
            self.prompt_save_chat()
            self.save_all()
        finally:
            self.destroy()

    def prompt_save_chat(self) -> None:
        """有对话时问一句"要不要保存",选了就写进 save/chats/。

        为什么要问而不是自动存:这段记录**只有用户知道值不值得留**。
        自动存会在 save/chats 里堆一堆"哦""嗯"的碎片;自动不存则会把
        用户真的想问的那一次弄丢。问一句是唯一不会两头都错的做法。

        没有对话时安静地什么都不做 —— 那种情况下弹一个空框只是打扰。
        """
        turns = self.conversation.turns
        if not turns:
            return
        character = self.current_character.name
        if not dialogs.confirm(self, "保存对话记录",
                               "要把这次和「%s」的对话存下来吗?\n\n"
                               "会存到 save/chats/:一份能直接打开读的文本,"
                               "和一份完整备份。 (%d 条)"
                               % (character, len(turns))):
            return
        try:
            path = transcript.save(turns, character, self.current_persona.name)
        except Exception as exc:             # 存记录失败不该拦住退出
            storage.log_error("保存对话记录失败: %s" % exc)
            dialogs.error(self, "保存失败",
                          "对话记录没能写进 save/chats/。\n\n%s" % exc)
            return
        if path is not None:
            dialogs.info(self, "已保存", "对话记录已存到:\n%s" % path)

    # ---- 路由 ------------------------------------------------------------
    #
    # 具体逻辑在 ui/router.py —— 那里解释了"为什么临时离开一页不能重建它"。
    # 这里只是转发,好让界面层继续写 self.app.show(...) / self.app.push_view(...)。

    def show(self, name: str, **kwargs: Any) -> None:
        """切到某个板块。kwargs 会传给板块的 on_enter()。"""
        self.router.show(name, **kwargs)

    def push_view(self, name: str, **kwargs: Any) -> None:
        """临时切到另一页,把当前页留着以便原样返回(对话页就是这么打开的)。"""
        self.router.push(name, **kwargs)

    def pop_view(self) -> bool:
        """回到 push_view 之前的页面。没有可回的就返回 False。"""
        return self.router.pop()

    def back_to_menu(self) -> None:
        self.show("menu")

    # ---- 设置生效 --------------------------------------------------------

    def apply_geometry(self) -> None:
        """把分辨率与全屏立刻用上。设置页点保存时调。"""
        windowing.apply_window(self, self.settings.ui.width,
                               self.settings.ui.height,
                               self.settings.ui.fullscreen)

    def apply_theme(self, name: str) -> None:
        """换主题。

        做法是"改全局主题 → 重刷根窗口 → 重进当前板块"。
        之所以敢整个重刷,是因为每个板块都是从一个工厂函数现造的
        (见 show()),没有跨页面的状态会因此丢失 ——
        学习进行到一半时换主题才算越界,而那时用户也不会在设置页。
        """
        self.theme = get_theme(name)
        self.settings.ui.theme = self.theme.name
        self.configure(bg=theme_color(self.theme, "background"))
        self.container.configure(bg=theme_color(self.theme, "background"))
        self._configure_ttk()
        self.show(self.current_view_name or "menu")


def register_builtin_views() -> None:
    """把内置板块注册进注册表。**重复调用是安全的。**

    内置板块走注册表,和插件板块完全一样 —— 这样"插件能做什么"
    和"内置怎么做的"永远是同一个答案,接缝不会因为没人用而生锈。
    """
    from .views import register_all
    register_all(registry)
