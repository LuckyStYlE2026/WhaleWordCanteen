# -*- coding: utf-8 -*-
"""PIL 图 → Tk 能显示的图,并替所有调用方**看着它们的寿命**。

**为什么单独一个模块。** Tkinter 有一个特别费时间的坑:

    ImageTk.PhotoImage 建出来的对象,如果只被局部变量引用,函数一返回
    就被垃圾回收 —— 界面上留下一块空白,而且**不报任何错**。

另一个坑就在旁边,而且更凶:

    ImageTk.PhotoImage(image) 不传 master 时,图片会挂到"当前默认根窗口"上。
    如果控件属于**另一个** Tk 解释器(比如调用方自己先建了一个窗口),
    `label.configure(image=...)` 会报 `image "pyimage1" doesn't exist` ——
    这个名字在控件所在的解释器里根本没注册过,而错误信息里一个字都不提
    master。曲线页和 AI 选择页就这么整页打不开过。

所以这个模块只做一件事:把图交出去,同时把引用留住、把 master 传对。
两个坑都封在同一个函数里,调用方想绕过去会很难受,这正是目的。
"""

import tkinter as tk
from typing import Dict, Optional

from PIL import Image, ImageTk

# 强引用缓存。键是 "<用途>:<标识>",用途只是给人看的,唯一性靠标识。
_photo_refs: Dict[str, ImageTk.PhotoImage] = {}


def to_photo(image: Image.Image, key: str,
             master: Optional[tk.Misc] = None) -> ImageTk.PhotoImage:
    """转成 Tk 能显示的 PhotoImage,保持强引用,并挂到正确的解释器上。

    key  缓存键。**必须唯一**,否则后一张会顶掉前一张的强引用。
    master **务必传**:把要用这张图的控件传进来(或它的任意祖先)。
          不传的话就退回"默认根窗口",而那在多解释器场景下是错的 ——
          见模块开头的第二个坑。

    已登记的图不会主动回收(界面在跑就一直在用)。想清理可以调 forget()。
    """
    photo = (ImageTk.PhotoImage(image, master=master) if master is not None
             else ImageTk.PhotoImage(image))
    _photo_refs[key] = photo
    return photo


def forget(key: str) -> None:
    """放掉一张图。控件销毁后调用,免得缓存无限长。"""
    _photo_refs.pop(key, None)


def tracked_keys():
    """当前登记了哪些键。给测试和排查用。"""
    return list(_photo_refs)
