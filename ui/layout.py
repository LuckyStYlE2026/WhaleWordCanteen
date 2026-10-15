# -*- coding: utf-8 -*-
"""场景布局:对话框在哪、立绘摆多大、摆在哪。**纯算术,不认识 Tkinter 也不认识 Pillow。**

单独成模块有两个实在的理由:

1. **界面层要复用同一套坐标。** 对话框的位置既要用来画图(ui/scene.py),
   又要用来摆输入框和按钮(ui/views/study.py、exam.py)。两边各算一遍
   是不可靠的 —— 改了比例之后一定有一个人忘了同步,然后控件飘到框外面。
2. **布局要能脱离图形环境测。** 立绘"有没有被对话框挡住"是一个可以
   用几个数字回答的问题,不该需要先起一个窗口才能验证。

比例的取值见文件末尾那组常量,它们的来历在 v1.5 的说明里:
v1.4 及以前立绘贴着屏幕底边站,对话框盖住了它 41% 的高度 ——
脸都在框里,所以用户报"老师被对话框挡住了"。
"""

from dataclasses import dataclass
from typing import Optional, Tuple

from core.config import PANEL_OPACITY_DEFAULT

# --------------------------------------------------------------------------
# 对话框:一条横贯底部的圆角带
# --------------------------------------------------------------------------

DIALOG_MARGIN_X = 0.05          # 左右留白
DIALOG_MARGIN_BOTTOM = 0.05     # 离底边的距离
DIALOG_HEIGHT = 0.28            # 高度占比
DIALOG_RADIUS = 18              # 圆角半径(像素)
DIALOG_PADDING = 22             # 内边距
NAME_PLATE_HEIGHT = 34          # 名字牌高度

# 内容底板在窗口里的位置,用比例表示。
#
# **它必须同时被两边读到**:场景合成器要把底板画在这个位置上,
# 页面要把真正的 Tk 控件摆在同一个位置上。两边各写一份坐标一定会漂移,
# 表现成"图片里的底和控制器的位置差了一截"。
#
# 这些数是用 place 的 relx/rely/relwidth/relheight 直接喂给 Tk 的。
#
# 主菜单那一块和它左边的内容区一样大 —— 卡的自然是"整块内容底",
# 而不是只垫在标题下面。
#
# 高度给到 0.90 而不是 0.88:底部那个「退出」按钮**曾经被切掉一半**——
# 五张卡片 + 标题 + 进度行 + 退出需要约 640px,而 0.88 只给得出 634px,
# pack 分配空间时最后声明的 footer 就被压到只剩 6px 高。
# 把面板加高比压缩卡片划算:卡片是主内容,而退出按钮点不到是真问题。
MENU_PANEL_BOX = (0.04, 0.04, 0.52, 0.90)

# 学习页的内容区。**高度一直伸到原来对话框的下沿**(对话框占 0.28 高、
# 离底边留 0.05,所以下沿在 0.95 处)。
#
# 那里以前是对话框,这一版对话框整个去掉了 —— 空着的话背景会显得很空旷,
# 而且单词表本来就需要更多纵向空间(一屏最多 5 个词)。
STUDY_PANEL_BOX = (0.04, 0.05, 0.60, 0.90)
EXAM_PANEL_BOX = (0.34, 0.08, 0.34, 0.26)

# 学习页「隐藏老师」之后的内容区:**铺满整个窗口**。
#
# 上下左右都留一点点边,是因为贴死窗口边缘会让卡片看起来"被切掉了";
# 而老师已经不在画面上了,右边不需要再给她留位置。
FULL_PANEL_BOX = (0.02, 0.03, 0.96, 0.94)

# 内容底板的默认透明度。见 core/config.py 的 PANEL_OPACITY_DEFAULT ——
# 同一个数只写一处,渲染层的默认值跟着设置走。
PANEL_OPACITY = PANEL_OPACITY_DEFAULT

# 对话框那几层各自的透明度。它们乘在用户设定的"对话框透明度"之上 ——
# 以前整块是"几乎不透明的一张板",把背景挡掉了大半;现在只有正文
# 保持完全不透明,板、描边、阴影各自让背景透出来。
#
# ⚠️ 这个名字(v1.5 叫 PANEL_OPACITY)和上面那个底板常量**撞过名**,
# 结果渲染器的底板默认值变成了对话框的 0.72。测试在对齐默认值时抓到的
# (tests/test_layout.py 的 SettingsDefaultsAgreeTest)。
DIALOG_PANEL_OPACITY = 0.72     # 对话框的板本身
BORDER_OPACITY = 0.85           # 描边
SHADOW_OPACITY = 0.22           # 投影(以前是 0.35;板变透了阴影不减会显得比板还重)
NAME_PLATE_OPACITY = 0.92       # 名字牌比板更实:它压在框沿上,背后是背景

