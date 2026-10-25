"""write_notebook 内置工具（2026-10-22）。

用户要求：「鱼的本子用法不对，应该记**他认为重要**的东西，在他发言的时候就应该去看」。

* 「看」：`subconscious` 那边已经改了 —— 本子现在同时进**规划器**和**回复器**提示词，
  群聊至少带上置顶的身份核心页。
* 「记重要的」：就是这个工具。以前本子只由 `diary_keeper.write_notebook` 在写完日记后
  自动生成一页，是"每天一本流水"的派生；麦麦自己**没有任何办法往本子里写东西**。
  现在它可以在对话中判断「这件事我想留着」，直接写一页。

落库位置与监控共用 `qq-monitor/data/diary.db` 的 `notebook_entries`：
同一天多次写会追加到同一页（kind='manual'），不会把本子刷成碎的。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.common.logger import get_logger
from src.config.config import global_config
from src.core.tooling import ToolExecutionContext, ToolExecutionResult, ToolInvocation, ToolSpec

from .context import BuiltinToolRuntimeContext

logger = get_logger("maisaka_builtin_notebook_write")

_MAX_TITLE = 60
_MAX_BODY = 2000
_KIND = "manual"


def tool_enabled() -> bool:
    """跟着小本子总开关走。"""

    try:
        return bool(global_config.notebook.enabled)
    except Exception:  # noqa: BLE001
        return False


def get_tool_spec(*, enabled: bool = True) -> ToolSpec:
    """获取 write_notebook 工具声明。"""

    return ToolSpec(
        name="write_notebook",
        description="往自己的小本子里写一页（记下你觉得重要的事、想留的一句话、一个念头）。",
        parameters_schema={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "这一页的标题，第一人称，带上“我”。",
                },
                "body": {
                    "type": "string",
                    "description": "正文。写你为什么想留着它，不用交代给谁看。",
                },
            },
            "required": ["title", "body"],
        },
        provider_name="maisaka_builtin",
        provider_type="builtin",
        enabled=enabled,
    )


def _resolve_db_path(configured: str = "") -> Optional[Path]:
    """本子库路径：配置优先，否则按项目相对位置逐级向上找。"""

    candidates: list[Path] = []
    if configured and str(configured).strip():
        candidates.append(Path(str(configured).strip()))
    here = Path(__file__).resolve()
    for base in here.parents:
        candidates.append(base / "qq-monitor" / "data" / "diary.db")
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


async def handle_tool(
    tool_ctx: BuiltinToolRuntimeContext,
    invocation: ToolInvocation,
    context: Optional[ToolExecutionContext] = None,
) -> ToolExecutionResult:
    """执行 write_notebook：往今天的本子页里写/追加。"""

    del context
    title = " ".join(str(invocation.arguments.get("title") or "").split())[:_MAX_TITLE]
    body = str(invocation.arguments.get("body") or "").strip()[:_MAX_BODY]
    if not title or not body:
        return tool_ctx.build_failure_result(invocation.tool_name, "标题和正文都要有。")

    db_path = _resolve_db_path(getattr(global_config.notebook, "db_path", "") or "")
    if db_path is None:
        return tool_ctx.build_failure_result(invocation.tool_name, "没找到本子（库文件不存在）。")

    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().isoformat(timespec="seconds")
    try:
        con = sqlite3.connect(str(db_path), timeout=5.0)
        try:
            con.row_factory = sqlite3.Row
            row = con.execute(
                "SELECT id, body FROM notebook_entries WHERE date=? AND kind=?", (today, _KIND)
            ).fetchone()
            if row is None:
                con.execute(
                    "INSERT INTO notebook_entries(date,kind,title,body,created_at,source_entry_id) "
                    "VALUES (?,?,?,?,?,NULL)",
                    (today, _KIND, title, body, now),
                )
                con.commit()
                page_id = con.execute(
                    "SELECT id FROM notebook_entries WHERE date=? AND kind=?", (today, _KIND)
                ).fetchone()[0]
                merged = False
            else:
                merged_body = f"{row['body']}\n\n{body}".strip()
                con.execute(
                    "UPDATE notebook_entries SET body=?, created_at=? WHERE id=?",
                    (merged_body[:_MAX_BODY * 2], now, row["id"]),
                )
                con.commit()
                page_id, merged = int(row["id"]), True
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001 - 写不进去也不能影响这轮回复
        logger.warning("写本子失败: %s", type(exc).__name__)
        return tool_ctx.build_failure_result(
            invocation.tool_name, f"本子没写进去（{type(exc).__name__}）。"
        )

    logger.info("[本子] 写下一页 id=%s merged=%s title=%s", page_id, merged, title)
    return tool_ctx.build_success_result(
        invocation.tool_name,
        content=f"写进本子了：{title}",
        structured_content={"success": True, "page_id": page_id, "date": today, "appended": merged},
    )
