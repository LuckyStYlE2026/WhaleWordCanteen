# -*- coding: utf-8 -*-
"""把立绘的**白色背景**抠成透明。

## 为什么不是"把所有白像素变透明"

因为角色身上也有白色 —— 眼白、高光、白袖子、白围裙。一刀切会把它们一起
删掉,人物会变成一身洞。

所以这里用**从四边灌水**(flood fill):只有**和画面边缘连通**的那片白色才算
背景。角色内部的白色区域和外面不连通,所以一点都不会被动到。

这个前提要先验证:如果角色顶到了画面边缘(比如头发被裁在边上),
灌水会从缺口渗进角色内部。脚本每次都会先量四条边的白色比例并报出来,
低于 95% 就警告你。

## 顺带处理白边(halo)

角色的轮廓是**抗锯齿**的:轮廓那一圈像素是"角色色和白混出来的浅色"。
只把纯白变透明的话,会留下一圈浅色描边,在深色背景上很显眼。

处理方式是:背景里那些**和角色相邻**的像素,按它有多浅给出**部分透明** ——
越接近白越透明。这样过渡自然,不会留下硬边。

## 怎么用

    cd game

    # 先看会怎么处理,不写文件
    python tools/make_transparent.py --dry-run

    # 处理成 assets/ai/default/xxx_transparent.png 供你比对
    python tools/make_transparent.py

    # 满意了再覆盖原文件(会自动把原件备份到 assets/ai/default/_backup/)
    python tools/make_transparent.py --in-place

    # 抠得不干净时放宽容差(默认 12,越大抠掉越多)
    python tools/make_transparent.py --in-place --tolerance 30
"""

import argparse
import shutil
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.paths import image_dir                            # noqa: E402

# 放立绘的目录(和 core/characters.AI_IMAGE_SUBDIR 一致)
AI_DIR = ("ai", "default")

# 备份目录名。**以 _ 开头**是为了让它混在立绘文件夹里也一眼看出不是素材。
BACKUP_DIR = "_backup"

# 默认容差。白底一般不纯(实测你的是 254~255),给 12 够用;
# 太大容易啃到角色的浅色部分。
DEFAULT_TOLERANCE = 12


def is_near_white(pixel, tolerance: int) -> bool:
    """这个像素算不算"背景白"。

    判据是**每个通道都够亮**,而不是"接近纯白" —— 白底常常带一点点色偏
    (比如 254,255,255),用阈值比用距离更宽容也更好调。
    """
    threshold = 255 - tolerance
    return (pixel[0] >= threshold and pixel[1] >= threshold
            and pixel[2] >= threshold)


def edge_whiteness(pixels, width: int, height: int, tolerance: int):
    """量四条边上有多少比例是背景白。用来判断"能不能安全灌水"。"""
    def ratio(points):
        hit = sum(1 for x, y in points if is_near_white(pixels[x, y], tolerance))
        return hit / max(1, len(points))

    return {
        "上": ratio([(x, 0) for x in range(width)]),
        "下": ratio([(x, height - 1) for x in range(width)]),
        "左": ratio([(0, y) for y in range(height)]),
        "右": ratio([(width - 1, y) for y in range(height)]),
    }


def flood_background(pixels, width: int, height: int, tolerance: int):
    """从四边灌水,返回"背景像素"的集合。

    用显式的队列而不是递归:1152x2080 的图有两百多万像素,递归会直接
    把 Python 的调用栈撑爆(而且报的是 RecursionError,不像"图太大")。
    """
    background = set()
    queue = deque()

    def push(x, y):
        if 0 <= x < width and 0 <= y < height and (x, y) not in background:
            if is_near_white(pixels[x, y], tolerance):
                background.add((x, y))
                queue.append((x, y))

    for x in range(width):
        push(x, 0)
        push(x, height - 1)
    for y in range(height):
        push(0, y)
        push(width - 1, y)

    while queue:
        x, y = queue.popleft()
        push(x + 1, y)
        push(x - 1, y)
        push(x, y + 1)
        push(x, y - 1)

    return background