# --------------------------------------------------------------------------
# 立绘:站在右侧,下半身被对话框遮住一小截(galgame 的常规构图)
# --------------------------------------------------------------------------

# 立绘高度占比。
#
# 这三个数(v1.5 定的)合起来决定构图,改任何一个都要连着看另外两个:
#   高度 0.70 + 底边落在 0.70 处 → 立绘从窗口顶部往下站,
#   底边压在对话框上沿附近,被框盖住的只有最下面两成左右,
#   头、肩、脸全在框外面。
#
# 为什么不再大一点:对话框上沿在 0.67 处,把立绘做到 0.82 高就必须
# 让它往下站,否则头顶顶到屏幕边缘 —— 那样反而被框盖掉三成(和 v1.4
# 的毛病同源,只是轻一些)。"老师别被对话框挡住"比"老师够大"重要。
CHARACTER_HEIGHT = 0.70
CHARACTER_WIDTH = 0.32          # 宽度占比上限
CHARACTER_MARGIN = 0.012        # 离右边界的距离

# 立绘的右下角默认落点。这两个数**必须和 core/config.py 里 UiSettings 的
# 默认值一致** —— 两边不一致时,"直接构造渲染器"和"从设置里读"会给出
# 不同的构图(测试和真实界面就分家了)。
#
# x 取 0.995 是**故意的**:学习页/考试页的按钮行贴着对话框底边居中,
# 最右边的「← 返回」大约伸到窗口的 90% 处;立绘落在 .90 的话,
# 最下面那截会和按钮行叠在一起。贴到右边界就没有这个问题。
#
# y 取 0.67 就是**对话框上沿所在的高度** —— 立绘的底边正好停在框上沿,
# 于是"被挡住多少"只剩几像素的描边误差,而不是一个要靠调参去猜的数。
CHARACTER_ANCHOR_X_DEFAULT = 0.995
CHARACTER_ANCHOR_Y_DEFAULT = 0.67

# 对话页(点老师打开的那一页)里立绘站到**窗口中间**。
#
# 这几个数是界面的常量,不是用户设置:对话页只有"老师居中、对话框在下面"
# 这一种构图,做成可调只是多给人一个调坏的机会。
#
# 横向是**正中**(centre_x),纵向是"底边贴着对话框上沿" ——
# 也就是沿用立绘默认落点那个 0.67。两件事都要,所以用的是 centre_x
# 而不是 centred(后者是横纵都居中,会把下半身压到框里那排按钮上)。
CHAT_CHARACTER_ANCHOR_X = 0.50
CHAT_CHARACTER_ANCHOR_Y = CHARACTER_ANCHOR_Y_DEFAULT

# **不缩小。** 用户明确要求"不要缩小这个形象" —— 老师在这一页是主角,
# 尺寸就按设置里那个倍数(默认 1.0 = 和别处一样大)。
CHAT_CHARACTER_SCALE = 1.0

LINE_SPACING = 6                # 对话框里的行距


@dataclass(frozen=True)
class CharacterLayout:
    """立绘的一次布局结果。

    前四个字段就是"该把立绘缩放成多大、贴到哪个坐标",可以直接交给
    Pillow 或 Tk 用;后两个是给界面层做判断和给测试断言的 ——
    "被对话框遮住了多少"是这次布局的**后果**,不该由调用方各算一遍。
    """

    width: int
    height: int
    left: int
    top: int
    free_height: int        # 对话框上沿以上还剩多少高度(可见区)
    covered: int            # 被对话框盖住的像素数

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


def dialog_rect(size: Tuple[int, int]) -> Tuple[int, int, int, int]:
    """对话框占据的矩形 (左, 上, 右, 下),单位像素。"""
    width, height = max(320, size[0]), max(240, size[1])
    margin_x = int(width * DIALOG_MARGIN_X)
    bottom = height - int(height * DIALOG_MARGIN_BOTTOM)
    top = bottom - int(height * DIALOG_HEIGHT)
    return margin_x, top, width - margin_x, bottom


