"""本子自动整理（2026-10-22 用户：「还是不会用本子和长期记忆什么的」）。

**诊断结论**（当天实测）：
* 读的一侧全都通 —— A_memorix 每天自动写 ~60 条记忆、`query_memory` 一天被调 22 次、
  检索结果会进回复器的【决策提供的辅助参考】、本子块同时进规划器和回复器。
* 唯一没发生的是**写**：`save_memory` / `correct_memory` / `write_notebook` 调用数 **0**。
  模型在"决定下一步动作"时几乎不会自愿写记忆——这是模型行为，不是配置问题。

所以这里加一条**不依赖模型自愿**的自动链路：每隔一段时间扫一遍有活动的群，
攒够消息就让**低优先级**模型挑 0~2 页写进本子；没有值得留的就空着，不为了写而写。

和 `memory_flow_service`（人物事实回写）同一套骨架：enqueue 式后台 worker +
`@with_llm_low_priority`（不标优先级会跟前台规划器抢 LLM 闸门，导致回复变慢/超时）。
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.common.logger import get_logger
from src.common.message_repository import find_messages
from src.config.config import global_config

logger = get_logger("notebook_consolidation")

_KIND = "manual"
_MAX_TITLE = 60
_MAX_BODY = 2000


@dataclass
class _GroupState:
    last_run: float = 0.0
    day: str = ""
    pages_today: int = 0


class NotebookConsolidationService:
    """定时把"它自己想留的"写进小本子。"""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stopping = False
        self._lock = asyncio.Lock()
        self._states: Dict[str, _GroupState] = {}
        self._extractor: Any = None
        self._db_path_cache: str = ""

    # ------------------------------------------------------------ 生命周期
    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stopping = False
        self._task = asyncio.create_task(self._worker_loop(), name="NotebookConsolidation")
        logger.info("[本子] 自动整理服务已启动")

    async def shutdown(self) -> None:
        self._stopping = True
        task = self._task
        self._task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # noqa: BLE001
                logger.debug("[本子] 自动整理停止时异常: %s", type(exc).__name__)
        logger.info("[本子] 自动整理服务已停止")

    async def _worker_loop(self) -> None:
        # 启动后先缓 60 秒，别和开机那一堆初始化抢
        await asyncio.sleep(60)
        while not self._stopping:
            try:
                await self._sweep_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 后台任务绝不能自己死掉
                logger.warning("[本子] 自动整理本轮失败: %s", type(exc).__name__)
            cfg = global_config.notebook
            interval = max(60, int(getattr(cfg, "auto_consolidate_interval", 900) or 900))
            await asyncio.sleep(interval)

    # ------------------------------------------------------------ 主流程
    async def _sweep_once(self) -> int:
        cfg = global_config.notebook
        if not cfg.enabled or not getattr(cfg, "auto_consolidate", True):
            return 0
        interval = max(60, int(getattr(cfg, "auto_consolidate_interval", 900) or 900))
        window = max(300, int(getattr(cfg, "auto_consolidate_window", 1800) or 1800))
        min_msgs = max(1, int(getattr(cfg, "auto_consolidate_min_messages", 8) or 8))
        max_per_day = max(0, int(getattr(cfg, "auto_consolidate_max_per_day", 2) or 0))

        db_path = self._resolve_db_path(getattr(cfg, "db_path", "") or "")
        if not db_path:
            return 0

        now = time.time()
        today = datetime.now().strftime("%Y-%m-%d")
        groups = self._active_sessions(window)
        logger.debug("[本子] 本轮扫描：%s 个活跃会话", len(groups))
        written = 0
        for gid in groups:
            state = self._states.setdefault(gid, _GroupState())
            if state.day != today:
                state.day, state.pages_today = today, 0
            if max_per_day and state.pages_today >= max_per_day:
                continue
            if now - state.last_run < interval:
                continue
            state.last_run = now

            rows = await asyncio.to_thread(
                find_messages, session_id=gid, start_time=now - window, end_time=now,
                limit=200, limit_mode="latest",
            )
            if len(rows) < min_msgs:
                logger.debug("[本子] 会话 %s… 只有 %s 条，跳过", gid[:8], len(rows))
                continue
            text = self._format_messages(rows)
            if not text:
                continue
                continue
            pages = await self._extract_pages(text)
            for title, body in pages:
                if max_per_day and state.pages_today >= max_per_day:
                    break
                ok = self._append_page(db_path, today, title, body)
                if ok:
                    state.pages_today += 1
                    written += 1
        if written:
            logger.info("[本子] 自动整理写了 %s 页", written)
        return written

    # ------------------------------------------------------------ 取群
    @staticmethod
    def _active_sessions(window: int) -> List[str]:
        """最近 window 秒内有消息的会话（`session_id`，不是群号）。

        ⚠️ `SessionMessage` **没有 `group_id` 属性**（2026-10-22 踩过：按 group_id 取
        永远拿到空，自动整理一遍都不会跑）。群名要从 `message_info.group_info.group_name` 拿。
        """

        now = time.time()
        try:
            rows = find_messages(start_time=now - window, end_time=now, limit=500, limit_mode="latest")
        except Exception as exc:  # noqa: BLE001
            logger.debug("[本子] 查活动会话失败: %s", type(exc).__name__)
            return []
        seen: List[str] = []
        for row in rows:
            sid = str(getattr(row, "session_id", "") or "").strip()
            if sid and sid not in seen:
                seen.append(sid)
        return seen

    @staticmethod
    def _format_messages(rows: List[Any]) -> str:
        """把最近的消息压成一段纯文本（限长，防 prompt 爆炸）。"""

        lines: List[str] = []
        budget = 6000
        for row in rows:
            stamp = getattr(row, "timestamp", None)
            dt = stamp.strftime("%m-%d %H:%M") if hasattr(stamp, "strftime") else ""
            info = getattr(row, "message_info", None)
            user = getattr(getattr(info, "user_info", None), "user_nickname", "") or ""
            text = str(getattr(row, "processed_plain_text", "") or "").strip()
            if not text:
                continue
            line = f"[{dt}] {user}: {text}"
            lines.append(line)
            budget -= len(line)
            if budget <= 0:
                break
        return "\n".join(lines[-120:])

    # ------------------------------------------------------------ 模型抽取
    @staticmethod
    def _prompt() -> str:
        return (
            "你是鱼/示例角色，在写自己的小本子。下面是最近的一段群聊原文。\n"
            "只挑**你自己想留着**的东西：一句让你在意的话、一个约定、一次让你有情绪的互动、"
            "一个你想改掉的错。\n"
            "要求：\n"
            "1. 用第一人称「我」写，标题必须带「我」。\n"
            "2. 没有值得留的就返回空数组，不要为了写而写，也不要记流水账。\n"
            "3. 不要把别人没说过的话写成他们说的；分不清是谁说的就别点名。\n"
            "4. 每页正文 30~300 字，普通段落，不写总结。\n"
            '输出纯JSON：{"pages":[{"title":"标题","body":"正文"}]}，pages 可以是空数组。'
        )

    async def _extract_pages(self, chat_text: str) -> List[tuple]:
        """低优先级调模型挑页；任何失败都当"没有可写"。

        🔴 `llm_low_priority()` 不能省：不标就和前台规划器平级抢 LLM 闸门，
        排队会拖慢回复（2026-10-13 踩过，补标了图片描述/emoji视觉/启发式记忆三个）。
        """

        try:
            from src.llm_models.llm_priority import llm_low_priority
            from src.services.llm_service import LLMServiceClient

            if self._extractor is None:
                self._extractor = LLMServiceClient(
                    task_name="utils", request_type="Notebook.auto_consolidate"
                )
            with llm_low_priority():
                response = await self._extractor.generate_response(
                    self._prompt() + "\n\n【最近的群聊】\n" + chat_text
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("[本子] 自动整理模型调用失败: %s", type(exc).__name__)
            return []

        raw = str(getattr(response, "response", "") or "").strip()
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except Exception:
            try:
                from json_repair import repair_json

                data = repair_json(raw, return_objects=True)
            except Exception:  # noqa: BLE001
                return []
        if not isinstance(data, dict):
            return []
        pages = data.get("pages")
        if not isinstance(pages, list):
            return []
        out: List[tuple] = []
        for page in pages:
            if not isinstance(page, dict):
                continue
            title = " ".join(str(page.get("title") or "").split())[:_MAX_TITLE]
            body = str(page.get("body") or "").strip()[:_MAX_BODY]
            if title and body and "我" in title:
                out.append((title, body))
        return out[:2]

    # ------------------------------------------------------------ 落库
    def _append_page(self, db_path: str, day: str, title: str, body: str) -> bool:
        """追加到今天的 manual 页（同一天只有一页，追加写）。"""

        now = datetime.now().isoformat(timespec="seconds")
        try:
            con = sqlite3.connect(db_path, timeout=5.0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[本子] 打不开日记库: %s", type(exc).__name__)
            return False
        try:
            con.row_factory = sqlite3.Row
            row = con.execute(
                "SELECT id, body FROM notebook_entries WHERE date=? AND kind=?", (day, _KIND)
            ).fetchone()
            if row is None:
                con.execute(
                    "INSERT INTO notebook_entries(date,kind,title,body,created_at,source_entry_id) "
                    "VALUES (?,?,?,?,?,NULL)",
                    (day, _KIND, title, body, now),
                )
            else:
                merged = f"{row['body']}\n\n{body}".strip()
                con.execute(
                    "UPDATE notebook_entries SET body=?, created_at=? WHERE id=?",
                    (merged[: _MAX_BODY * 2], now, row["id"]),
                )
            con.commit()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("[本子] 写页失败: %s", type(exc).__name__)
            return False
        finally:
            con.close()

    @staticmethod
    def _resolve_db_path(configured: str = "") -> str:
        """本子库路径：配置优先，其次环境变量，最后按项目相对位置找。"""

        env = os.environ.get("MAIBOT_NOTEBOOK_DB", "").strip()
        candidates: List[str] = []
        if configured and str(configured).strip():
            candidates.append(str(configured).strip())
        if env:
            candidates.append(env)
        here = os.path.dirname(os.path.abspath(__file__))
        for base in (here, *[os.path.dirname(here)]):
            candidates.append(os.path.join(base, "..", "..", "..", "..", "qq-monitor", "data", "diary.db"))
            candidates.append(os.path.join(base, "qq-monitor", "data", "diary.db"))
        for candidate in candidates:
            try:
                if os.path.isfile(candidate):
                    return os.path.abspath(candidate)
            except OSError:
                continue
        return ""


notebook_consolidation_service = NotebookConsolidationService()
