# -*- coding: utf-8 -*-
"""考试挑词页上**跟用户说话**的那部分:文案、二次确认的内容、列表的排序。

从 ui/views/exam_pick.py 拆出来,因为那一页已经超过 300 行的体积约定,
而这几件事和"页面怎么搭"没有关系:

* `volume_prompt`:词量那一问**说了什么**。它是给用户的一句**承诺**
  ("这次会把这份词包里的 100 个词全部考一遍"),所以值得单独放、单独读 ——
  早先就是"说的和做的不一致"(提示说考全部,实际按 20 考)。
* `ORDER_OPTIONS` / `SEED_OPTIONS`:顺序与加题两个选择的内容。
* `cluster_by_vocab`:列表里把同一份单词表的三档排在一起。

文案集中在一处还有个好处:改一次话不用在几百行页面代码里找。
"""

from core.exam_group import KIND_LABELS, is_exam_pack

from .session import ORDER_RANDOM, ORDER_SEQUENTIAL

# 超过这么多词就先问一句(见 ui/views/exam_pick.py 的三道闸)。
#
# 80 这个数不是拍脑袋:设置里默认每场 20 题,而 80 意味着"用户很可能
# 不是想考整包,而是想抽一部分"。真正想全考的人多点一次也不亏。
LARGE_PACK_WORDS = 80

# 顺序那一问的两个选项。顺序在前 —— 它是更常见的那个(按词表过一遍),
# 默认选中它,用户想随机再改。
ORDER_OPTIONS = [
    ("顺序考试:按词包 / 单词表里的原顺序", ORDER_SEQUENTIAL),
    ("随机考试:把这一次要考的词打乱(不改编词包)", ORDER_RANDOM),
]

# 选了随机之后的子选项:要不要从这份词表已有的考试包里再抽一批词混进来。
SEED_NONE = "none"
SEED_ALL = "all"
SEED_OPTIONS = [
    ("不加入:只考我勾选的这些词", SEED_NONE),
    ("随机加入:再从考试词包里按 掌握3 : 模糊4 : 错题5 抽一批", SEED_ALL),
]

# 加题的总量,取"这一场题量的一半"。
#
# 加太多会把用户真正想考的那批稀释掉 —— 而这一场是用户自己勾的,
# 它才该是主体;加题是"顺带把薄弱的词也过一遍"。
SEED_SHARE = 0.5


def volume_prompt(total: int) -> str:
    """词量那一问的正文(一个纯确认,不改题量)。"""
    return ("该词包词量极大(%d 个词),是否确认考试?\n\n"
            "这次会把这份词包里的 %d 个词全部考一遍。" % (total, total))


def cluster_by_vocab(packs):
    """把同一份单词表的考试包聚到一起。

    分组感是靠**相邻**给的,不必真做嵌套(见 core/exam_group.py 开头)。

    组内按 `KIND_LABELS` 的顺序(掌握 → 模糊 → 错题):三档是同一份词表的,
    时间戳区分不出该谁在前,而"越严重的越靠后"才是用户想看的顺序。

    不在这个体系里的包(学习结果包、上一版留下的按日期考试包)排在各组之后,
    保持原顺序 —— 它们本来就没有组可归。
    """
    members = {}
    others = []
    for pack in packs:
        if is_exam_pack(pack):
            members.setdefault(pack.group_id, []).append(pack)
        else:
            others.append(pack)

    clustered = []
    for vocab_id in sorted(members):
        clustered.extend(sorted(
            members[vocab_id],
            key=lambda pack: (list(KIND_LABELS).index(pack.kind)
                              if pack.kind in KIND_LABELS else 99)))
    return clustered + others


__all__ = [
    "LARGE_PACK_WORDS", "ORDER_OPTIONS", "SEED_ALL", "SEED_NONE",
    "SEED_OPTIONS", "SEED_SHARE", "cluster_by_vocab", "volume_prompt",
]