def build_alpha(pixels, width: int, height: int, background, tolerance: int):
    """算出每个像素的透明度。

    * 背景内部的像素 -> 完全透明;
    * 背景里**紧挨着角色**的那一圈 -> 按它有多浅给部分透明(消白边);
    * 其余(角色本体) -> 完全不透明。

    为什么要单独处理那一圈:轮廓的抗锯齿像素是"角色色 + 白"混出来的,
    直接留成不透明会在深色背景上显出一圈白描边。
    """
    threshold = 255 - tolerance
    alphas = {}

    for (x, y) in background:
        lightest = max(pixels[x, y][:3])
        touches_character = False
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbour = (x + dx, y + dy)
            if 0 <= neighbour[0] < width and 0 <= neighbour[1] < height:
                if neighbour not in background:
                    touches_character = True
                    break
        if not touches_character:
            alphas[(x, y)] = 0
        else:
            # 越接近纯白越透明;越暗说明越可能是角色的一部分,留一点
            span = max(1, 255 - threshold)
            alphas[(x, y)] = max(0, min(255, int((lightest - threshold)
                                                 * 255 / span)))
    return alphas


def convert(path: Path, tolerance: int, dry_run: bool = False):
    """处理一张图,返回 (结果说明, 输出图 or None)。"""
    from PIL import Image

    image = Image.open(str(path))
    original_mode = image.mode
    rgb = image.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()

    edges = edge_whiteness(pixels, width, height, tolerance)
    worst = min(edges.values())
    warning = ""
    if worst < 0.95:
        low = [name for name, value in edges.items() if value < 0.95]
        warning = ("   ⚠ %s 边的白色只有 %.0f%% —— 角色可能顶到边缘,"
                   "灌水有渗进人物内部的风险"
                   % ("/".join(low), worst * 100))

    if dry_run:
        return ("%dx%d %s -> RGBA,四边白比例 %s%s"
                % (width, height, original_mode,
                   " ".join("%s%.0f%%" % (k, v * 100) for k, v in edges.items()),
                   warning), None)

    background = flood_background(pixels, width, height, tolerance)
    alphas = build_alpha(pixels, width, height, background, tolerance)

    out = rgb.convert("RGBA")
    out_pixels = out.load()
    for (x, y), alpha in alphas.items():
        r, g, b, _old = out_pixels[x, y]
        out_pixels[x, y] = (r, g, b, alpha)

    share = len(background) / float(width * height)
    note = ("%dx%d %s -> RGBA,抠掉 %.1f%% 的像素(四边白 %s)%s"
            % (width, height, original_mode, share * 100,
               " ".join("%s%.0f%%" % (k, v * 100) for k, v in edges.items()),
               warning))
    return note, out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="把立绘的白色背景抠成透明(从四边灌水,不会误删角色身上的白色)")
    parser.add_argument("--tolerance", type=int, default=DEFAULT_TOLERANCE,
                        help="白色容差,默认 %d;抠不干净就调大" % DEFAULT_TOLERANCE)
    parser.add_argument("--in-place", action="store_true",
                        help="覆盖原文件(会先备份到 %s/)" % BACKUP_DIR)
    parser.add_argument("--dry-run", action="store_true",
                        help="只报告会怎么处理,不写任何文件")
    parser.add_argument("--only", default="",
                        help="只处理某个文件,例如 --only happy.png")
    parser.add_argument("--all", action="store_true",
                        help="连已经是 RGBA 的图也重新处理(默认跳过它们)")
    args = parser.parse_args()

    folder = image_dir().joinpath(*AI_DIR)
    if not folder.is_dir():
        print("找不到立绘目录:%s" % folder)
        return 1

    candidates = sorted(p for p in folder.iterdir()
                        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
    if args.only:
        candidates = [p for p in candidates if p.name == args.only]
    if not candidates:
        print("这个目录里没有图片可处理:%s" % folder)
        return 1

    backup = folder / BACKUP_DIR
    changed = 0
    for path in candidates:
        from PIL import Image
        mode = Image.open(str(path)).mode
        if mode in ("RGBA", "LA") and not args.all:
            print("%-16s 已经是 %s,跳过(要重做加 --all)" % (path.name, mode))
            continue

        note, output = convert(path, args.tolerance, dry_run=args.dry_run)
        print("%-16s %s" % (path.name, note))
        if output is None:
            continue

        if args.in_place:
            backup.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(path), str(backup / path.name))
            output.save(str(path))
            print("%-16s -> 已覆盖(原件备份在 %s/)" % ("", BACKUP_DIR))
        else:
            target = path.with_name(path.stem + "_transparent.png")
            output.save(str(target))
            print("%-16s -> 写出 %s(和原图对比后再决定要不要 --in-place)"
                  % ("", target.name))
        changed += 1

    print()
    if args.dry_run:
        print("--dry-run:没有写任何文件。")
    elif changed:
        print("处理了 %d 张。" % changed)
        if not args.in_place:
            print("看对比效果:打开 *_transparent.png,或者进游戏换形象试。")
    else:
        print("没有需要处理的图。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
