# -*- coding: utf-8 -*-
"""示例插件:给词表增加一种 Markdown 导出格式。

**这个文件夹是用来被抄的。** 想写自己的插件,把这里复制一份改名,
改掉 plugin.json 里的信息和下面的 register(),就成了。

插件的最小结构就是两个文件:

    plugins/你的插件名/
    ├── plugin.json      清单:名字、版本、要求的内核接口版本
    └── __init__.py      入口:一个 register(registry) 函数

内核启动时会扫描 plugins/ 下的每个子文件夹,读出清单,校验 api_version,
然后调用 register(registry)。你能做的事情全在 core/interfaces.py 里,
那里列着所有可以替换的部件。

三条值得记住的规矩:
  1. register() 里**不要做耗时的事**。它是在程序启动时被调用的,
     导入一大堆数据会让用户觉得软件卡住了。要读文件请留到真正用到时。
  2. register() 里**不要连网**。这个软件承诺离线可用,
     插件在启动时联网会让断网的用户永远打不开它。
  3. 出错不要紧,但要知道会被跳过。任何异常都会被内核接住、写进
     save/logs/errors.log,然后这个插件不生效 —— 游戏照常启动。
     所以改完之后如果发现没效果,先去那个日志里看一眼。
"""

from pathlib import Path
from typing import Dict, List

from core.interfaces import WordPackExporter
from core.models import Word


class MarkdownExporter(WordPackExporter):
    """把词表导成 Markdown 列表,按「组合」分组。

    比 CSV 多出来的那点价值就是这个分组:导进 Notion、语雀或者
    手机备忘录里复习时,分好组的列表才读得下去。
    """

    name = "markdown"                                    # 内部名,英文
    title = "Markdown(按组合分组,适合贴进笔记软件)"      # 显示给用户的名字

    def export(self, words: List[Word], path: Path) -> Path:
        # path 是用户输入的名字,可能没带后缀 —— 导出器自己决定加什么
        target = path.with_suffix(".md")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self._render(words), encoding="utf-8")
        return target

    def _render(self, words: List[Word]) -> str:
        """拼出整份 Markdown。"""
        lines: List[str] = ["# 单词表", "",
                            "共 %d 个词。用「鲸鱼单词食堂」导出。" % len(words), ""]
        for group, members in self._grouped(words).items():
            lines.append("## %s" % (group or "未分组"))
            lines.append("")
            for word in members:
                lines.append(self._render_word(word))
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _grouped(words: List[Word]) -> Dict[str, List[Word]]:
        """按「组合」分组。

        用 dict 而不是 itertools.groupby —— groupby 只合并相邻的相同项,
        而词表里同组的词未必挨着。dict 在 Python 3.7+ 保持插入顺序,
        所以组的先后还是词表里的先后。
        """
        grouped: Dict[str, List[Word]] = {}
        for word in words:
            grouped.setdefault(word.group or "", []).append(word)
        return grouped

    @staticmethod
    def _render_word(word: Word) -> str:
        """一个词条渲染成一行(有例句就多缩进一行)。"""
        line = "- **%s**" % word.word
        if word.phonetic:
            line += " `%s`" % word.phonetic
        line += " — %s" % word.translation
        if word.example:
            line += "\n  - 例:%s" % word.example
        return line


def register(registry) -> None:
    """内核启动时调用这里。把上面那个导出器登记进去就够了。

    登记之后它会自动出现在「单词设置 → 导出」的格式列表里 ——
    界面不需要为你改任何代码,这正是注册表存在的意义。
    """
    registry.register_exporter(MarkdownExporter.name, MarkdownExporter)
