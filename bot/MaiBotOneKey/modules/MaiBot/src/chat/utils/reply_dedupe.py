"""出站回复的「防复读」检查。

背景（本机旧版 0.11.0 的实测教训，2026-09-18）：麦麦会在同一个聊天流里把几乎一样的
一句话连着发两遍，用户直接看得见。旧版把这个判断挂在回复生成链里、并且每次都查数据库。

搬到 1.2.5 后生成链（maisaka）和存储层（A_memorix）都换掉了，所以这里改成
**进程内环形缓存**：

1. 出站消息最终都汇聚到 ``send_service._send_via_platform_io``，在那里拦最省事，
   也不用依赖 1.x 新的消息表结构（表名/字段在 1.x 换过一次，查库写死字段风险高）；
2. 每条回复都查一次库没必要，进程内缓存是 O(1)，没有 SQL 抖动；
3. 代价是重启后缓存清空 —— 只影响「刚重启那一小会儿可能重复一次」，可以接受。

**2026-10-11 用户要求：群里的复读拦截整体关掉。**
原话是「你把群里的复读功能关了」——所以 ``_enabled()`` 现在**默认返回 False**，
整条链路不再拦截任何出站回复（下面 ``is_duplicate_reply`` 里的判定逻辑全部保留，
只是没人调用它了；要重新打开就把环境变量 ``MAIBOT_DEDUPE_REPLY`` 设成 1/true）。

为什么保留代码而不是删掉：判定逻辑本身是对的（数字感知那条尤其值钱），
万一以后又想开，改一个常量就回来了；删掉的话得从头再踩一遍坑。
"""

from collections import deque
from difflib import SequenceMatcher
from typing import Deque, Dict, Tuple

import os
import re
import time

from src.common.logger import get_logger

logger = get_logger("reply_dedupe")

WINDOW_SECONDS = 600
"""(秒) 只跟这个时间窗内的历史发言比对。"""

MAX_HISTORY_PER_SESSION = 8
"""每个聊天流最多记这么多条近期发言。"""

SIMILARITY_THRESHOLD = 0.72
"""模糊判重的相似度阈值；旧版线上实测这个值能拦住复读又不误杀。"""

_DISABLED_VALUES = {"0", "false", "off", "no"}

# 2026-10-11 用户明确要求「把群里的复读功能关了」→ 默认关闭。
# 想重新打开就把这个常量改成 True（或者临时设环境变量 MAIBOT_DEDUPE_REPLY=1）。
DEDUPE_REPLY_DEFAULT_ON = False

_AT_MARK_PATTERN = re.compile(r"@<[^>]*>")
_NOISE_PATTERN = re.compile(r"[\s，。？！?!~、,.～…：:;；\[\]【】@]")
# 数字（含中文数量词）：抽掉它以后的骨架用于"同模板判定"。
_DIGIT_PATTERN = re.compile(r"\d+")

_history: Dict[str, Deque[Tuple[float, str]]] = {}


def _skeleton(text: str) -> str:
    """把数字抽成统一占位符后的"骨架"，用来识别「同一模板 + 不同数据」。

    为什么需要它（2026-10-11 实测，真 bug）：
      用户 A 问「好感度」→ 麦麦答「你在我这儿 509」；
      用户 B 也问 → 正确答案是「你在我这儿 357」——
      但防复读把这两句的相似度算成 0.93 > 0.72，**直接把 B 的回答拦掉了**，
      于是 B 问了两遍什么都没收到（日志里能看到「防复读：跳过重复回复」紧跟着
      一条正确的好感度直答）。这类「固定句式 + 每次不同的数字」是**正确回复**，
      不是复读，必须放行。

    Args:
        text: 归一化后的文本。

    Returns:
        str: 数字被换成 ``#`` 的骨架。
    """
    return _DIGIT_PATTERN.sub("#", text)


