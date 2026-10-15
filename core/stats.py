# -*- coding: utf-8 -*-
"""统计:掌握度汇总、记忆曲线数据、学习诊断文案。

界面上的「记忆曲线」板块全部的数据都从这里来。这里只**算数**,
不画图 —— 画图是 ui/curve.py 的事。这样曲线怎么画(Canvas 折线、
颜色、坐标轴)改了不影响算法,算法改了也不用碰界面代码。

关于遗忘曲线的公式,见 forgetting_curve() 的说明。
"""

import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Tuple

from .models import Mastery, Word
from .scheduler import EBBINGHAUS_LADDER, parse_day

# 曲线的横轴天数。30 天正好覆盖完整的艾宾浩斯阶梯(最后一个间隔是 30 天)。
CURVE_DAYS = 30

# 预测保持率的下限。指数曲线尾巴会趋近 0,但画图时贴到 0 会看起来像"完全忘了",
# 而实际上总还是有一点点印象。截到 0.05 让图更好看,也更贴近真实感受。
MIN_RETENTION = 0.05


# --------------------------------------------------------------------------
# 掌握度汇总
# --------------------------------------------------------------------------

@dataclass
class MasterySummary:
    """整个词库的掌握情况。界面上那一排数字就是它。"""

    total: int = 0
    known: int = 0        # 已掌握
    fuzzy: int = 0        # 在学
    new: int = 0          # 没学过
    relearn: int = 0      # 掌握过又忘了,需要重学
    due_today: int = 0    # 今天到期的
    mistakes: int = 0     # 易错词

    @property
    def mastery_rate(self) -> float:
        """掌握率。一个词都没有时返回 0.0,而不是除零。"""
        if self.total <= 0:
            return 0.0
        return self.known / float(self.total)

    @property
    def studied(self) -> int:
        """**至少学过一遍**的词数。

        判据是"不是 new" —— new 的定义是"从没被评过"(见 WordState),
        所以减掉它就是"进过学习循环"的。这个数用来回答用户真正关心的
        那个问题:"我这份词表学到哪了?"
        """
        return max(0, self.total - self.new)

    @property
    def studied_rate(self) -> float:
        """学习进度:学过几个 / 一共几个。0.0 ~ 1.0。

        和 mastery_rate 是两件事,别混:
          * mastery_rate  = 学会了几个(要求 box 到 7 天以上)
          * studied_rate  = 碰过几个(学过一遍就算)
        用户问"这份词表我学到哪了"时想听的是后者 —— 他可能刚学完一遍、
        一个都还没"掌握",但进度显然不是 0。
        """
        if self.total <= 0:
            return 0.0
        return self.studied / float(self.total)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total, "known": self.known, "fuzzy": self.fuzzy,
            "new": self.new, "relearn": self.relearn,
            "due_today": self.due_today, "mistakes": self.mistakes,
            "mastery_rate": round(self.mastery_rate, 4),
            "studied": self.studied,
            "studied_rate": round(self.studied_rate, 4),
        }


def summarize(index: Dict[str, Word], today: date) -> MasterySummary:
    """扫一遍词库,算出汇总。

    每次调用都重新扫 —— 几百到几千个词的规模下这是微秒级的,
    而缓存汇总数就多了一份"和真相不同步"的风险,不值得。
    """
    summary = MasterySummary(total=len(index))
    for word in index.values():
        state = word.state

        if state.mastery == Mastery.KNOWN:
            summary.known += 1
        elif state.mastery == Mastery.RELEARN:
            summary.relearn += 1
        elif state.mastery == Mastery.FUZZY:
            summary.fuzzy += 1
        else:
            summary.new += 1

        # 没学过的词不算"到期"。它们出生时就带着"今天到期"(见
        # scheduler.initial_state),算进来的话刚导入 100 个词的那天
        # 会显示"今天有 100 个等着复习",而它们其实一个都没进过考场。
        # 口径必须和 scheduler.due_words 一致,否则菜单上的数字
        # 会和「今日复习」那一栏对不上。
        scheduled = parse_day(state.next_review)
        if (scheduled is not None and scheduled <= today
                and not state.is_never_studied()):
            summary.due_today += 1

        if state.is_mistake():
            summary.mistakes += 1

    return summary


