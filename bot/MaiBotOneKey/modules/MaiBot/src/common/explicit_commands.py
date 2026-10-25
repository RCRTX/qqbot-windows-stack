"""明确指令的统一文本匹配，不依赖插件运行时。"""
import re

AT_PREFIX = r"(?:@[^\s]+[ \t]*)?"
QA_COMMAND_PATTERN = rf"^\s*{AT_PREFIX}/?问答(?:\s+(?P<question>\S[\s\S]*))?\s*$"
QA_COMMAND_RE = re.compile(QA_COMMAND_PATTERN)
FAVOR_RANK_PATTERN = rf"^\s*{AT_PREFIX}/?好感度排行榜\s*$"
FAVOR_RANK_RE = re.compile(FAVOR_RANK_PATTERN)
