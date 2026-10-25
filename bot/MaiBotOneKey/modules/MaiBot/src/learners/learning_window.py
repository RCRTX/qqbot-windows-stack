"""后台学习的「时间窗」控制（2026-10-13 用户定稿：学习挪到半夜跑）。

为什么需要
----------
硅基流动这个账号的实际并发≈1（实测：并发 2 个 → 2.0s/74.5s；串行 3 个 → 19s 全部完成）。
麦麦的后台学习（表达/黑话/行为/高频词）一次就是 4 个 LLM 批次，而触发间隔只有 30 秒 ——
白天群里一热闹，后台学习就把唯一的通道占满，前台回复只能排在它后面等，
表现就是「说话卡顿」。

所以这里给后台学习加一个时间窗：只有落在窗口内（默认凌晨 1:00~6:00）才放行，
白天一律跳过。白天被跳过的学习不会丢 —— 待学习的消息一直在攒，
窗口一开就会触发（runtime 侧的 pending 计数天然满足）。

例外：**手动「闭关学习」**（``study_mode.py``）。下达指令后一段时间内不回消息、
专心学习，那期间不受这个窗口限制（闭关本来就是为了现在学）；半夜的自动学习照常。

配置
----
热重载文件 ``data/learning_window.json``（改完下一轮生效，不用重启）：

    {
      "enabled": true,          // false = 不做任何限制（恢复原 behavior）
      "start": "01:00",         // 窗口起点（含）
      "end": "06:00",           // 窗口终点（不含）；跨零点自动处理
      "catch_up": true          // 窗口开启后的第一轮是否强制跑（补白天的量）
    }

环境变量 ``MAIBOT_LEARN_WINDOW`` 可整体覆盖，格式 ``"01:00-06:00"``、
``"off"``（不限制）、``"always"``（总是允许）—— 调试用，优先级最高。
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, time as dtime
from typing import Any, Dict, Optional, Tuple

from src.learners.study_mode import is_active as study_mode_active

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WINDOW_FILE = os.path.join(_ROOT, "data", "learning_window.json")

DEFAULT_WINDOW: Dict[str, Any] = {
    "enabled": True,
    "start": "01:00",
    "end": "06:00",
    "catch_up": True,
    "_说明": (
        "后台学习（表达/黑话/行为/高频词）只在窗口内跑 —— 硅基流动账号并发≈1，"
        "白天跑学习会把前台回复挤到后面等，表现是说话卡顿。"
        "enabled=false 恢复原行为；start/end 支持跨零点；catch_up=true 时窗口刚开的第一轮强制跑。"
    ),
}

# 热重载缓存：文件 mtime 变了才重新读
_CACHE: Dict[str, Any] = {"mtime": -1.0, "cfg": None}


def _parse_hm(value: Any, fallback: str) -> Tuple[int, int]:
    """把 "01:30" / "1:30" 解析成 (时, 分)；解析不了用 fallback。"""
    try:
        text = str(value or "").strip()
        hh, mm = text.split(":", 1)
        hour, minute = int(hh), int(mm)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    except Exception:  # noqa: BLE001
        pass
    hh, mm = fallback.split(":", 1)
    return int(hh), int(mm)


def load_config(force: bool = False) -> Dict[str, Any]:
    """读配置（按 mtime 热重载）。"""
    cfg = _CACHE.get("cfg")
    if cfg is not None and not force:
        try:
            mtime = os.path.getmtime(WINDOW_FILE)
        except OSError:
            mtime = -1.0
        if mtime == _CACHE.get("mtime"):
            return cfg
    cfg = dict(DEFAULT_WINDOW)
    try:
        with open(WINDOW_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            cfg.update({k: v for k, v in loaded.items() if not k.startswith("_")})
    except FileNotFoundError:
        pass                                  # 没这个文件就用默认值
    except Exception:                         # noqa: BLE001
        pass                                  # 坏了也别让学习模块崩
    _CACHE["cfg"] = cfg
    try:
        _CACHE["mtime"] = os.path.getmtime(WINDOW_FILE)
    except OSError:
        _CACHE["mtime"] = -1.0
    return cfg


def _in_window(now_dt: datetime, start: Tuple[int, int], end: Tuple[int, int]) -> bool:
    """判断 now 是否落在 [start, end) 内；支持跨零点（如 22:00-06:00）。"""
    minutes = now_dt.hour * 60 + now_dt.minute
    s = start[0] * 60 + start[1]
    e = end[0] * 60 + end[1]
    if s == e:
        return True                            # 起止相同 = 全天
    if s < e:
        return s <= minutes < e
    return minutes >= s or minutes < e         # 跨零点


def learning_allowed(now_dt: Optional[datetime] = None) -> bool:
    """当前是否允许后台学习跑（闭关期间一律放行）。"""
    now_dt = now_dt or datetime.now()
    # 手动闭关：用户下令「现在就学」—— 不看时间窗（半夜的自动学习也照常，两者是或关系）
    try:
        if study_mode_active():
            return True
    except Exception:                         # noqa: BLE001
        pass                                  # 状态文件坏了就当没闭关，退回时间窗判断

    override = str(os.environ.get("MAIBOT_LEARN_WINDOW") or "").strip()
    if override:
        low = override.lower()
        if low in ("off", "none", "0", "false"):
            return True
        if low in ("always", "on", "1", "true"):
            return True
        if "-" in override:
            a, b = override.split("-", 1)
            return _in_window(now_dt, _parse_hm(a, "01:00"), _parse_hm(b, "06:00"))

    cfg = load_config()
    if not cfg.get("enabled"):
        return True
    return _in_window(now_dt,
                      _parse_hm(cfg.get("start"), "01:00"),
                      _parse_hm(cfg.get("end"), "06:00"))


def window_open_since(now_dt: Optional[datetime] = None, catch_up: bool = True) -> Optional[float]:
    """本轮窗口的开启时间戳（用于「补跑」判断）；不在窗口内返回 None。

    窗口刚打开的第一轮返回窗口起点，调用方可据此判断「上次学习还在窗口开启之前」
    → 放行补跑，把白天攒的量一次吃掉。
    """
    if not catch_up:
        return None
    now_dt = now_dt or datetime.now()
    if not learning_allowed(now_dt):
        return None
    cfg = load_config()
    if not cfg.get("enabled") or not cfg.get("catch_up"):
        return None
    start = _parse_hm(cfg.get("start"), "01:00")
    opened = now_dt.replace(hour=start[0], minute=start[1], second=0, microsecond=0)
    if opened > now_dt:                        # 跨零点窗口，起点属于前一天
        from datetime import timedelta
        opened -= timedelta(days=1)
    return opened.timestamp()


def learning_window_reason(now_dt: Optional[datetime] = None) -> str:
    """给日志用的一句话状态说明。"""
    now_dt = now_dt or datetime.now()
    try:
        if study_mode_active():
            from src.learners.study_mode import status_text as study_status_text

            return f"手动闭关中（{study_status_text()}），本轮放行学习"
    except Exception:                         # noqa: BLE001
        pass
    if learning_allowed(now_dt):
        return f"后台学习窗口内（{now_dt:%H:%M}）"
    cfg = load_config()
    return (f"不在后台学习窗口（{now_dt:%H:%M}，窗口 "
            f"{cfg.get('start')}~{cfg.get('end')}），本轮跳过")


def ensure_default_file() -> str:
    """若配置文件不存在则写一份默认（返回值便于日志/探针断言）。"""
    if os.path.exists(WINDOW_FILE):
        return WINDOW_FILE
    os.makedirs(os.path.dirname(WINDOW_FILE), exist_ok=True)
    with open(WINDOW_FILE, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_WINDOW, f, ensure_ascii=False, indent=2)
    load_config(force=True)
    return WINDOW_FILE


# 兼容旧名：早期调用点/探针里用的是 allowed()
allowed = learning_allowed