def summary_for_pack(pack, index: Dict[str, Word],
                     today: date) -> MasterySummary:
    """一个词包的掌握汇总。

    直接复用 summarize,只是把词集换成"这个包里的词" —— 不另起一套
    统计口径。两套口径早晚会在某个字段上对不齐,而"词包已掌握 12 个"
    和"全库已掌握 40 个"必须是同一把尺子量出来的。

    指向已删单词的 id 直接跳过:词包只存 id,单词可能已经被删了
    (见 ui/session.words_from_packs 的同一条取舍)。
    """
    subset = {word_id: index[word_id] for word_id in pack.word_ids
              if word_id in index}
    return summarize(subset, today)


def pack_status_label(pack, today: date, summary=None) -> str:
    """词包的状态标签。一看就知道这个包现在该不该动。

    顺序不能反:`needs_relearn` 优先级最高 —— 一个已经被判定要重学的包,
    哪怕它"下次到期日"看着还在未来,也不能显示成"5 天后到期"。

    ⚠️ **单词表包没有自己的复习排期**(它的词可能分属不同周期),
    所以它的 `recommended_next` 一直是空的,以前于是一律显示「还没学过」——
    哪怕用户已经把这份词表学了好几遍(用户 2026-10-15 报的就是这个:
    "作为单词表的 cet46 和 sample 不应该表示为'还没学过'")。

    现在这种包改按**学习进度**显示:学过几个 / 一共几个。
    判据是"包自己有没有排期",不是"它是什么类型" —— 学习结果包
    (study)有排期,照旧显示到期日。
    """
    if not pack.word_ids:
        return "空包"
    if pack.schedule.needs_relearn:
        return "需要重学"

    scheduled = parse_day(pack.schedule.recommended_next)
    if scheduled is None:
        # 没有排期 ⇒ 这不是一个"到点复习"的包(典型是单词表)
        if summary is not None and summary.total and summary.studied:
            return "已学习 %.0f%%(%d/%d)" % (summary.studied_rate * 100,
                                             summary.studied, summary.total)
        return "还没学过"

    delta = (scheduled - today).days
    if delta < 0:
        return "逾期 %d 天" % (-delta)
    if delta == 0:
        return "今天到期"
    return "%d 天后到期" % delta


# --------------------------------------------------------------------------
# 遗忘曲线
# --------------------------------------------------------------------------

def forgetting_curve(strength_days: float, days: int = CURVE_DAYS) -> List[Tuple[int, float]]:
    """画出艾宾浩斯遗忘曲线,返回 [(第几天, 记得的概率), ...]。

    公式是经典的指数衰减 R(t) = e^(-t/S),其中 S 是"记忆强度"(天)。
    为什么用指数而不是别的?因为它是艾宾浩斯本人从实验数据里拟合出来的形状,
    而规格明确要"艾宾浩斯记忆曲线"。用一个有出处的公式,
    比自创一个连自己都解释不清的曲线要诚实。

    S 取多少见 average_strength()。S 越大曲线越平,表示记忆越牢。
    """
    strength = max(0.5, float(strength_days))
    points: List[Tuple[int, float]] = []
    for day in range(days + 1):
        retention = math.exp(-day / strength)
        points.append((day, max(MIN_RETENTION, retention)))
    return points


def average_strength(index: Dict[str, Word], default: float = 1.0) -> float:
    """用当前的平均复习间隔当记忆强度 S。

    只统计**已经学过的**词(mastery 不是 new)—— 没学过的词 interval 是 0,
    把它们算进去会把曲线压成一条贴近 0 的直线,看不出任何东西。
    """
    intervals = [word.state.interval_days for word in index.values()
                 if word.state.mastery != Mastery.NEW and word.state.interval_days > 0]
    if not intervals:
        return default
    return sum(intervals) / float(len(intervals))


