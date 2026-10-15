# -*- coding: utf-8 -*-
"""随机考试的"随机加入全考试词包"。

用户 2026-10-14 的要求:

    在用户选择"随机词考试"时,增加一个子选项"随机加入全考试词包"
    (在用户选择的词包内,按照比例抽取 sample·考试 总词包中的单词,
     比如在掌握中抽取 3 个,模糊中抽取 4 个,错题中抽取 5 个,
     加入用户现在选择的考试词包)

**为什么单独一个模块。** 它和 core/exam_group.py 是同一个主题的两面,
但方向相反:那边管"考完之后结果怎么落",这边管"考之前往这一场里加什么"。
合成一个文件会超过 300 行的体积约定,而拆开的界线也很自然 ——
这一份只依赖"三个包各自有多少词",不碰任何写入逻辑。

**为什么不向别的档借词。** 某一档不够时只抽它有的那些。借来的词属于
另一档,抽进来会让用户看不懂:"我明明全对了,怎么这次又在考它"。
少抽几个是可接受的,凑数不是。
"""

from typing import Dict, Iterable, List

from .models import Word
from .packs import (
    PACK_KIND_FUZZY,
    PACK_KIND_KNOWN,
    PACK_KIND_WRONG,
    WordPack,
)

# 从三档各抽几个。错题抽得最多、掌握抽得最少 —— 偏重薄弱词,
# 和 core/quiz.sampling_weight(1 + 2*错 + 模糊)是同一个方向。
# 用户确认过就是这个比例。
SEED_WEIGHTS = (
    (PACK_KIND_KNOWN, 3),
    (PACK_KIND_FUZZY, 4),
    (PACK_KIND_WRONG, 5),
)


def seed_plan(packs: Iterable[WordPack], vocab_id: str,
              count: int) -> Dict[str, int]:
    """从三档各抽几个。

    按 3 : 4 : 5 缩放到 `count` 个,并且不超过该档实际有的词数。
    返回 {档位: 个数}。
    """
    from .exam_group import exam_packs_of

    plan = {kind: 0 for kind, _weight in SEED_WEIGHTS}
    if count <= 0:
        return plan
    total_weight = sum(weight for _kind, weight in SEED_WEIGHTS)
    available = {pack.kind: pack.word_count
                 for pack in exam_packs_of(packs, vocab_id)}
    for kind, weight in SEED_WEIGHTS:
        share = int(round(count * weight / float(total_weight)))
        plan[kind] = max(0, min(share, available.get(kind, 0)))
    return plan


def seed_words(packs: Iterable[WordPack], vocab_id: str,
               index: Dict[str, Word], count: int,
               rng=None) -> List[Word]:
    """按 3:4:5 从三档抽一批词,用来"随机加入"当前这场考试。

    返回 Word 列表(词库里已经删掉的 id 会被跳过)。
    `rng` 只为测试可注入,平时传 None。
    """
    import random

    from .exam_group import exam_packs_of

    chooser = rng or random
    plan = seed_plan(packs, vocab_id, count)
    picked: List[Word] = []
    for pack in exam_packs_of(packs, vocab_id):
        want = plan.get(pack.kind, 0)
        if not want:
            continue
        pool = [index[word_id] for word_id in pack.word_ids if word_id in index]
        chooser.shuffle(pool)
        picked.extend(pool[:want])
    return picked


__all__ = ["SEED_WEIGHTS", "seed_plan", "seed_words"]
