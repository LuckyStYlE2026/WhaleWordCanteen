# -*- coding: utf-8 -*-
"""词包内增删单词、删整个词包、把学完的词并进当天的结果包 ——
纯数据操作,不碰磁盘、不碰界面。

抽到 core 有两个理由:

  1. **去重**。这段"摘引用 → 判断是不是孤儿 → 清洗悬空 id"的逻辑有两处
     调用方(词包列表页删整包、包内编辑页删单个词),分头写迟早会各自漂移,
     然后出现"从这里删干净了、从那里删没干净"这种最难查的 bug。
  2. **可测**。它是纯逻辑,放进 core 就能脱离界面单元测试,不必为了验证
     "删一个共用词会不会误删别人的词"去开一个 Tk 窗口。

单词的学习记录只有一份(在全局 index 里),词包只存 id。所以"删一个词"
永远是两步:先从这个包摘 id,再看它是不是还属于别的包 —— 只有彻底没人
要了,才连记录一起删。
"""

from datetime import date
from typing import Dict, List, Optional

from .models import Word
from .packs import PACK_TYPE_STUDY, WordPack


def detach_word(index: Dict[str, Word], packs: List[WordPack],
                pack: WordPack, word_id: str) -> bool:
    """把一个词从 pack 里摘掉,返回它是否连学习记录一起被删了。

    摘完之后如果这个词不再属于任何词包(既不在别的包的 word_ids 里,
    `source_packs` 也空了),就连记录一起删 —— 否则会在全局索引里留下
    看不见的孤儿词,越积越多,而且用户没有任何入口能再删掉它们。

    `source_packs` 和别的包的 `word_ids` 都查一遍:它们理论上应该同步,
    但老存档或哪次异常可能让两者对不上,多查一眼更稳。
    """
    if word_id in pack.word_ids:
        pack.word_ids.remove(word_id)

    word = index.get(word_id)
    if word is None:
        return False
    if pack.id in word.source_packs:
        word.source_packs.remove(pack.id)

    still_used = any(word_id in other.word_ids for other in packs
                     if other.id != pack.id)
    if still_used or word.source_packs:
        return False

    del index[word_id]
    # 顺手把别的包错题缓存里的悬空 id 也清掉,免得它指向一个不存在的词
    for other in packs:
        if word_id in other.mistakes:
            other.mistakes.remove(word_id)
    return True


def detach_all(index: Dict[str, Word], packs: List[WordPack],
               pack: WordPack) -> None:
    """把一个词包里的词逐个摘掉。删整个词包前调它。

    先 list() 复制一份再遍历 —— detach_word 会改 pack.word_ids,
    直接遍历原列表等于边走边拆脚下的路。
    """
    for word_id in list(pack.word_ids):
        detach_word(index, packs, pack, word_id)


def remove_pack(packs: List[WordPack], pack: WordPack) -> None:
    """把 pack 从列表里移除。

    按**身份**而不是相等来找:WordPack 是 dataclass,`==` 比的是全部字段,
    两个内容碰巧一样的包会被误判成同一个 —— 那种 bug 平时看不出来,
    一旦出现就是"删了 A 结果 B 不见了"。用 is 就没这问题。
    """
    for index, existing in enumerate(packs):
        if existing is pack:
            del packs[index]
            return


def remove_pack_and_children(index: Dict[str, Word], packs: List[WordPack],
                             pack: WordPack) -> List[WordPack]:
    """删一个词包,**连同它的子包**(目前只有单词表名下的考试结果包)。

    子包为什么会存在:一份单词表有固定的三个考试结果包(掌握 / 模糊 / 错题),
    见 core/exam_group.py。它们脱离父单词表就没有出处了,名字里的
    「某某考试·」也失去含义,所以跟着一起走。

    顺序要紧:先删子包再删父包 —— 反过来父包会先把这些词的最后一个引用
    摘掉并删记录,子包再摘就找不到词了。两边共用同一个词时
    `detach_word` 有引用计数,不会误删。

    返回被删掉的子包(界面要报一句"连同 3 个考试包一起删了")。
    """
    from .exam_group import drop_for_vocab

    children = drop_for_vocab(packs, pack.id)
    for child in children:
        detach_all(index, packs, child)
    detach_all(index, packs, pack)
    remove_pack(packs, pack)
    return children


def dedupe_word_ids(pack: WordPack) -> int:
    """把词包里重复的 id 去掉(保留第一次出现的位置),返回去掉几个。

    **为什么需要一个修复函数。** 用户实测撞到过一个坏存档:
    一个 30 词的学习结果包里,前 10 个 id 各出现了两次(20 个唯一词)。
    表现是"我学了 20 个词,包却说 30 个,而且前 10 个是重复的"。

    去重本来由 :func:`attach_words` 负责,但那个实现依赖"包当前的内容" ——
    只要有一条路径能绕过它(或者包的状态在两次写入之间被谁动过),
    重复就会**安静地写进存档**,而且再也不会自己消失。所以:
    存档里出现重复时,得有个地方能收拾它。
    """
    seen = set()
    unique = []
    for word_id in pack.word_ids:
        if word_id in seen:
            continue
        seen.add(word_id)
        unique.append(word_id)
    removed = len(pack.word_ids) - len(unique)
    if removed:
        pack.word_ids = unique
    return removed


def attach_words(pack: WordPack, words: List[Word]) -> int:
    """把一批词加进词包,返回新增了几个。

    按 id 去重、**保持传进来的先后**:同一天学第二场时,这一场学过的词
    可能已经在当天的结果包里了(早上学过一遍),重复 append 会让词包
    里的 id 列表越滚越长,而界面上的词数也跟着虚高。

    ⚠️ **先把包里的重复清理掉再判断。** 判据是 `word.id in pack.word_ids`,
    所以只有在"包自己是干净的"前提下才成立;包里本来就有重复的话,
    这个判据仍然是对的,但那个重复会一直留在存档里。先调一次
    :func:`dedupe_word_ids` 让它自我修复。

    这里刻意不动 `word.source_packs` —— 那个字段记的是"这个词是从哪个
    词表包来的"(导入/手工建的包),结果包不参与。以前两者混着写,
    导致删一个词表包时会误判"这个词还有人要"。
    """
    dedupe_word_ids(pack)
    seen = set(pack.word_ids)
    added = 0
    for word in words:
        # 同一批里传进重复的 id 也要挡掉:两处都判,才能保证"加完之后
        # 这个列表一定没有重复",而不是"大概没有"
        if word.id in seen:
            continue
        seen.add(word.id)
        pack.word_ids.append(word.id)
        added += 1
    return added


def find_today_result_pack(packs: List[WordPack],
                           today: date) -> Optional[WordPack]:
    """今天已经建过的那一个学习结果包;没有就返回 None。

    只认 `PACK_TYPE_STUDY` 且 `created_at == today`:考试包(exam)有它
    自己的 exam 快照,把今天的学习记录并进去会让那份快照变得对不上;
    昨天的包更不能并 —— 那正是用户抱怨的"词包堆积"。

    一天里有多个时取**最新的一个**,因为那才是用户心里"今天那一个"。
    不靠列表顺序判断:app.packs 是新包 append 到**末尾**的,顺序和
    "由新到旧"正好相反;而包 id 是 `pack_YYYYMMDD_NNN` 递增的,
    比 id 字符串大小最稳,跟列表怎么排没关系。
    """
    day = today.isoformat()
    candidates = [pack for pack in packs
                  if pack.pack_type == PACK_TYPE_STUDY and pack.created_at == day]
    if not candidates:
        return None
    return max(candidates, key=lambda pack: pack.id)