def word_retention(word: Word, today: date) -> float:
    """这个词现在还记得的概率,0.0 ~ 1.0。

    用"上次复习到现在过了几天"代入同一条曲线。没复习过的词返回 0 ——
    它还没进入记忆,谈不上保持率。
    """
    last = parse_day(word.state.last_review)
    if last is None:
        return 0.0
    elapsed = max(0, (today - last).days)
    strength = max(0.5, float(word.state.interval_days or 1))
    return max(MIN_RETENTION, math.exp(-elapsed / strength))


def due_forecast(index: Dict[str, Word], today: date,
                 days: int = CURVE_DAYS) -> List[Tuple[int, int]]:
    """未来每天有多少词到期,返回 [(第几天, 词数), ...]。

    这是曲线页上那排柱状图的来源。它回答的是用户最关心的问题:
    "接下来几天我每天要复习多少?" —— 这张图比任何曲线都实用。
    """
    counts = [0] * (days + 1)
    for word in index.values():
        # 没学过的词不排进预测:它们还没有"复习日",只有"随时可以开始"。
        # 不加这句,新导入的词会全堆在第 0 天的柱子上,把整张图压垮。
        if word.state.is_never_studied():
            continue
        scheduled = parse_day(word.state.next_review)
        if scheduled is None:
            continue
        offset = (scheduled - today).days
        if 0 <= offset <= days:
            counts[offset] += 1
    return list(enumerate(counts))


def ladder_marks(days: int = CURVE_DAYS) -> List[int]:
    """艾宾浩斯阶梯上落在横轴范围内的复习点,用来在曲线上打标记。

    这几个点是"应该在什么时候复习",与用户实际什么时候复习无关 ——
    实际复习时间看 history。
    """
    return [day for day in EBBINGHAUS_LADDER if 0 <= day <= days]


# --------------------------------------------------------------------------
# 文案
# --------------------------------------------------------------------------

def progress_line(summary: MasterySummary) -> str:
    """学习进度的一句话总结。主界面上显示给用户看的那行字。"""
    if summary.total == 0:
        return "词库里还没有单词呢,先去「单词设置」导入一份词表吧~"
    return (
        "您已经学了 %d 个单词了,其中 %d 个已经掌握(%.0f%%),"
        "今天有 %d 个单词等着复习。"
        % (summary.total, summary.known, summary.mastery_rate * 100, summary.due_today)
    )


def diagnosis_text(summary: MasterySummary) -> str:
    """**离线**诊断文案。

    这是 L1 层的产物:零成本、纯规则。更细腻、更有人味儿的评语交给
    L2(大模型),由 AIProvider.diagnose 生成 —— 那要花钱,所以一次学习
    只调一次,而且这段离线文案始终是它的兜底。
    """
    if summary.total == 0:
        return "还没有词可以分析呢,先导入一些单词吧。"
    if summary.due_today > 0:
        return "今天还有 %d 个词没复习,先把到期的清掉再学新的,记得更牢哦。" % summary.due_today
    if summary.mistakes > 0:
        return "有 %d 个词你反复出错,它们是最值得花时间的部分。" % summary.mistakes
    if summary.mastery_rate >= 0.8:
        return "掌握率已经到 %.0f%% 了,这个节奏很好,保持下去。" % (summary.mastery_rate * 100)
    if summary.mastery_rate >= 0.5:
        return "过了一半了,继续按记忆曲线的节奏走,别急着赶进度。"
    return "刚起步总是慢的,每天复习到期的词,剩下的交给时间。"


def build_diagnosis_payload(summary: MasterySummary,
                            pack_title: str = "") -> Dict[str, Any]:
    """打包给 AIProvider.diagnose 的输入。

    刻意只传**汇总数字**,不传单词列表 —— 传 200 个单词的细节会让这个请求
    的输出 token 暴涨,而诊断需要的其实只是这几个人数。
    这是省 Token 的机制之一:让"发给模型的东西"尽可能小。
    """
    payload = summary.to_dict()
    if pack_title:
        payload["pack"] = pack_title
    return payload
