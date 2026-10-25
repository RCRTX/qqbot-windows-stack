"""麦麦自己的小本子（2026-10-21 接入）。

本子由 qq-monitor 的 diary_keeper 每天写完日记后生成，住在
``qq-monitor/data/diary.db`` 的 ``notebook_entries`` 表里（``kind='self'``）。
在本次接入之前它一直是"只写不读"的——麦麦半夜写，自己聊天时却看不到，
规划器里也从来没有任何一段关于"我自己"的延续材料。

本模块只做三件事：
1. 以 **只读** 方式打开那个库（URI ``mode=ro``，不加写锁，不影响监控写入）；
2. 取最近几页、按字数截断，拼成一段塞给规划器的提示词；
3. 任何异常（库不存在、被锁、表结构变了、内容为空）都**静默返回空串**——
   聊天链路绝不能因为"本子没翻开"而断。

配置项见 ``src/config/official_configs.py`` 的 ``NotebookConfig``；
注入点见 ``chat_loop_service.py`` 的 ``_build_notebook_block``。
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterator, Optional

try:  # 生产环境：走麦麦统一日志
    from src.common.logger import get_logger

    logger = get_logger("maisaka.notebook_context")
except Exception:  # 探针按文件路径独立导入时没有包上下文，退化为标准库日志
    import logging

    logger = logging.getLogger("maisaka.notebook_context")


_DB_RELATIVE = ("qq-monitor", "data", "diary.db")
"""监控侧日记库的相对位置；按「从近到远」逐级向上找，兼容项目整体搬家。"""

_BLOCK_HEADER = "【我自己的小本子】"
_BLOCK_INTRO = (
    "下面几页是我自己写下的念头，是每天写完日记之后留给自己的，"
    "不是聊天记录，也不是别人要我记的内容。"
)
_BLOCK_FOOTER = (
    "用法：这是我用来延续自己的材料——合适的时候可以自然提起、接着想、"
    "承认自己改了主意；不相关就不提，不要逐字复读，也不要拿里面的情绪去质问任何人。"
    "别记错：这些是我当时写下的主观感受，不等于别人真的说过那些话，人名、时间、"
    "数字拿不准就别下定论。群聊里尤其注意——本子是我的私事，不是谈资，"
    "别把里面具体的细节抖出去，也别把没发生在群里的事说成群里发生的。"
)

# 缓存：本子一天只多一页，没必要每轮都查库
_lock = threading.Lock()
_cache: dict[str, Any] = {"key": None, "ts": 0.0, "block": ""}


def resolve_db_path(configured: str = "") -> Optional[Path]:
    """确定日记库路径：配置优先，其次环境变量，最后按相对位置逐级向上找。"""

    candidates: list[Path] = []
    if configured and str(configured).strip():
        candidates.append(Path(str(configured).strip()))
    env_path = os.environ.get("MAIBOT_NOTEBOOK_DB", "").strip()
    if env_path:
        candidates.append(Path(env_path))
    here = Path(__file__).resolve()
    for base in here.parents:
        candidates.append(base.joinpath(*_DB_RELATIVE))
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def fetch_pages(db_path: Path, limit: int, max_chars: int, pinned_only: bool = False) -> list[tuple[str, str, str]]:
    """取出要看的页：**置顶页永远在最前**，后面跟最近几页，总字数不超过 ``max_chars``。

    2026-10-22：加置顶（`pinned=1`）—— 妈妈留下的那页必须每次都在，
    不能被"只取最近 N 页"挤掉。没有 pinned 列的老库自动退回旧行为。

    任何读取异常都向上抛，由调用方决定降级——这里不做静默吞掉，
    方便探针区分「真的没有页」和「读失败了」。
    """

    limit = max(1, int(limit))
    max_chars = max(200, int(max_chars))
    # mode=ro：只读打开，绝不创建文件、绝不给监控的写入加锁
    uri = f"file:{db_path.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=2.0)
    rows: list[tuple[str, str, str]] = []
    try:
        took_pinned = False
        try:
            pinned_rows = con.execute(
                "SELECT date, title, body FROM notebook_entries "
                "WHERE pinned=1 AND body IS NOT NULL ORDER BY id ASC",
            ).fetchall()
            took_pinned = True
        except sqlite3.Error:
            pinned_rows = []          # 老库没有 pinned 列：当没有置顶页
        recent_rows = [] if pinned_only else con.execute(
            "SELECT date, title, body FROM notebook_entries "
            "WHERE date IS NOT NULL AND body IS NOT NULL "
            + ("" if not took_pinned else "AND (pinned IS NULL OR pinned=0) ")
            + "ORDER BY date DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        rows = list(pinned_rows) + list(recent_rows)
    finally:
        con.close()

    pages: list[tuple[str, str, str]] = []
    budget = max_chars
    for date, title, body in rows:
        date = str(date or "").strip()
        title = str(title or "").strip() or "无题"
        body = " ".join(str(body or "").split())  # 压掉换行与连续空白，省 token
        if not body:
            continue
        if len(body) > budget:
            body = body[: max(0, budget - 1)].rstrip() + "…"
        pages.append((date, title, body))
        budget -= len(body) + len(title) + 8
        if budget <= 0:
            break
    return pages


def render_block(pages: list[tuple[str, str, str]]) -> str:
    """把取回的页拼成提示词段落；没有页就返回空串（调用方据此整段不注入）。"""

    if not pages:
        return ""
    lines = [_BLOCK_HEADER, _BLOCK_INTRO]
    for date, title, body in pages:
        # 日期只留月-日，年份对模型没有意义还占 token
        short_date = date[5:] if len(date) >= 10 else date
        lines.append(f"- {short_date}《{title}》：{body}")
    lines.append(_BLOCK_FOOTER)
    return "\n".join(lines)


def build_notebook_block(
    *,
    enabled: bool = True,
    db_path: str = "",
    limit: int = 5,
    max_chars: int = 1800,
    cache_seconds: int = 300,
    pinned_only: bool = False,
) -> str:
    """供规划器/回复器调用的入口：带 TTL 缓存，任何失败都返回空串。

    ``pinned_only=True`` 只取置顶页（妈妈留的那页）——群聊默认不注入私人本子，
    但身份核心那页应该到哪儿都在。
    """

    if not enabled:
        return ""
    cache_seconds = max(0, int(cache_seconds))
    key = (str(db_path or ""), int(limit), int(max_chars), bool(pinned_only))
    now = time.monotonic()
    with _lock:
        if _cache["key"] == key and now - _cache["ts"] < cache_seconds:
            return _cache["block"]

    block = ""
    try:
        resolved = resolve_db_path(db_path)
        if resolved is not None:
            block = render_block(fetch_pages(resolved, limit, max_chars, pinned_only=pinned_only))
        else:
            # 2026-10-22：这里原来是 debug —— 本子一旦找不到库就整段静默消失，
            # 排查时完全看不到（用户只会觉得"他没看本子"）。改成 warning。
            logger.warning(
                "[本子] 找不到 diary.db（配置路径=%r），本次不注入。"
                "可在 bot_config.toml 的 [notebook] db_path 写绝对路径，"
                "如 C:/QQBotStack/qq-monitor/data/diary.db。",
                db_path,
            )
    except Exception as exc:  # 读不到就不能影响聊天，静默降级
        logger.warning("本子读取失败，本次不注入: %s", type(exc).__name__)
        block = ""

    with _lock:
        _cache.update(key=key, ts=now, block=block)
    return block


def reset_cache() -> None:
    """清空缓存（测试用）。"""

    with _lock:
        _cache.update(key=None, ts=0.0, block="")
