# -*- coding: utf-8 -*-
"""一场学习/考试的"成绩单"。

就是三个计数(记住 / 模糊 / 没见过)。单独一个文件,是因为**它有两个主人**:
学习页一边评一边累加,收尾流程(ui/study_flow.py)读它来落词包和写总结。
放在界面的某个模块里,收尾那边就得反向 import 界面,或者各自维护一份口径。

这里只认 core.models.Grade,不认识任何界面 —— 所以能脱离图形环境测。
"""

from typing import Dict, Iterable

from .models import Grade

# 成绩单里的三个键。顺序就是"从好到差",界面按这个顺序摆按钮。
TALLY_KEYS = (Grade.CORRECT.value, Grade.FUZZY.value, Grade.WRONG.value)


def empty() -> Dict[str, int]:
    """一张空成绩单。"""
    return {key: 0 for key in TALLY_KEYS}


def add(tally: Dict[str, int], grade: Grade, count: int) -> None:
    """把 count 个词按 grade 记进去。

    单独的 add 而不是让调用方自己写 `tally[...] += n`,是为了让
    "一场学习记了些什么"只有一处定义。不认识的分档会被忽略而不是新建一个
    键 —— 成绩单的键是固定的三个,多出来一个只会在总结那里显示成怪东西。
    """
    if grade.value in tally:
        tally[grade.value] += int(count)


def total(tally: Dict[str, int]) -> int:
    """一共评价了多少个词。收尾时的"一个都没评"判断用的就是它。"""
    return sum(int(tally.get(key, 0)) for key in TALLY_KEYS)


def of_grades(grades: Iterable[Grade]) -> Dict[str, int]:
    """按分档列表直接统计一份成绩单。给测试和脚本用。"""
    result = empty()
    for grade in grades:
        add(result, grade, 1)
    return result
