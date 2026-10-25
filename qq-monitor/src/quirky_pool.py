
"""QQ bot stack component."""























from __future__ import annotations

import json
import os
import random
import threading
import time
from typing import Any, Dict, List, Optional, Sequence

from src.logger import setup_logger

logger = setup_logger("quirky_pool")


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


DEFAULT_POOL_FILE = os.path.join(
    REPO_ROOT, "bot", "MaiBotOneKey", "modules", "MaiBot", "data", "quirky_lines.json")


DEFAULT_MAX_CHARS = 0    


RECENT_KEEP = 30






BLOCKED_PATTERNS = (
    
    "狗罕见", "沙皮", "贩剑", "nmsl", "傻逼", "傻*", "死全家", "滚出中国",
    "原批", "欧泡",
    
    "不转不是中国人", "转发到", "转发这", "发到99", "发到 99", "发到你各个群",
    "群里的中国人", "日本人就给", "美国人就给", "发到你所在",
)


def blocked_reason(text: str) -> str:
    """QQ bot stack component."""
    low = str(text or "").lower()
    for pat in BLOCKED_PATTERNS:
        if pat.lower() in low:
            return pat
    return ""


def pool_path(configured: Any = "") -> str:
    """QQ bot stack component."""
    p = str(configured or "").strip()
    return os.path.abspath(os.path.expanduser(p)) if p else DEFAULT_POOL_FILE


def load_items(path: str) -> List[Dict[str, Any]]:
    """QQ bot stack component."""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if not isinstance(d, dict):
        raise ValueError("怪话库顶层不是 JSON 对象")
    items = d.get("items")
    if not isinstance(items, list):
        raise ValueError("怪话库里没有 items 数组")
    return [i for i in items if isinstance(i, dict)]


def usable(items: Sequence[Dict[str, Any]], max_chars: int = DEFAULT_MAX_CHARS
           ) -> List[Dict[str, Any]]:
    """QQ bot stack component."""




    out: List[Dict[str, Any]] = []
    for it in items or []:
        if not isinstance(it, dict) or it.get("enabled", True) is False:
            continue
        text = str(it.get("text") or "").strip()
        if not text:
            continue
        if max_chars and max_chars > 0 and len(text) > max_chars:
            continue
        if blocked_reason(text):
            continue
        out.append(it)
    return out


def choose(items: Sequence[Dict[str, Any]], recent: Optional[Sequence[str]] = None,
           rng: Any = None, max_chars: int = DEFAULT_MAX_CHARS) -> Optional[Dict[str, Any]]:
    """QQ bot stack component."""




    pool = usable(items, max_chars)
    if not pool:
        return None
    skip = {str(x) for x in (recent or [])}
    fresh = [it for it in pool if str(it.get("id") or "") not in skip]
    if fresh:
        pool = fresh
    lowest = min(int(it.get("used", 0) or 0) for it in pool)
    tied = [it for it in pool if int(it.get("used", 0) or 0) == lowest]
    return (rng or random).choice(tied)


def mark_used(path: str, item_id: str, now: Optional[float] = None) -> bool:
    """QQ bot stack component."""



    item_id = str(item_id or "").strip()
    if not item_id or not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        items = d.get("items") if isinstance(d, dict) else None
        if not isinstance(items, list):
            return False
        for it in items:
            if isinstance(it, dict) and str(it.get("id") or "") == item_id:
                it["used"] = int(it.get("used", 0) or 0) + 1
                it["last_used"] = float(time.time() if now is None else now)
                break
        else:
            return False                     
        d["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        tmp = path + ".tmp-quirky"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)                
        return True
    except (OSError, ValueError) as e:
        logger.warning(f"回写怪话使用次数失败（不影响发送）: {type(e).__name__}: {e}")
        return False


class QuirkyPool:
    """QQ bot stack component."""

    def __init__(self, path: Any = DEFAULT_POOL_FILE, max_chars: int = DEFAULT_MAX_CHARS,
                 recent_keep: int = RECENT_KEEP, label: str = "怪话库") -> None:
        self.path = pool_path(path)
        self.max_chars = int(max_chars or 0)
        self.recent_keep = int(recent_keep or 0)
        
        self.label = str(label or "怪话库")
        self._lock = threading.Lock()
        self._items: List[Dict[str, Any]] = []
        self._mtime = -1.0
        self._recent: List[str] = []
        self._reads = 0
        self._sends = 0
        self._errors = 0
        self.reload(force=True)

    
    def reload(self, force: bool = False) -> bool:
        """QQ bot stack component."""
        try:
            mtime = os.path.getmtime(self.path) if os.path.exists(self.path) else 0.0
        except OSError:
            mtime = 0.0
        if not force and mtime == self._mtime:
            return False
        try:
            items = load_items(self.path) if mtime else []
        except Exception as e:
            self._errors += 1
            logger.error(f"怪话库读取失败（沿用上一次的 {len(self._items)} 条）: "
                         f"{type(e).__name__}: {e}")
            return False
        with self._lock:
            self._items = items
            self._mtime = mtime
            self._reads += 1
        logger.info(f"{self.label}已载入：{len(items)} 条（{self.path}）")
        return True

    def items(self) -> List[Dict[str, Any]]:
        self.reload()
        with self._lock:
            return list(self._items)

    def count(self) -> int:
        """QQ bot stack component."""
        return len(usable(self.items(), self.max_chars))

    
    def pick(self) -> Optional[Dict[str, Any]]:
        """QQ bot stack component."""
        self.reload()
        with self._lock:
            items = list(self._items)
            recent = list(self._recent)
        item = choose(items, recent, max_chars=self.max_chars)
        if item:
            text = str(item.get("text") or "").strip()
            logger.debug(f"挑中怪话 {item.get('id')}（used={item.get('used', 0)}）: "
                         f"{text[:30]}")
        return item

    def takeover(self, item: Optional[Dict[str, Any]]) -> str:
        """QQ bot stack component."""
        if not item:
            return ""
        text = str(item.get("text") or "").strip()
        if not text:
            return ""
        rid = str(item.get("id") or "")
        if rid:
            with self._lock:
                self._recent.append(rid)
                if self.recent_keep > 0:
                    self._recent = self._recent[-self.recent_keep:]
        
        if rid:
            mark_used(self.path, rid)
        self._sends += 1
        return text

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {"path": self.path, "max_chars": self.max_chars,
                    "items": len(self._items), "usable": self.count(),
                    "reads": self._reads, "sends": self._sends, "errors": self._errors,
                    "recent": len(self._recent)}