def box_rect(size: Tuple[int, int],
             box: Tuple[float, float, float, float]) -> Tuple[int, int, int, int]:
    """把一个 (relx, rely, relwidth, relheight) 的比例框换算成像素矩形。

    学习页/考试页的内容区用 place 的 rel* 参数摆控件,场景合成器要
    在**同一个位置**画那块半透明的板。同一个比例喂给这个函数就得到
    一致的像素坐标 —— 两边不必各写一份换算。
    """
    width, height = max(320, size[0]), max(240, size[1])
    relx, rely, relwidth, relheight = box
    left = int(width * relx)
    top = int(height * rely)
    return left, top, left + int(width * relwidth), top + int(height * relheight)


def character_rect(size: Tuple[int, int],
                   aspect: Optional[float] = None,
                   scale: float = 1.0,
                   anchor_x: float = CHARACTER_ANCHOR_X_DEFAULT,
                   anchor_y: float = CHARACTER_ANCHOR_Y_DEFAULT,
                   centred: bool = False,
                   centre_x: bool = False) -> CharacterLayout:
    """算立绘该占多大、贴在哪。

    三条规矩:

    * **按高度定大小,宽度跟着图片自己的长宽比走。** 以前是"塞进一个
      40%×80% 的框里居中",立绘一窄,框里就留两条透明边 —— 视觉上人和
      对话框一起往中间缩。现在只约束高度和宽度上限,长宽比由素材决定。
    * **位置默认给的是右下角落点,不是左上角。** 用户(和这里)想的是
      "立绘站在窗口的哪个位置",而"右下角"是立绘和对话框之间唯一
      有意义的参照点:让落点停在对话框上沿,脸就不会被挡住。
    * **越界夹回窗口内。** 窗口很窄很高时按比例算出的落点可能跑到画布
      外面,那会得到一张"人不见了"的图,而且不报错。

    两种"居中"的区别很简单:

    * ``centred=True`` —— 落点就是**正中**(横纵都是)。适合"人和框不
      重叠"的构图。
    * ``centre_x=True`` —— **只横向居中**,纵向仍按"底边落在 anchor_y"。
      对话页要的就是这个:老师站在正中间,同时底边停在对话框上沿、
      不伸进框里那排按钮。这两种模式都不能让调用方自己去调 anchor_x 抵消
      —— 留白是按窗口宽度算的,要抵消得反解一个跟窗口尺寸有关的数,
      读代码的人看到 0.512 根本猜不出那是什么意思。
    """
    width, height = max(320, size[0]), max(240, size[1])
    if aspect is None or aspect <= 0:
        aspect = CHARACTER_WIDTH / float(CHARACTER_HEIGHT)

    # 高度是主约束,但宽度不能超过占比上限(否则一张超宽的图会横着铺满)
    box_height = height * CHARACTER_HEIGHT * max(0.1, scale)
    box_width = min(box_height * aspect, width * CHARACTER_WIDTH)
    box_height = box_width / aspect

    box = (max(1, int(box_width)), max(1, int(box_height)))

    # margin 是"贴边留白":横向按窗口宽度取,纵向按**同一个像素数**取。
    # 纵向不要跟着高度比例走 —— 那样在宽窗口上会算出几十像素的落差,
    # 立绘被整个推下去,正好抵掉"往右上挪"的效果(v1.5 第一版就写错过)。
    margin = width * CHARACTER_MARGIN
    if centred:
        left = int(width * anchor_x - box[0] / 2.0)
        top = int(height * anchor_y - box[1] / 2.0)
    elif centre_x:
        left = int(width * anchor_x - box[0] / 2.0)
        top = int(height * anchor_y - box[1] + margin)
    else:
        left = int(width * anchor_x - box[0] + margin)
        top = int(height * anchor_y - box[1] + margin)

    left = max(0, min(left, width - box[0]))
    if height - box[1] < 0:
        top = 0
    else:
        top = max(0, min(top, height - box[1]))

    _left, dialog_top, _right, _bottom = dialog_rect((width, height))
    visible_bottom = min(top + box[1], height)
    return CharacterLayout(
        width=box[0], height=box[1], left=left, top=top,
        free_height=max(0, dialog_top - top),
        covered=max(0, visible_bottom - dialog_top),
    )
