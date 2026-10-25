"""「闭关学习」模式（2026-10-13 用户定稿：下指令后一段时间不回答消息，专心学习）。

为什么需要
----------
后台学习（表达/黑话/行为/高频词）一次是 4 个 LLM 批次，而硅基流动这个账号的
实际并发≈1 —— 白天群里一热闹，学习就和前台回复抢同一条通道，表现是说话卡顿。
所以默认让学习只在半夜跑（见 ``learning_window.py``）。

但有时候人就是想让它**现在**学：群里聊了一整天，攒了一堆没消化的料。于是加一个
手动开关 —— 下达指令后进入「闭关」：

  · 一段时间内**不回复任何消息**（@ 也不回），把唯一的 LLM 通道让给学习；
  · 期间把攒下来的群消息分批喂给学习器（表达/黑话/行为/高频词）；
  · 到点自动出关；也可以手动喊「出关」提前结束；
  · **半夜的自动学习照常跑** —— 闭关只是在夜间窗口之外额外放行，不冲突。

跨进程
------
下达指令的是**监控进程**（qq-monitor 的关键词回复），真正学习的是**麦麦进程**。
两边靠 ``data/study_mode.json`` 通信（监控写、麦麦读，按 mtime 热重载）。
所以这个模块**只用标准库**，监控那边按文件路径直接加载它（不 import `src.*` 包，
免得触发麦麦那一大坨初始化）。

状态文件
--------
``data/study_mode.json``：

    {
      "active": true,              // 是否在闭关
      "until_ts": 1760352000.0,    // 出关时间戳（time.time() 口径）
      "started_at": "2026-10-13 10:40:00",
      "duration_minutes": 30,
      "requester": "1000000008",   // 谁下的令
      "group_id": "1000000007",
      "source": "keyword_reply",
      // 下面几个是参数，改完下一轮生效，不用重启
      "default_minutes": 30,       // 不带时长时的默认闭关分钟数
      "max_minutes": 180,          // 上限（防手滑来个 99999）
      "min_minutes": 5,            // 下限
      "batch_interval_seconds": 90,// 闭关期间每隔多久喂一批
      "batch_messages": 20,        // 攒够这么多条也可以提前喂
      "history_batch_messages": 120 // 刚闭关时回头咀嚼的历史条数
    }
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE_FILE = os.path.join(_ROOT, "data", "study_mode.json")

DEFAULT_STATE: Dict[str, Any] = {
    "active": False,
    "until_ts": 0.0,
    "started_at": "",
    "duration_minutes": 0,
    "requester": "",
    "group_id": "",
    "source": "",
    # ---- 参数（改完下一轮生效）----
    "default_minutes": 30,
    "max_minutes": 180,
    "min_minutes": 5,
    "batch_interval_seconds": 90,
    "batch_messages": 20,
    "history_batch_messages": 120,
    "_说明": (
        "闭关学习：指令下达后一段时间内不回消息，专心学表达/黑话/行为/高频词。"
        "半夜的自动学习照常（这个开关只在夜间窗口之外额外放行）。"
        "active=true 且 until_ts 未到 = 闭关中；到点自动出关。"
    ),
}

# 热重载缓存：文件 mtime 变了才重新读
_CACHE: Dict[str, Any] = {"mtime": -1.0, "state": None}

# 时长解析用的中文数字（「半小时」「两小时」）
_CN_DIGITS = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "半": 0.5,
}


def _now() -> float:
    return time.time()


def load_state(force: bool = False) -> Dict[str, Any]:
    """读状态（按 mtime 热重载；文件坏了用默认值，绝不抛）。"""
    state = _CACHE.get("state")
    if state is not None and not force:
        try:
            mtime = os.path.getmtime(STATE_FILE)
        except OSError:
            mtime = -1.0
        if mtime == _CACHE.get("mtime"):
            return state
    state = dict(DEFAULT_STATE)
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            state.update({k: v for k, v in loaded.items() if not k.startswith("_")})
    except FileNotFoundError:
        pass                                   # 没这个文件就用默认值（= 没在闭关）
    except Exception:                          # noqa: BLE001
        pass                                   # 文件坏了也别把学习/回复模块带崩
    _CACHE["state"] = state
    try:
        _CACHE["mtime"] = os.path.getmtime(STATE_FILE)
    except OSError:
        _CACHE["mtime"] = -1.0
    return state


def write_state(patch: Dict[str, Any]) -> Dict[str, Any]:
    """局部更新状态（读-改-写，原子替换），返回写后的完整状态。

    监控和麦麦都可能写，所以这里是**合并**而不是覆盖 —— 免得一边把另一边的
    字段（比如 requester）抹掉。
    """
    merged = dict(load_state(force=True))
    merged.update({k: v for k, v in (patch or {}).items() if not str(k).startswith("_")})
    merged["_说明"] = DEFAULT_STATE["_说明"]
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_FILE)            # 原子替换，麦麦那边不会读到半个文件
    except Exception:                          # noqa: BLE001
        pass                                   # 写失败最多是闭关不生效，不能让它抛穿
    return load_state(force=True)


def clamp_minutes(minutes: Any) -> int:
    """把时长钳到 [min_minutes, max_minutes]；给了个没法解析的值就用 default。"""
    state = load_state()
    try:
        default_minutes = int(state.get("default_minutes") or 30)
    except (TypeError, ValueError):
        default_minutes = 30
    try:
        max_minutes = int(state.get("max_minutes") or 180)
    except (TypeError, ValueError):
        max_minutes = 180
    try:
        min_minutes = int(state.get("min_minutes") or 5)
    except (TypeError, ValueError):
        min_minutes = 5
    if min_minutes < 1:
        min_minutes = 1
    if max_minutes < min_minutes:
        max_minutes = min_minutes
    try:
        value = int(float(minutes))
    except (TypeError, ValueError):
        return max(min_minutes, min(default_minutes, max_minutes))
    if value <= 0:
        return max(min_minutes, min(default_minutes, max_minutes))
    return max(min_minutes, min(value, max_minutes))


def parse_duration_minutes(text: str) -> Optional[int]:
    """从「闭关 30」「学习半小时」「闭关 1 小时」里抠出分钟数；抠不到返回 None。

    只认两种写法，免得把随便一句话里的数字当成长度：
      · 纯数字（可带「分钟/分/m」）：30、30分钟、30m
      · 中文量词：半小时 / 一小时 / 两小时 / 一个半小时
    """
    import re

    t = str(text or "").strip()
    if not t:
        return None

    # 先把中文数字换成阿拉伯数字（「一个半小时」「两小时」），十按 10 处理
    t2 = t
    for word, digit in _CN_DIGITS.items():
        if word in ("半",):
            continue                                # 「半」留着给下面的「半小时/个半」用
        t2 = t2.replace(word, str(int(digit)) if digit != 0.5 else "0.5")

    # 「1 个半小时 / 一个半小时」→ 1.5 小时
    m = re.search(r"(\d+(?:\.\d+)?)\s*个?\s*半\s*(小时|钟头)", t2)
    if m:
        return clamp_minutes(int(round((float(m.group(1)) + 0.5) * 60)))
    # 「2 小时 / 两小时 / 1h」
    m = re.search(r"(\d+(?:\.\d+)?)\s*(小时|钟头|h)(?![a-zA-Z])", t2, re.I)
    if m:
        return clamp_minutes(int(round(float(m.group(1)) * 60)))
    # 「半小时」
    if re.search(r"半\s*(小时|钟头)", t):
        return clamp_minutes(30)

    m = re.search(r"(\d+(?:\.\d+)?)\s*(分钟|分|m(?:in)?)\b", t, re.I)
    if m:
        return clamp_minutes(int(round(float(m.group(1)))))

    m = re.search(r"(?<![\d.])(\d{1,4})(?![\d.])", t)
    if m:
        return clamp_minutes(int(m.group(1)))
    return None


def activate(minutes: Any = None, *, requester: str = "", group_id: str = "",
             source: str = "keyword_reply", now: Optional[float] = None) -> Dict[str, Any]:
    """开始闭关，返回写后的状态。"""
    state = load_state(force=True)
    if minutes is None:
        try:
            minutes = int(state.get("default_minutes") or 30)
        except (TypeError, ValueError):
            minutes = 30
    duration = clamp_minutes(minutes)
    started = float(now if now is not None else _now())
    return write_state({
        "active": True,
        "until_ts": started + duration * 60.0,
        "started_at": datetime.fromtimestamp(started).strftime("%Y-%m-%d %H:%M:%S"),
        "duration_minutes": duration,
        "requester": str(requester or ""),
        "group_id": str(group_id or ""),
        "source": str(source or ""),
    })


def deactivate(*, source: str = "keyword_reply") -> Dict[str, Any]:
    """提前出关（到点了不用调，is_active 自己会判断）。"""
    return write_state({
        "active": False,
        "until_ts": 0.0,
        "duration_minutes": 0,
        "source": str(source or ""),
    })


def remaining_seconds(now: Optional[float] = None) -> float:
    """还剩多少秒出关；没在闭关返回 0。"""
    state = load_state()
    if not state.get("active"):
        return 0.0
    try:
        until = float(state.get("until_ts") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    left = until - float(now if now is not None else _now())
    return left if left > 0 else 0.0


def is_active(now: Optional[float] = None) -> bool:
    """当前是否在闭关（到点自动算失效，不写文件 —— 免得两个进程互相覆盖）。"""
    return remaining_seconds(now) > 0.0


def status(now: Optional[float] = None) -> Dict[str, Any]:
    """给日志/面板用的一份快照。"""
    state = load_state()
    left = remaining_seconds(now)
    return {
        "active": left > 0.0,
        "remaining_seconds": round(left, 1),
        "remaining_minutes": round(left / 60.0, 1),
        "duration_minutes": state.get("duration_minutes") or 0,
        "started_at": state.get("started_at") or "",
        "requester": state.get("requester") or "",
        "group_id": state.get("group_id") or "",
        "default_minutes": state.get("default_minutes") or 30,
        "max_minutes": state.get("max_minutes") or 180,
    }


def status_text(now: Optional[float] = None) -> str:
    """一句话状态（进日志用）。"""
    snap = status(now)
    if not snap["active"]:
        return "未闭关"
    return (f"闭关学习中（还剩 {snap['remaining_minutes']:.0f} 分钟，"
            f"{snap['started_at']} 起，{snap['duration_minutes']} 分钟）")


def until_text(now: Optional[float] = None) -> str:
    """出关时刻的 HH:MM（给群里的回执用）。"""
    left = remaining_seconds(now)
    if left <= 0:
        return ""
    return datetime.fromtimestamp(_now() + left).strftime("%H:%M")


def setting(key: str, fallback: Any) -> Any:
    """取一个参数（配置文件里没有就用 fallback）。"""
    state = load_state()
    value = state.get(key)
    return fallback if value is None else value


def ensure_default_file() -> str:
    """文件不存在就写一份默认（返回值便于探针断言）。"""
    if os.path.exists(STATE_FILE):
        return STATE_FILE
    write_state({})
    return STATE_FILE


# 兼容旧名（和 learning_window.allowed 一个路子，方便探针/日志里混用）
active = is_active
