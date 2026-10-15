# -*- coding: utf-8 -*-
"""复习调度:艾宾浩斯固定阶梯。

**为什么用固定阶梯而不是 SM-2?**

规格要的是"记忆曲线",而曲线是要**展示给用户看**的。
圆整的间隔(1、2、4、7、15、30 天)能画出一条干净的曲线,
也能直白地告诉用户"下次复习:10 月 13 日"。
SM-2 的 ease 因子会算出 3.7 天、9.1 天这种数字 ——
既画不出好看的图,也没法跟用户解释为什么。

而 MVP 阶段每个词只复习几轮,SM-2 的自适应根本来不及积累数据就结束学习了,
反而只带来浮点漂移和调试负担。

所以:本版用固定阶梯。但 WordState 里已经预留了 ease 字段,
将来想换成 SM-2 或 FSRS,继承 Scheduler 接口注册进去即可,不用改数据结构。
"""

from datetime import date, timedelta
from typing import Dict, List, Optional

from . import storage
from .interfaces import Scheduler
from .models import Grade, Mastery, Word, WordState
from .packs import (
    PACK_TYPE_STUDY,
    REGULARITY_DELAYED,
    REGULARITY_ON_SCHEDULE,
    REGULARITY_OVERDUE,
    SessionRecord,
    WordPack,
)

# 艾宾浩斯阶梯,单位:天。box 是这张表的下标。
EBBINGHAUS_LADDER = (0, 1, 2, 4, 7, 15, 30)

# 达到这个 box 才算"掌握"。
# 注意不要写成 3 —— 阶梯是 (0,1,2,4,7,15,30),下标 3 对应的是 **4 天**,
# 下标 4 才是 7 天。规格要求"7 天以上才算掌握",所以阈值取 4。
# 一个词隔了 7 天还记得,才算真的记住了。
MASTERY_BOX_THRESHOLD = 4

# 逾期超过这个天数,无论原定间隔多长,一律判定为"需要重学"。
MAX_TOLERATED_SLACK_DAYS = 7


def parse_day(text: Optional[str]) -> Optional[date]:
    """把 ISO 日期字符串转成 date。空字符串和非法值都返回 None。

    单独拎出来是因为存档里到处都是日期字符串,而且手工编辑过的存档
    很容易出现空串或写错的日期,统一在这里兜住。
    """
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def format_day(when: date) -> str:
    return when.isoformat()


def initial_state(today: date) -> WordState:
    """新建单词时的初始状态:立刻到期,这样刚导入就能学。"""
    return WordState(
        mastery=Mastery.NEW,
        box=0,
        interval_days=0,
        next_review=format_day(today),
    )