def _enabled() -> bool:
    """判断防复读是否启用。

    2026-10-11 用户要求群里的复读拦截整体关掉，所以**默认返回 False**。
    环境变量 ``MAIBOT_DEDUPE_REPLY`` 仍然可以**覆盖**这个默认值：
    设成 1/true/on 就强制打开，设成 0/false/off/no 就强制关闭；不设则看
    ``DEDUPE_REPLY_DEFAULT_ON``（当前 False）。

    Returns:
        bool: 是否启用防复读。
    """
    raw = os.getenv("MAIBOT_DEDUPE_REPLY")
    if raw is not None and raw.strip():
        return raw.strip().lower() not in _DISABLED_VALUES
    return DEDUPE_REPLY_DEFAULT_ON


def normalize_reply_text(text: str) -> str:
    """归一化回复文本，用于复读比对。

    ⚠️ 2026-09-18 修过的地方（别删）：**必须先剥引用前缀**。机器人引用别人时
    ``processed_plain_text`` 会变成 ``[回复<xxx:123> 的消息：…] 正文``，同一句话
    带前缀和不带前缀的相似度会被稀释到 0.72 阈值以下 —— 防复读会**静默失效**
    （旧版当天全量日志 0 次命中，且不报错、不留痕）。

    前缀还可能**嵌套**（回复里又套一层回复），一条正则剥不干净，但正文永远在
    最后一个 ``]`` 之后，按这个切最稳。

    Args:
        text: 原始回复文本。

    Returns:
        str: 去掉引用前缀、@ 标记、空白与标点后的文本。
    """
    value = str(text or "")
    idx = value.rfind("]")
    if idx >= 0 and len(value[idx + 1 :].strip()) >= 2:
        value = value[idx + 1 :]
    value = _AT_MARK_PATTERN.sub("", value)
    return _NOISE_PATTERN.sub("", value)


def _recent_entries(session_id: str, now: float) -> Deque[Tuple[float, str]]:
    """取出该聊天流的近期发言缓存，并顺手清掉过期的。"""
    entries = _history.get(session_id)
    if entries is None:
        entries = deque(maxlen=MAX_HISTORY_PER_SESSION)
        _history[session_id] = entries
    while entries and now - entries[0][0] > WINDOW_SECONDS:
        entries.popleft()
    return entries


def is_duplicate_reply(session_id: str, text: str) -> bool:
    """判断这条回复是不是近期在同一个聊天流里已经说过的。

    Args:
        session_id: 聊天流 ID。
        text: 本次准备发送的回复文本。

    Returns:
        bool: 判定为复读时返回 ``True``（调用方应跳过发送）。
    """
    if not _enabled() or not session_id or not text:
        return False

    normalized = normalize_reply_text(text)
    if len(normalized) < 2:
        return False

    now = time.time()
    skel = _skeleton(normalized)
    for sent_at, old_text in _recent_entries(session_id, now):
        if not old_text:
            continue
        if normalized == old_text:
            return True
        # 「同模板 + 不同数字」= 正常回答，不是复读（见 `_skeleton` 的注释）。
        # 2026-10-11：不加这条的话，「你在我这儿 509」会把它后面的
        # 「你在我这儿 357」整个拦掉 —— 用户问好感度收不到任何回复。
        old_skel = _skeleton(old_text)
        if skel == old_skel and skel != normalized and "#" in skel:
            continue
        if len(old_text) >= 4 and SequenceMatcher(None, normalized, old_text).ratio() > SIMILARITY_THRESHOLD:
            # 相似但只有数字不同 → 同样放行（SequenceMatcher 那 0.93 是数字撑出来的）
            if skel == old_skel and "#" in skel:
                continue
            return True
    return False


def remember_sent_reply(session_id: str, text: str) -> None:
    """记下一条**确实发出去**的回复，供后续比对。

    只有在发送成功后才调用：被拦下的回复不该进历史，否则一句话会被反复判重。

    Args:
        session_id: 聊天流 ID。
        text: 已发送的回复文本。
    """
    if not session_id or not text:
        return
    normalized = normalize_reply_text(text)
    if len(normalized) < 2:
        return
    _recent_entries(session_id, time.time()).append((time.time(), normalized))


def reset_history() -> None:
    """清空全部缓存（测试与手动排障用）。"""
    _history.clear()