class EbbinghausScheduler(Scheduler):
    """内置的复习调度器。判分规则见 grade() 里的表格。"""

    def grade(self, state: WordState, result: Grade, today: date) -> WordState:
        """根据本次作答结果推进复习状态,返回新状态。

        三种结果的规则(与 guige.md 的约定一致):

          答对   box 前进一级,间隔跳到新等级的间隔。
                 box >= 3(即间隔 7 天以上)才算"掌握"。
          模糊   box 原地不动 —— 不加分也不重罚,
                 间隔砍半,过几天再来一次。
          答错   box 退一级(最低退到 1,不会永远卡在 0),
                 间隔打回 1 天,明天重来。
                 如果这个词原本已掌握,标记为"需要重学"。
        """
        new_state = state.clone()
        new_state.review_count += 1
        new_state.last_review = format_day(today)

        if result == Grade.CORRECT:
            new_state.box = min(state.box + 1, len(EBBINGHAUS_LADDER) - 1)
            new_state.interval_days = EBBINGHAUS_LADDER[new_state.box]
            new_state.correct_count += 1
            new_state.streak_correct += 1
            new_state.mastery = (
                Mastery.KNOWN if new_state.box >= MASTERY_BOX_THRESHOLD else Mastery.FUZZY
            )

        elif result == Grade.FUZZY:
            new_state.box = state.box
            # 间隔砍半,但至少隔一天 —— 当天重复同一张卡片没有意义
            new_state.interval_days = max(1, EBBINGHAUS_LADDER[state.box] // 2)
            new_state.fuzzy_count += 1
            new_state.streak_correct = 0
            new_state.mastery = Mastery.FUZZY

        else:  # Grade.WRONG
            new_state.box = max(1, state.box - 1)
            new_state.interval_days = 1
            new_state.wrong_count += 1
            new_state.streak_correct = 0
            new_state.lapses += 1
            # 掌握过的词答错了才叫"遗忘";没掌握过的词答错只是"还没学会"
            new_state.mastery = (
                Mastery.RELEARN if state.mastery == Mastery.KNOWN else Mastery.NEW
            )

        new_state.next_review = format_day(today + timedelta(days=new_state.interval_days))
        new_state.append_history(format_day(today), result)
        return new_state

    def due_words(self, index: Dict[str, Word], today: date,
                  limit: int = 0) -> List[Word]:
        """取出今天到期的单词,**跨词包**查询。

        这是规格里明确要求的:复习按单词的到期时间走,不按词包走。
        一个词包里的词可能分属不同的复习周期,不该被强行绑在一起。

        从没学过的词不算"到期" —— 它们还没进复习循环,该做的是先去学。
        这道过滤不能省:新建的词一律带着"今天到期"出生
        (见 initial_state),光看 next_review 的话,刚导入 100 个词,
        「今日复习」就会立刻摆出 100 个待复习 —— 而其实一个都还没学过。
        判据见 WordState.is_never_studied()。
        """
        due: List[Word] = []
        for word in index.values():
            if word.state.is_never_studied():
                continue
            scheduled = parse_day(word.state.next_review)
            if scheduled is not None and scheduled <= today:
                due.append(word)

        # 逾期最久的排最前 —— 它们遗忘得最厉害,最该先复习
        due.sort(key=lambda word: (word.state.next_review or "", word.id))
        if limit > 0:
            return due[:limit]
        return due

    def evaluate_pack_regularity(self, pack: WordPack, today: date) -> str:
        """判断用户有没有按计划回来学习这个词包。

        规则:
          slack <= 0                     按时          → on_schedule
          slack <= max(2, 半个间隔)       拖了一点      → delayed
          否则                            严重逾期      → overdue(触发重学)
          硬规则:slack > 7 天一律 overdue,不管原间隔多长。

        为什么要有"硬规则"那一条?因为间隔 30 天的词包如果逾期 20 天,
        按比例算仍然"在容忍范围内",但 20 天足够忘光了。
        所以给一个绝对上限兜底。
        """
        expected = parse_day(pack.schedule.recommended_next)
        if expected is None:
            return REGULARITY_ON_SCHEDULE

        slack = (today - expected).days
        if slack <= 0:
            return REGULARITY_ON_SCHEDULE

        if slack > MAX_TOLERATED_SLACK_DAYS:
            return REGULARITY_OVERDUE

        last_studied = parse_day(pack.schedule.last_studied)
        if last_studied is None:
            # 没有上次学习日期就没法算原定间隔,只能用绝对上限判断
            return REGULARITY_DELAYED

        planned_interval = max(1, (expected - last_studied).days)
        if slack <= max(2, planned_interval // 2):
            return REGULARITY_DELAYED
        return REGULARITY_OVERDUE

    def relearn_pack(self, pack: WordPack, index: Dict[str, Word],
                     today: date) -> List[str]:
        """把词包里的词全部打回重学,返回受影响的 id 列表。

        用于"逾期太久,需要重新学一遍"的场景。注意是**打回**,不是删除 ——
        累计的正确/错误次数保留,这样错题本还记得这个词一直很难。
        """
        affected: List[str] = []
        for word_id in pack.word_ids:
            word = index.get(word_id)
            if word is None:
                continue
            new_state = word.state.clone()
            new_state.box = 1
            new_state.interval_days = 1
            new_state.next_review = format_day(today)
            new_state.mastery = Mastery.RELEARN
            new_state.streak_correct = 0
            word.state = new_state
            affected.append(word_id)
        return affected

    def build_study_pack(self, words: List[Word], when: date,
                         source_mode: str = "sequential",
                         source_pack: Optional[str] = None,
                         source_vocab: str = "") -> WordPack:
        """为一次学习生成词包。

        source_vocab 记"这批词是从哪份单词表学来的" —— 考试结果要落到
        那份单词表名下(见 core/exam_group.vocab_of),所以这个关系必须
        显式存下来,不能靠 source_pack 推(跨来源会话那里是空的)。

        词包记录的是"这批词是在哪天、以什么方式录入的"。
        它同时给出建议的下次学习日期 —— 取这批词里最近的一个到期日,
        这样用户下次回来时正好接上。
        """
        pack_id = storage.new_pack_id(PACK_TYPE_STUDY, when)
        scheduled_days = [
            parse_day(word.state.next_review) for word in words
        ]
        # 取这批词里最早的到期日,用户下次回来正好接上;全都还没排期就顺延一天
        soonest = min((day for day in scheduled_days if day is not None), default=None)
        pack = WordPack(
            id=pack_id,
            pack_type=PACK_TYPE_STUDY,
            title="%s 学习词包" % when.strftime("%Y-%m-%d"),
            created_at=format_day(when),
            word_ids=[word.id for word in words],
            source_mode=source_mode,
            source_pack=source_pack,
            source_vocab=source_vocab,
        )
        pack.schedule.recommended_next = format_day(
            soonest if soonest is not None else when + timedelta(days=1)
        )
        pack.schedule.last_studied = format_day(when)
        return pack

    def record_session(self, pack: WordPack, when: date, correct: int,
                       fuzzy: int, wrong: int) -> None:
        """把一次学习的成绩记进词包,并更新规律性与建议日期。

        规律性是在**这次**学习开始时算的(用今天和原定日期比),
        记完成绩之后再顺延下次建议日期 —— 顺序不能反,否则会拿新日期跟自己比。
        """
        on_time = pack.schedule.regularity != REGULARITY_OVERDUE
        pack.schedule.sessions.append(
            SessionRecord(day=format_day(when), on_time=on_time,
                          correct=correct, fuzzy=fuzzy, wrong=wrong)
        )
        pack.schedule.last_studied = format_day(when)
        pack.schedule.recommended_next = format_day(when + timedelta(days=1))
